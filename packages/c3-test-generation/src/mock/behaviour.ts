// C3-07 mock behaviour from the scenario's Given/When steps (FR4, SO2).
// The rule (C3-05) decides WHETHER to mock. Here the model only says WHAT the mock does, as a small
// structured answer. C3 checks the answer; a bad answer gets one retry with the problems listed, then
// the rule default stays (marked `source: "rule_default"`, so confidence routing can see it).
// The structured part (kind/value) is kept in c3/work/mock_behaviour.json for the Jest writer (C3-10);
// mock_decisions.json gets summary + rationale + derived_from_steps + model (contract fields only).
import { parseJsonAnswer, type ChatMessage, type ModelClient } from '../model/index.js';
import type { C3Inputs, C3ScenarioInput, ScenarioStep } from '../input/types.js';
import type { MockDecision, MockDecisionsFile } from './decisions.js';

export const BEHAVIOUR_PROMPT_VERSION = '0.2.0';

/** What a mocked function does when the code under test calls it. */
export const BEHAVIOUR_KINDS = [
  'returns', // returns `value`
  'returns_input', // returns its first argument (merged over `value` when `value` is an object)
  'throws', // throws an Error with `error_message`
  'resolves', // async: resolves to `value`
  'rejects', // async: rejects with an Error with `error_message`
] as const;
export type BehaviourKind = (typeof BEHAVIOUR_KINDS)[number];

/** Structured mock behaviour (internal, not a contract field). */
export interface StructuredBehaviour {
  kind: BehaviourKind;
  value?: unknown; // JSON value
  error_message?: string;
  /** returns_input on a function that returns a Promise: the mock is `async`. */
  async?: true;
}

/** One line of c3/work/mock_behaviour.json. */
export interface BehaviourRecord extends Partial<StructuredBehaviour> {
  decision_id: string;
  scenario_id: string;
  source: 'model' | 'rule_default';
  model?: string;
  attempts: number;
  /** Problems found in model answers (empty when the first answer was fine). */
  problems: string[];
  /** Things to review that did not reject the answer, e.g. "a Given step says 'fails' but the mock succeeds". */
  warnings: string[];
}

export interface BehaviourWorkFile {
  prompt_version: string;
  model: string | null;
  records: BehaviourRecord[];
}

/** The model's JSON answer, before checking. */
interface RawAnswer {
  steps?: unknown;
  kind?: unknown;
  value?: unknown;
  error_message?: unknown;
  summary?: unknown;
  rationale?: unknown;
}

const MAX_TEXT = 300;

/** Given/When steps the model may cite, numbered S1.. in scenario order. */
export function setupSteps(
  sc: C3ScenarioInput,
): { id: string; step: ScenarioStep; text: string }[] {
  return sc.steps
    .filter((s) => s.keyword !== 'Then')
    .map((step, i) => ({ id: `S${i + 1}`, step, text: `${step.keyword} ${step.text}` }));
}

const isAsync = (d: MockDecision) => /\bPromise\s*</.test(d.dependency.type_signature ?? '');

/** Then steps, shown to the model as context only (it may not cite them). */
function outcomeSteps(sc: C3ScenarioInput): string[] {
  return sc.steps.filter((s) => s.keyword === 'Then').map((s) => `${s.keyword} ${s.text}`);
}

/** Does the code under test use what the dependency returns? (`return dep(...)`, `x = dep(...)`, `dep(...).y`) */
export function usesResult(callSites: readonly string[], d: MockDecision): boolean {
  const sym = d.dependency.symbol === 'default' ? '' : d.dependency.symbol;
  const call = sym ? `\\b${sym.replace(/[$]/g, '\\$')}\\s*\\(` : '\\(';
  return callSites.some(
    (line) =>
      new RegExp(`(\\breturn\\b|[^=!<>]=(?!=)|\\bawait\\b).*${call}`).test(line) ||
      new RegExp(`${call}[^;]*\\)\\s*\\.`).test(line),
  );
}

/**
 * Build the chat messages for one mock decision. Deterministic: same input -> same prompt (cache key).
 * `callSites` are the source lines of the module under test that call the dependency.
 */
export function behaviourPrompt(
  sc: C3ScenarioInput,
  d: MockDecision,
  targetExports: string[],
  callSites: readonly string[] = [],
): { system: string; user: string } {
  const dep = d.dependency;
  const fn =
    dep.symbol === 'default'
      ? `the module '${dep.import_specifier}'`
      : `${dep.symbol}() from '${dep.import_specifier}'`;
  const steps = setupSteps(sc)
    .map((s) => `${s.id}: ${s.text}`)
    .join('\n');
  const outline = sc.isOutline
    ? `\nThis is a Scenario Outline. <name> placeholders change per Examples row; describe the behaviour that fits every row.`
    : '';
  const then = outcomeSteps(sc);
  const system =
    'You decide what a mocked dependency does in one unit test. ' +
    'The mock must make the situation in the Given and When steps true, so the test checks the code under test, not the mock. ' +
    'Answer with one JSON object and nothing else.';
  const user = [
    `Scenario: ${sc.scenarioName}`,
    `Function under test: ${targetExports.join(', ')} in ${sc.subject.modulePath}`,
    `Mocked dependency: ${fn}`,
    `Type signature: ${dep.type_signature ?? 'unknown'}${/=>\s*never\s*$/.test(dep.type_signature ?? '') ? ' (the real code only throws in tests, which is why it is mocked; this says nothing about the mock)' : ''}`,
    `Side effect: ${dep.side_effect}`,
    `Why it is mocked: ${d.reason}`,
    ...(callSites.length
      ? ['Where the function under test calls it:', ...callSites.map((l) => `  ${l.trim()}`)]
      : []),
    '',
    'Given/When steps (cite these by id):',
    steps + outline,
    ...(then.length
      ? ['', 'Expected outcome (context only, do not cite, do not copy into "value"):', ...then]
      : []),
    '',
    'Rules:',
    '1. If no step says the dependency fails, is down or is unavailable, the mock must succeed (returns, returns_input or resolves).',
    '2. Use throws/rejects only when a step says the dependency fails; put that failure in "error_message".',
    '3. If the function passes data to the dependency and uses what comes back, use returns_input (add fields the steps imply, e.g. a generated id, in "value").',
    '4. Do not return null when the function uses the result, unless a step says nothing is found.',
    '',
    'Example 1. Step S1: "Given the mail server is available". Code: return mailer.send(message);',
    '{"steps": ["S1"], "kind": "returns_input", "value": {"sent": true}, "error_message": null, "summary": "send() returns the message it was given, marked as sent.", "rationale": "S1 says the mail server is available, so sending succeeds."}',
    'Example 2. Step S1: "Given the mail server is down". Code: mailer.send(message);',
    '{"steps": ["S1"], "kind": "throws", "value": null, "error_message": "mail server is down", "summary": "send() throws an error saying the mail server is down.", "rationale": "S1 says the mail server is down, so sending fails."}',
    '',
    'Answer format:',
    '{"steps": ["S1"], "kind": "...", "value": null, "error_message": null, "summary": "...", "rationale": "..."}',
    '- steps: ids of the Given/When steps the behaviour comes from (at least one).',
    `- kind: one of ${BEHAVIOUR_KINDS.join(', ')}. Use resolves/rejects only if the function returns a Promise.`,
    '  returns: the mock returns "value". returns_input: it returns its first argument, with an object "value" merged under it.',
    '- value: a JSON value (number, string, boolean, object, array or null).',
    '- summary: what the mock returns or throws, in one plain sentence.',
    '- rationale: which step says so and why, in one sentence.',
  ].join('\n');
  return { system, user };
}

/** Check one model answer. Returns the problems found (empty = usable). */
export function checkAnswer(
  raw: RawAnswer,
  sc: C3ScenarioInput,
  d: MockDecision,
  callSites: readonly string[] = [],
): string[] {
  const problems: string[] = [];
  const all = setupSteps(sc);
  const ids = new Set(all.map((s) => s.id));
  let cited: string[] = [];
  if (!Array.isArray(raw.steps) || raw.steps.length === 0) {
    problems.push('"steps" must be a non-empty list of step ids like "S1"');
  } else {
    const bad = raw.steps.filter((s) => typeof s !== 'string' || !ids.has(s.trim().toUpperCase()));
    if (bad.length)
      problems.push(
        `"steps" has unknown ids ${JSON.stringify(bad)}; allowed: ${[...ids].join(', ')}`,
      );
    const wanted = new Set(raw.steps.map((s) => String(s).trim().toUpperCase()));
    cited = all.filter((s) => wanted.has(s.id)).map((s) => s.text);
  }
  if (typeof raw.kind !== 'string' || !(BEHAVIOUR_KINDS as readonly string[]).includes(raw.kind)) {
    problems.push(`"kind" must be one of ${BEHAVIOUR_KINDS.join(', ')}`);
  }
  const kind = raw.kind as BehaviourKind;
  if ((kind === 'returns' || kind === 'resolves') && !('value' in raw)) {
    problems.push(`"value" is required when kind is ${kind}`);
  }
  if (
    kind === 'returns_input' &&
    raw.value != null &&
    (typeof raw.value !== 'object' || Array.isArray(raw.value))
  ) {
    problems.push('"value" for returns_input must be an object or null');
  }
  if (
    (kind === 'throws' || kind === 'rejects') &&
    (typeof raw.error_message !== 'string' || !raw.error_message.trim())
  ) {
    problems.push(`"error_message" is required when kind is ${kind}`);
  }
  // Rule 1: a failing mock needs a step that says the dependency fails.
  if ((kind === 'throws' || kind === 'rejects') && !all.some((s) => NEGATIVE.test(s.text))) {
    problems.push(
      `kind ${kind} makes the dependency fail, but no Given/When step says it fails; the mock must succeed`,
    );
  }
  // Rule 4: null breaks code that uses the result, unless a step says nothing is found.
  if (
    (kind === 'returns' || kind === 'resolves') &&
    raw.value == null &&
    usesResult(callSites, d) &&
    !cited.some((t) => NOTHING.test(t))
  ) {
    problems.push(
      `the function uses what ${d.dependency.symbol}() returns, so "value" must not be null (use returns_input or a value the steps imply)`,
    );
  }
  // C3-14 batch (fix-6): the value must fit what the dependency returns. process.cwd() takes no input and returns
  // a string; returns_input with {"cwd": ...} made path.resolve() throw on correct code (eslint-23).
  const want = returnTypeOf(d);
  if (kind === 'returns_input' && takesNoInput(d)) {
    problems.push(
      `${d.dependency.symbol}() takes no input, so returns_input cannot work; use returns with a ${want ?? 'value'}`,
    );
  }
  if (
    (kind === 'returns' || kind === 'resolves') &&
    want &&
    raw.value != null &&
    typeof raw.value !== want
  ) {
    problems.push(`"value" must be a ${want}: ${d.dependency.symbol}() returns a ${want}`);
  }
  if ((kind === 'resolves' || kind === 'rejects') && d.dependency.type_signature && !isAsync(d)) {
    problems.push(
      `kind ${kind} needs a Promise, but the signature is ${d.dependency.type_signature}`,
    );
  }
  for (const f of ['summary', 'rationale'] as const) {
    const v = raw[f];
    if (typeof v !== 'string' || v.trim().length < 5) problems.push(`"${f}" must be a sentence`);
    else if (v.length > MAX_TEXT) problems.push(`"${f}" is longer than ${MAX_TEXT} characters`);
  }
  if ('value' in raw) {
    try {
      JSON.stringify(raw.value);
    } catch {
      problems.push('"value" is not a JSON value');
    }
  }
  return problems;
}

const NOTHING = /\b(no|not found|missing|empty|none|does not exist|unknown)\b/i;
const NEGATIVE =
  /\b(fail|fails|failed|failing|unavailable|down|offline|error|errors|timeout|times out|not available|not reachable|unreachable|rejects?|refuses?|crash(es|ed)?|broken)\b/i;

/** Review notes that do not reject the answer. */
function warningsFor(kind: BehaviourKind, cited: string[]): string[] {
  const neg = cited.some((t) => NEGATIVE.test(t));
  const fails = kind === 'throws' || kind === 'rejects';
  if (neg && !fails) return ['a cited step sounds like a failure, but the mock succeeds'];
  if (!neg && fails) return ['the mock fails, but no cited step mentions a failure'];
  return [];
}

/** If the signature returns a Promise, a sync kind becomes its async twin (deterministic fix-up). */
function fixAsync(
  kind: BehaviourKind,
  d: MockDecision,
): { kind: BehaviourKind; async?: true; note?: string } {
  if (!isAsync(d)) return { kind };
  if (kind === 'returns')
    return { kind: 'resolves', note: 'returns -> resolves (signature returns a Promise)' };
  if (kind === 'throws')
    return { kind: 'rejects', note: 'throws -> rejects (signature returns a Promise)' };
  if (kind === 'returns_input') return { kind, async: true };
  return { kind };
}

export interface DeriveOptions {
  /** Retries after a bad answer (default 1, so at most 2 calls per decision). */
  retries?: number;
  /** Export(s) each scenario tests (from C3-05). */
  targets?: ReadonlyMap<string, { exports: string[] }>;
  /** Source lines of the module under test that call the decision's dependency. */
  callSites?: (d: MockDecision) => string[];
  log?: (line: string) => void;
}

/**
 * C3-07: fill `behaviour` for every `mock` decision from the scenario's Given/When steps.
 * Returns a NEW mock_decisions file (input is not changed) and the work file for the Jest writer.
 */
export async function deriveMockBehaviours(
  file: MockDecisionsFile,
  inputs: C3Inputs,
  client: ModelClient,
  options: DeriveOptions = {},
): Promise<{ file: MockDecisionsFile; work: BehaviourWorkFile }> {
  const retries = options.retries ?? 1;
  const log = options.log ?? (() => {});
  const byId = new Map(inputs.scenarios.map((s) => [s.scenarioId, s]));
  const records: BehaviourRecord[] = [];
  const decisions: MockDecision[] = [];

  for (const d of file.decisions) {
    const sc = byId.get(d.scenario_id);
    if (d.decision !== 'mock' || !sc) {
      decisions.push(d);
      continue;
    }
    const targets = options.targets?.get(d.scenario_id)?.exports ?? sc.subject.exports;
    const sites = options.callSites?.(d) ?? [];
    const { system, user } = behaviourPrompt(sc, d, targets, sites);
    const messages: ChatMessage[] = [
      { role: 'system', content: system },
      { role: 'user', content: user },
    ];
    const problems: string[] = [];
    let accepted: { raw: RawAnswer; model: string } | undefined;
    let attempts = 0;
    for (let attempt = 0; attempt <= retries && !accepted; attempt++) {
      attempts++;
      const res = await client.complete({
        messages: [...messages],
        temperature: 0,
        maxTokens: 400,
        purpose: `C3-07 behaviour ${d.decision_id}`,
      });
      let raw: RawAnswer;
      try {
        raw = parseJsonAnswer<RawAnswer>(res.text);
      } catch (err) {
        raw = {};
        problems.push(`attempt ${attempts}: ${err instanceof Error ? err.message : String(err)}`);
      }
      const found = Object.keys(raw).length ? checkAnswer(raw, sc, d, sites) : [];
      if (Object.keys(raw).length && !found.length) {
        accepted = { raw, model: `${res.model}@${res.provider}` };
      } else {
        problems.push(...found.map((p) => `attempt ${attempts}: ${p}`));
        messages.push(
          { role: 'assistant', content: res.text },
          {
            role: 'user',
            content: `Your answer has problems:\n- ${(found.length ? found : ['not a JSON object']).join('\n- ')}\nAnswer again with one corrected JSON object.`,
          },
        );
      }
    }

    if (!accepted) {
      log(`  ${d.decision_id} model answer unusable after ${attempts} call(s); rule default kept`);
      records.push({
        decision_id: d.decision_id,
        scenario_id: d.scenario_id,
        source: 'rule_default',
        ...defaultStructured(d),
        attempts,
        problems,
        warnings: [],
      });
      decisions.push({
        ...d,
        behaviour: d.behaviour && {
          ...d.behaviour,
          rationale: `Model answer was not usable (${problems.length} problem(s), see c3/work/mock_behaviour.json); rule ${d.rule_id} default kept.`,
        },
      });
      continue;
    }

    const raw = accepted.raw;
    const steps = setupSteps(sc);
    const citedIds = [...new Set((raw.steps as string[]).map((s) => s.trim().toUpperCase()))];
    const cited = steps.filter((s) => citedIds.includes(s.id)).map((s) => s.text);
    const fixed = fixAsync(raw.kind as BehaviourKind, d);
    const structured: StructuredBehaviour = {
      kind: fixed.kind,
      ...(fixed.async ? { async: true as const } : {}),
      ...(raw.value !== undefined && raw.value !== null ? { value: raw.value } : {}),
      ...(typeof raw.error_message === 'string' && raw.error_message.trim()
        ? { error_message: raw.error_message.trim() }
        : {}),
    };
    const warnings = [...warningsFor(structured.kind, cited), ...(fixed.note ? [fixed.note] : [])];
    records.push({
      decision_id: d.decision_id,
      scenario_id: d.scenario_id,
      source: 'model',
      ...structured,
      model: accepted.model,
      attempts,
      problems,
      warnings,
    });
    decisions.push({
      ...d,
      behaviour: {
        derived_from_steps: cited,
        summary: (raw.summary as string).trim(),
        rationale: (raw.rationale as string).trim(),
        model: accepted.model,
      },
    });
    log(
      `  ${d.decision_id} ${structured.kind} from ${citedIds.join(',')}${warnings.length ? ` (review: ${warnings.join('; ')})` : ''}`,
    );
  }

  return {
    file: { ...file, decisions },
    work: { prompt_version: BEHAVIOUR_PROMPT_VERSION, model: client.modelTag, records },
  };
}

/** Rule-default behaviour as structured data (matches the default summary written by C3-05). */
export function defaultStructured(d: MockDecision): StructuredBehaviour {
  // fix-6: a dependency with a known primitive result gets a value of that type, never null
  // (process.cwd() -> '/project', so path.resolve() keeps working).
  const key = depKey(d);
  if (key in KNOWN_DEFAULTS) return { kind: 'returns', value: KNOWN_DEFAULTS[key] };
  const want = returnTypeOf(d);
  const typed = want === 'string' ? '' : want === 'number' ? 0 : want === 'boolean' ? false : null;
  switch (d.dependency.side_effect) {
    case 'database':
      return isAsync(d) ? { kind: 'returns_input', async: true } : { kind: 'returns_input' };
    case 'random':
      return { kind: 'returns', value: 0.5 };
    case 'time':
      return { kind: 'returns', value: 1760000000000 };
    case 'network':
    case 'io':
      return { kind: isAsync(d) ? 'resolves' : 'returns', value: typed };
    default:
      return { kind: 'returns', value: typed };
  }
}

/** Rule-default work records for a run without a model (`c3 run` with no .env). */
export function defaultBehaviourWork(file: MockDecisionsFile): BehaviourWorkFile {
  return {
    prompt_version: BEHAVIOUR_PROMPT_VERSION,
    model: null,
    records: file.decisions
      .filter((d) => d.decision === 'mock')
      .map((d) => ({
        decision_id: d.decision_id,
        scenario_id: d.scenario_id,
        source: 'rule_default' as const,
        ...defaultStructured(d),
        attempts: 0,
        problems: [],
        warnings: ['no model configured; rule default used'],
      })),
  };
}

/**
 * Jest code that gives one mocked function its behaviour (used by the Jest writer, C3-10).
 * `target` is the expression of the mocked function, e.g. `userRepository.save`.
 */
export function behaviourToJest(target: string, b: StructuredBehaviour): string {
  const lit = (v: unknown) => JSON.stringify(v ?? null);
  const err = (m?: string) => `new Error(${JSON.stringify(m ?? 'mocked failure')})`;
  switch (b.kind) {
    case 'returns':
      return `${target}.mockReturnValue(${lit(b.value)});`;
    case 'resolves':
      return `${target}.mockResolvedValue(${lit(b.value)});`;
    case 'returns_input': {
      const fn = b.async ? 'async (input)' : '(input)';
      return b.value && typeof b.value === 'object' && !Array.isArray(b.value)
        ? `${target}.mockImplementation(${fn} => ({ ...${lit(b.value)}, ...input }));`
        : `${target}.mockImplementation(${fn} => input);`;
    }
    case 'throws':
      return `${target}.mockImplementation(() => {\n  throw ${err(b.error_message)};\n});`;
    case 'rejects':
      return `${target}.mockRejectedValue(${err(b.error_message)});`;
  }
}

const depKey = (d: MockDecision) =>
  `${d.dependency.import_specifier.replace(/^node:/, '')}#${d.dependency.symbol}`;

/** Globals and built-ins whose result type is fixed (they have no type signature in the scan). */
const KNOWN_RETURNS: Record<string, 'string' | 'number' | 'boolean'> = {
  'process#cwd': 'string',
  'process#uptime': 'number',
  'Date#now': 'number',
  'Math#random': 'number',
  'os#hostname': 'string',
  'os#platform': 'string',
  'os#homedir': 'string',
  'os#tmpdir': 'string',
};
const NO_INPUT = new Set([
  'process#cwd',
  'process#uptime',
  'Date#now',
  'Math#random',
  'os#hostname',
  'os#platform',
  'os#homedir',
  'os#tmpdir',
]);
const KNOWN_DEFAULTS: Record<string, unknown> = { 'process#cwd': '/project' };

/** 'string' | 'number' | 'boolean' when the dependency is known to return that type (also through a Promise). */
export function returnTypeOf(d: MockDecision): 'string' | 'number' | 'boolean' | undefined {
  const known = KNOWN_RETURNS[depKey(d)];
  if (known) return known;
  const m = /=>\s*(?:Promise<\s*)?(string|number|boolean)\s*>?\s*$/.exec(
    d.dependency.type_signature ?? '',
  );
  return m ? (m[1] as 'string' | 'number' | 'boolean') : undefined;
}

/** True when the dependency is called without arguments (process.cwd(), Date.now(), a `() => ...` signature). */
export function takesNoInput(d: MockDecision): boolean {
  return NO_INPUT.has(depKey(d)) || /^\s*\(\s*\)\s*=>/.test(d.dependency.type_signature ?? '');
}
