// C3-08 typed assertions (FR6, SO3).
// One model call per scenario. The model does NOT write test code: it fills slots in a JSON answer
//   act        - the call of the function under test, with values from the Given/When steps
//   assertions - one or more per Then step, each with a category (equality, exception, state_change, range)
//                and the slots that category's fixed template needs (templates.ts).
// The model never sees the code of the function under test, only its parameter names, so the
// assertions follow the requirement (the Then steps), not the code.
// C3 checks every slot (parses, known names only, every Then step covered); a bad answer gets one retry,
// then the scenario is marked `failed` and C3-13 routes it to a stub. A rule-based category guess is kept
// next to the model's category; their agreement is a confidence signal (C3-13).
import { ts } from 'ts-morph';
import { parseJsonAnswer, type ChatMessage, type ModelClient } from '../model/index.js';
import type { C3Inputs, C3ScenarioInput } from '../input/types.js';
import type { BehaviourWorkFile } from '../mock/behaviour.js';
import type { MockDecisionsFile } from '../mock/decisions.js';
import type { ScannedExport } from '../scan/types.js';
import {
  BUILTIN_ERRORS,
  checkExpression,
  paramName,
  renderValue,
  replacePlaceholders,
} from './expr.js';

export const ASSERTION_PROMPT_VERSION = '0.6.0';
export const ASSERTION_CATEGORIES = ['equality', 'exception', 'state_change', 'range'] as const;
export type AssertionCategory = (typeof ASSERTION_CATEGORIES)[number];
export const STATE_CHANGES = ['called_with', 'called', 'not_called', 'called_times'] as const;
export type StateChange = (typeof STATE_CHANGES)[number];

/** One typed assertion: the category plus the slots its template needs. */
export interface AssertionSlot {
  then: string; // T1, T2, ...
  when?: { column: string; equals: string }; // outlines: only rows where column == equals
  category: AssertionCategory;
  actual?: string; // equality/range: code over `result`, e.g. 'result.age'
  expected?: unknown; // equality: JSON value ("<col>" = the row's value)
  min?: unknown;
  max?: unknown;
  min_inclusive?: boolean;
  max_inclusive?: boolean;
  error?: string | null; // exception: error class
  message?: string | null; // exception: text the error message contains
  target?: string; // state_change: mocked function, e.g. 'userRepository.save'
  change?: StateChange;
  args?: unknown[];
  times?: number;
}

/** One test the writer will make: a non-outline scenario has one case, an outline one per Examples row. */
export interface PlanCase {
  row?: number; // Examples row_index (outlines)
  assertions: number[]; // indexes into plan.assertions that hold for this case
  categories: AssertionCategory[]; // for test_manifest.json assertion_categories
}

/** One line of c3/work/assertion_plan.json. */
export interface ScenarioPlan {
  scenario_id: string;
  requirement_id: string;
  source: 'model' | 'failed';
  model?: string;
  attempts: number;
  problems: string[];
  function_under_test: string[];
  act?: string; // as the model wrote it, with <placeholders>
  act_code?: string; // placeholders replaced by parameter names
  await?: boolean;
  params: Record<string, string>; // Examples column -> parameter name
  quoted_columns: string[]; // columns written as "<col>" (passed as strings)
  assertions: AssertionSlot[];
  cases: PlanCase[];
  /** Rule-based guess for each (case, Then step). */
  rule_categories: { then: string; row?: number; category: AssertionCategory }[];
  /** Share of (case, Then step) pairs where the model's categories include the rule's guess. */
  category_agreement: number;
}

export interface AssertionWorkFile {
  prompt_version: string;
  model: string | null;
  plans: ScenarioPlan[];
}

// ---------------------------------------------------------------- rule-based category guess

const RULES: [AssertionCategory, RegExp][] = [
  [
    'exception',
    /\b(error|errors|throws?|thrown|rejects?|rejected|refuses?|refused|denied|invalid|fails?|failed|exception|not allowed)\b/i,
  ],
  [
    'range',
    /\b(between|at least|at most|no more than|no less than|within|greater than|less than|more than|fewer than|above|below|maximum|minimum|or more|or less|up to|in the range)\b/i,
  ],
  [
    'state_change',
    /\b(saved|stored|persisted|created|deleted|removed|updated|recorded|sent|called|written|added|logged|increases?|increased|decreases?|decreased|changes?|changed|becomes?|set to|is (not )?(saved|stored|called|sent))\b/i,
  ],
];

/** Rule-based category for one Then step text (first matching rule wins; default equality). */
export function ruleCategory(text: string): AssertionCategory {
  for (const [cat, re] of RULES) if (re.test(text)) return cat;
  return 'equality';
}

// ---------------------------------------------------------------- context

/** What the model and the checks know about one scenario. */
export interface PlanContext {
  sc: C3ScenarioInput;
  exports: ScannedExport[];
  targets: string[]; // function(s) under test (C3-05)
  mocks: { target: string; decision_id: string; summary?: string; mockFields?: string[] }[];
  params: Map<string, string>; // Examples column -> parameter name
  columnValues: Map<string, string[]>; // Examples column -> cell texts (rows in order)
}

/** Local variable name the Jest writer gives a mocked module ('./userRepository' -> 'userRepository'). */
export function mockLocalName(specifier: string): string {
  const base = specifier.replace(/\\/g, '/').split('/').filter(Boolean).pop() ?? 'dep';
  const stem = base.replace(/\.[cm]?[jt]sx?$|\.json$/, '').replace(/^node:/, '');
  const camel = stem.replace(/[-_.@]+([A-Za-z0-9])/g, (_m, c: string) => c.toUpperCase());
  const id = camel.replace(/[^A-Za-z0-9_$]/g, '') || 'dep';
  return /^[0-9]/.test(id) ? `m_${id}` : id;
}

/** The expression a state_change assertion uses for a mocked dependency, e.g. 'userRepository.save'. */
export function mockTarget(dep: {
  import_specifier: string;
  symbol: string;
  kind: string;
}): string {
  if (dep.kind === 'global_object') return `${dep.import_specifier}.${dep.symbol}`;
  const local = mockLocalName(dep.import_specifier);
  return dep.symbol === 'default' ? local : `${local}.${dep.symbol}`;
}

export function planContext(
  sc: C3ScenarioInput,
  exports: ScannedExport[],
  targets: string[],
  mockFile?: MockDecisionsFile,
  behaviour?: BehaviourWorkFile,
): PlanContext {
  const taken = new Set([...exports.map((e) => e.name), 'result']);
  const params = new Map<string, string>();
  const columnValues = new Map<string, string[]>();
  if (sc.isOutline) {
    const cols = Object.keys(sc.examples[0]?.values ?? {});
    for (const c of cols) {
      const p = paramName(c, taken);
      taken.add(p);
      params.set(c, p);
      columnValues.set(
        c,
        sc.examples.map((r) => r.values[c] ?? ''),
      );
    }
  }
  const mocks = (mockFile?.decisions ?? [])
    .filter((d) => d.scenario_id === sc.scenarioId && d.decision === 'mock')
    .map((d) => {
      const rec = behaviour?.records.find((r) => r.decision_id === d.decision_id);
      const v = rec?.value;
      const mockFields =
        v && typeof v === 'object' && !Array.isArray(v) ? Object.keys(v).sort() : undefined;
      return {
        target: mockTarget(d.dependency),
        decision_id: d.decision_id,
        summary: d.behaviour?.summary,
        ...(mockFields?.length ? { mockFields } : {}),
      };
    });
  return { sc, exports, targets, mocks, params, columnValues };
}

// ---------------------------------------------------------------- prompt

const signature = (e: ScannedExport) =>
  e.valueKind === 'class'
    ? `class ${e.name}${e.params?.length ? ` (constructor(${e.params.join(', ')}))` : ''}`
    : e.valueKind === 'function'
      ? `${e.isAsync ? 'async ' : ''}${e.name}(${(e.params ?? []).join(', ')})`
      : `${e.name} (a value)`;

function stepLines(sc: C3ScenarioInput): string[] {
  let s = 0;
  let t = 0;
  return sc.steps.map((st) =>
    st.keyword === 'Then'
      ? `T${++t}: ${st.keyword} ${st.text}`
      : `S${++s}: ${st.keyword} ${st.text}`,
  );
}

export function thenIds(sc: C3ScenarioInput): string[] {
  return sc.steps.filter((s) => s.keyword === 'Then').map((_s, i) => `T${i + 1}`);
}

/** The chat messages for one scenario. Deterministic: same input -> same prompt (cache key). */
export function assertionPrompt(ctx: PlanContext): { system: string; user: string } {
  const { sc } = ctx;
  const byName = new Map(ctx.exports.map((e) => [e.name, e]));
  const fut = ctx.targets.map((t) => (byName.get(t) ? signature(byName.get(t)!) : `${t}(...)`));
  const others = ctx.exports.filter((e) => !ctx.targets.includes(e.name)).map(signature);
  const mocks = ctx.mocks.length
    ? ctx.mocks.map((m) => `  ${m.target}${m.summary ? ` - ${m.summary}` : ''}`)
    : ['  none (do not use state_change)'];
  const rows = sc.isOutline
    ? [
        '',
        `Examples columns: ${[...ctx.params.keys()].join(', ')}. Rows:`,
        ...sc.examples.slice(0, 20).map(
          (r) =>
            `  ${r.rowIndex}: ${Object.entries(r.values)
              .map(([k, v]) => `${k}=${v}`)
              .join(', ')}`,
        ),
        'Write <column> placeholders (e.g. <age>) in "act" and in values; each row fills them in.',
      ]
    : [];
  const system =
    'You turn one BDD scenario into the parts of a Jest test. You do not write test code: you fill slots in one JSON object. ' +
    'Assertions come from the Then steps (the requirement), not from guessing how the code works. ' +
    'Answer with one JSON object and nothing else.';
  const user = [
    `Scenario: ${sc.scenarioName} (type: ${sc.scenarioType})`,
    `Module under test: ${sc.subject.modulePath}`,
    `Function under test: ${fut.join(' or ')}`,
    ...ctx.targets
      .map((t) => byName.get(t))
      .filter((e): e is ScannedExport => !!e?.doc)
      .map((e) => `Documented interface of ${e.name} (its JSDoc): ${e.doc}`),
    `Other exports: ${others.length ? others.join(', ') : 'none'}`,
    'Mocked dependencies (only these may be used in state_change):',
    ...mocks,
    '',
    'Steps:',
    ...stepLines(sc),
    ...rows,
    '',
    'Answer format: {"act": "...", "assertions": [ ... ]}',
    '- act: ONE JavaScript call of the function under test with the values from the Given/When steps, e.g. isValid("abc"). Only the function name, literals and <column> placeholders.',
    '       If the function returns a function and a step uses that function, call it in the same act, e.g. makeCheck(2)("x", 0).',
    '- assertions: at least one per Then step. Each has "then" (T1, T2, ...), "category" and its slots:',
    '  equality:     {"then": "T1", "category": "equality", "actual": "result", "expected": <JSON value>}',
    '                "actual" is "result" (what the call returns) or a part of it, e.g. "result.age" or "result.length".',
    '  exception:    {"then": "T1", "category": "exception", "error": "TypeError", "message": null}',
    '                the call throws; "error" is an exported error class, Error, TypeError or RangeError (or null).',
    '  state_change: {"then": "T1", "category": "state_change", "target": "<mocked dependency>", "change": "called_with", "args": [<JSON values>]}',
    '                "change" is called_with, called, not_called or called_times (with "times").',
    '  range:        {"then": "T1", "category": "range", "actual": "result", "min": 1, "max": 10, "min_inclusive": true, "max_inclusive": true}',
    ...(sc.isOutline
      ? [
          '  Add "when": {"column": "<column name>", "equals": "<cell text>"} when an assertion holds only for rows with that value.',
        ]
      : []),
    'Rules:',
    '1. "expected", "args", "min" and "max" are JSON values taken from the steps. Never work them out from the code.',
    '2. If the call throws, that test cannot also check "result".',
    '3. A Then step that says the value is not X: use equality with the opposite value (e.g. "is not valid" -> expected false).',
    '4. Never check a field that only a mock returns, also not inside called_with args: the test must check the function under test, not the mock.',
    '   called_with args may only use fields the act passes in or the steps name; do not invent fields such as an id or a status.',
    '5. If a Then step only says the action succeeds or is accepted and a mocked dependency is listed, check that it was called (state_change).',
    ...(sc.isOutline
      ? ['6. Write "when" on the outcome column (for example result), not one assertion per row.']
      : []),
    '7. Every value written in the Given/When steps is used in "act" (e.g. "the setting 2" -> the call gets 2).',
    '8. "actual" may only use field names that the steps use (e.g. "the value is ..." -> result.value), or length/size.',
    '   Use the documented interface for the shape of the result: if it returns a Function, call it in "act" or check typeof result.',
    '9. Write string values without the quote marks of the steps: "text/html", not "\\"text/html\\"".',
    '10. A string in "expected" must be written in the steps. Do not add values the steps do not state.',
    ...(sc.isOutline
      ? [
          '11. When a Then step has a <column>, every assertion for it uses "<column>" in its value or "when" on that column.',
        ]
      : []),
    '',
    'Example. Steps: S1: Given the price "12.5"  S2: When the price is formatted  T1: Then the text is "12.50 USD"',
    '{"act": "formatPrice(\\"12.5\\")", "assertions": [{"then": "T1", "category": "equality", "actual": "result", "expected": "12.50 USD"}]}',
    'Example (outline, columns qty, outcome). S1: When <qty> items are ordered  T1: Then the order is <outcome>',
    '{"act": "placeOrder({ qty: <qty> })", "assertions": [{"then": "T1", "when": {"column": "outcome", "equals": "refused"}, "category": "exception", "error": "OrderError", "message": null}, {"then": "T1", "when": {"column": "outcome", "equals": "accepted"}, "category": "equality", "actual": "result.qty", "expected": "<qty>"}]}',
  ].join('\n');
  return { system, user };
}

// ---------------------------------------------------------------- check

interface RawAnswer {
  act?: unknown;
  await?: unknown;
  assertions?: unknown;
}

export interface CheckedAnswer {
  problems: string[];
  act?: string;
  actCode?: string;
  quoted: string[];
  assertions: AssertionSlot[];
  cases: PlanCase[];
}

const isObj = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === 'object' && !Array.isArray(v);

/** Check one model answer against the scenario. Returns problems (empty = usable) and the cleaned slots. */
export function checkAssertionAnswer(raw: RawAnswer, ctx: PlanContext): CheckedAnswer {
  const problems: string[] = [];
  const { sc } = ctx;
  const exportNames = new Set(ctx.exports.map((e) => e.name));
  const errorClasses = new Set([
    ...ctx.exports.filter((e) => e.valueKind === 'class').map((e) => e.name),
    ...BUILTIN_ERRORS,
  ]);
  const quoted = new Set<string>();

  // act
  let act: string | undefined;
  let actCode: string | undefined;
  if (typeof raw.act !== 'string' || !raw.act.trim()) {
    problems.push('"act" must be one JavaScript call as a string');
  } else {
    act = raw.act.trim().replace(/;+\s*$/, '');
    const ph = replacePlaceholders(act, ctx.params);
    if (ph.unknown.length)
      problems.push(
        `"act" uses <${ph.unknown.join('>, <')}> but ${sc.isOutline ? `the columns are ${[...ctx.params.keys()].join(', ')}` : 'this scenario has no Examples'}`,
      );
    for (const [col, u] of ph.used) if (u.quoted) quoted.add(col);
    actCode = ph.code;
    const allowed = new Set([...exportNames, ...ctx.params.values()]);
    const c = checkExpression(ph.code, allowed);
    problems.push(...c.problems.map((p) => `"act": ${p}`));
    if (c.ok && (!c.callee || !ctx.targets.includes(c.callee))) {
      problems.push(
        `"act" must call the function under test (${ctx.targets.join(' or ')}), not ${c.calleeText ?? 'something else'}`,
      );
    }
    // C3-14 pilot: a Given/When value the call never gets (compileTrust(<hop>) for "the trust setting 2")
    const unused = unusedStepValues(sc, act);
    if (unused.length)
      problems.push(
        `"act" does not use the step value(s) ${unused.map((u) => `${u.value} (${u.step})`).join(', ')}; every Given/When value goes into the call (rule 7)`,
      );
    // fix-6 (C3 batch shields-4): object fields in the call that nothing names are invented input
    // (makeBadge({ text: "build", status: "passed" }) for "the badge text \"build\" and \"passed\"").
    const invented = inventedActKeys(ph.code, sc, ctx);
    if (invented.length)
      problems.push(
        `"act" passes the field(s) ${invented.join(', ')} that no step, the scenario or the documented interface names; build the input only from what the steps say (rule 7)`,
      );
    // fix-6 (C3 batch eslint-23): "src\app.js" in a JavaScript string is "srcapp.js"; the backslash must be doubled.
    const slashes = unescapedBackslashValues(sc, act);
    if (slashes.length)
      problems.push(
        `"act": write ${slashes.map((v) => `"${v}" as ${JSON.stringify(v)}`).join(', ')} in JavaScript (a backslash in a string must be doubled)`,
      );
  }

  // assertions
  const rawTexts: string[] = []; // the model's JSON of each kept assertion, same order
  const tIds = thenIds(sc);
  const assertions: AssertionSlot[] = [];
  if (!Array.isArray(raw.assertions) || raw.assertions.length === 0) {
    problems.push('"assertions" must be a non-empty list');
  } else if (raw.assertions.length > 12) {
    problems.push('"assertions" has more than 12 entries');
  } else {
    const mockTargets = new Set(ctx.mocks.map((m) => m.target));
    raw.assertions.forEach((a, i) => {
      const where = `assertion ${i + 1}`;
      if (!isObj(a)) {
        problems.push(`${where} is not an object`);
        return;
      }
      const then = typeof a.then === 'string' ? a.then.trim().toUpperCase() : '';
      if (!tIds.includes(then)) problems.push(`${where}: "then" must be one of ${tIds.join(', ')}`);
      const cat = a.category as AssertionCategory;
      if (!ASSERTION_CATEGORIES.includes(cat)) {
        problems.push(`${where}: "category" must be one of ${ASSERTION_CATEGORIES.join(', ')}`);
        return;
      }
      const slot: AssertionSlot = { then, category: cat };
      const unknownPh: string[] = [];

      if (a.when != null) {
        if (!sc.isOutline) problems.push(`${where}: "when" is only for Scenario Outlines`);
        else if (!isObj(a.when) || typeof a.when.column !== 'string')
          problems.push(`${where}: "when" must be {"column": ..., "equals": ...}`);
        else {
          const col = a.when.column.replace(/^<|>$/g, '');
          const eq = String(a.when.equals ?? '');
          const vals = ctx.columnValues.get(col);
          if (!vals) problems.push(`${where}: "when" column "${col}" is not an Examples column`);
          else if (!vals.includes(eq))
            problems.push(
              `${where}: "when" value "${eq}" is not in column ${col} (${[...new Set(vals)].join(', ')})`,
            );
          else slot.when = { column: col, equals: eq };
        }
      }

      const checkActual = () => {
        const actual = typeof a.actual === 'string' && a.actual.trim() ? a.actual.trim() : 'result';
        // C3-14 control run: "actual": "<result>" gave a confusing parser error; say what is wrong
        if (/<[^<>]+>/.test(actual)) {
          problems.push(
            `${where}: "actual" is what the call returns (result or a part of it); <column> values belong in "expected", not in "actual"`,
          );
          slot.actual = 'result';
          return;
        }
        const c = checkExpression(actual, new Set(['result', ...ctx.params.values()]));
        problems.push(...c.problems.map((p) => `${where} "actual": ${p}`));
        if (c.ok && !c.identifiers.includes('result'))
          problems.push(`${where}: "actual" must use result (what the call returns)`);
        // Rule 4 (tautology): result.<field> that only a mock adds says nothing about the code under test.
        const field = /^result\??\.([A-Za-z_$][\w$]*)/.exec(actual)?.[1];
        const fromMock = field && ctx.mocks.find((m) => m.mockFields?.includes(field));
        if (
          fromMock &&
          !new RegExp(`\\b${field}\\b`).test(typeof raw.act === 'string' ? raw.act : '')
        ) {
          problems.push(
            `${where}: ${actual} only comes from the mock ${fromMock.target} (${fromMock.decision_id}), not from the function under test (rule 4)`,
          );
        }
        // C3-14 pilot: result.type / result.q when the steps say "the value" and "the quality" (rule 8)
        const invented = inventedResultFields(actual, sc, ctx);
        if (invented.length)
          problems.push(
            `${where}: "actual" uses field(s) ${invented.join(', ')} that no step names; use the words of the steps (e.g. result.value) or check result itself (rule 8)`,
          );
        slot.actual = actual;
      };
      if (cat === 'equality') {
        checkActual();
        if (!('expected' in a)) problems.push(`${where}: equality needs "expected"`);
        slot.expected = unquoteValue(a.expected, sc);
        // C3-14 run 2: values the steps never state ("application/json" for "2 types are returned")
        const ungrounded = ungroundedStrings(slot.expected, slot.actual ?? 'result', sc);
        if (ungrounded.length)
          problems.push(
            `${where}: "expected" has ${ungrounded.map((u) => `"${u}"`).join(', ')}, which no step states; use only values from the steps (rules 1, 10)`,
          );
        // fix-6 (C3 batch hexo-7): the Given input copied as the expected output ("Then ... is returned as text"
        // -> toBe("<h1 id='intro'>Intro</h1>")). An expected text or number must be stated by a Then step.
        const copied = copiedFromInput(slot.expected, sc, ctx);
        if (copied !== undefined)
          problems.push(
            `${where}: "expected" ${JSON.stringify(copied)} is the input of a Given/When step; no Then step states it as the result (rule 1)`,
          );
        // C3-14 control run: "accepted" is an outcome label of the Examples table, not a return value
        const label = outcomeLabel(slot.expected, slot.actual ?? 'result', sc, ctx);
        if (label)
          problems.push(
            `${where}: "${label.value}" is an outcome label from the Examples column ${label.column}, not what ${ctx.targets.join(' or ')} returns; for this row check what happens instead: an exception when it is refused, or that ${ctx.mocks.map((m) => m.target).join(' or ')} was called (state_change) when it succeeds (rules 2, 5)`,
          );
        // C3-14 run 2: keys of an expected object are field names too (rule 8)
        if (isObj(slot.expected)) {
          // fix-6: keys of a JSON object a Then step writes out ({"foo": true}) are named by that step
          const stated = new Set(
            jsonLiterals(thenText(sc)).flatMap((x) => objectKeys(x).map((k) => k.toLowerCase())),
          );
          const badKeys = inventedResultFields(
            Object.keys(slot.expected)
              .map((k) => `result.${k}`)
              .join(' '),
            sc,
            ctx,
          ).filter((k) => !stated.has(k.toLowerCase()));
          if (badKeys.length)
            problems.push(
              `${where}: "expected" uses field(s) ${badKeys.join(', ')} that no step names (rule 8)`,
            );
        }
        // C3-14 run 2: the documented result is an Object/Array/Function, compared whole with a plain value
        // (not when the act calls the returned function, or the value is a <column>)
        const ret = /\)\s*\(/.test(act ?? '') ? undefined : documentedReturn(ctx);
        if (
          ret &&
          !(typeof slot.expected === 'string' && /^<[^<>]+>$/.test(slot.expected)) &&
          (slot.actual ?? 'result') === 'result' &&
          ['string', 'number', 'boolean'].includes(typeof slot.expected)
        )
          problems.push(
            `${where}: the documented result is ${ret}, so all of result cannot equal ${JSON.stringify(slot.expected)}; check a field the Then step names, result.length, or typeof result (rule 8)`,
          );
        renderValue(a.expected, ctx.params, unknownPh);
      } else if (cat === 'range') {
        checkActual();
        const num = (v: unknown) =>
          v == null ||
          (typeof v === 'number' && Number.isFinite(v)) ||
          (typeof v === 'string' && /^<[^<>]+>$/.test(v));
        if (a.min == null && a.max == null) problems.push(`${where}: range needs "min" or "max"`);
        if (!num(a.min) || !num(a.max))
          problems.push(`${where}: "min"/"max" must be numbers (or "<column>")`);
        if (a.min != null) slot.min = a.min;
        if (a.max != null) slot.max = a.max;
        slot.min_inclusive = a.min_inclusive !== false;
        slot.max_inclusive = a.max_inclusive !== false;
        renderValue([a.min, a.max], ctx.params, unknownPh);
      } else if (cat === 'exception') {
        const err = typeof a.error === 'string' && a.error.trim() ? a.error.trim() : null;
        if (err && !errorClasses.has(err))
          problems.push(
            `${where}: "error" ${err} is not an exported class or a built-in error (${[...errorClasses].join(', ')})`,
          );
        slot.error = err;
        slot.message = typeof a.message === 'string' && a.message.trim() ? a.message.trim() : null;
      } else {
        if (!ctx.mocks.length) {
          problems.push(
            `${where}: state_change needs a mocked dependency, and this scenario has none; use equality on result`,
          );
        } else if (typeof a.target !== 'string' || !mockTargets.has(a.target.trim())) {
          problems.push(`${where}: "target" must be one of ${[...mockTargets].join(', ')}`);
        }
        slot.target = typeof a.target === 'string' ? a.target.trim() : '';
        const change = a.change as StateChange;
        if (!STATE_CHANGES.includes(change))
          problems.push(`${where}: "change" must be one of ${STATE_CHANGES.join(', ')}`);
        slot.change = change;
        if (change === 'called_with') {
          if (!Array.isArray(a.args)) problems.push(`${where}: called_with needs "args" (a list)`);
          else {
            slot.args = unquoteValue(a.args, sc) as unknown[];
            renderValue(a.args, ctx.params, unknownPh);
            problems.push(...inventedArgFields(a.args, raw.act, ctx).map((p) => `${where}: ${p}`));
          }
        }
        if (change === 'called_times') {
          if (!Number.isInteger(a.times) || (a.times as number) < 0)
            problems.push(`${where}: called_times needs "times" (a whole number)`);
          else slot.times = a.times as number;
        }
      }
      if (unknownPh.length)
        problems.push(`${where}: unknown placeholder(s) <${[...new Set(unknownPh)].join('>, <')}>`);
      assertions.push(slot);
      rawTexts.push(JSON.stringify(a));
    });
  }

  // every Then step covered, every case has assertions, no 'result' check in a throwing case
  for (const t of tIds)
    if (assertions.length && !assertions.some((a) => a.then === t))
      problems.push(`Then step ${t} has no assertion`);
  // C3-14 run 2: a Then step with <column> must depend on it (compileETag(<setting>) with kind "none")
  if (sc.isOutline) {
    const thenCols = thenColumns(sc, ctx);
    assertions.forEach((a, i) => {
      for (const col of thenCols.get(a.then) ?? []) {
        if (a.when?.column !== col && !rawTexts[i]!.includes(`<${col}>`))
          problems.push(
            `assertion ${i + 1}: Then step ${a.then} depends on <${col}>, so use "<${col}>" in the value or "when" on column ${col} (rule 11)`,
          );
      }
    });
  }
  // fix-6 rule 12 (C3 batch eslint-273): a Then step that writes the expected value as a JSON list or object is
  // checked against that whole value, not only its length or type (result.length 2 for "[2]" failed on correct code).
  if (assertions.length) {
    let t = 0;
    for (const st of sc.steps) {
      if (st.keyword !== 'Then') continue;
      const id = `T${++t}`;
      const lits = jsonLiterals(st.text).map(canonical);
      if (!lits.length) continue;
      const ok = assertions.some(
        (a) =>
          a.then === id &&
          a.category === 'equality' &&
          a.expected !== undefined &&
          lits.includes(canonical(a.expected)),
      );
      if (!ok)
        problems.push(
          `Then step ${id} states the value ${jsonLiterals(st.text)
            .map((x) => JSON.stringify(x))
            .join(
              ' or ',
            )}; check it with one equality assertion whose "expected" is exactly that value (rule 12)`,
        );
    }
  }
  const cases = buildCases(sc, assertions);
  for (const c of cases) {
    const label = c.row ? `row ${c.row}` : 'the scenario';
    if (assertions.length && !c.assertions.length) problems.push(`${label} has no assertion`);
    const cats = c.assertions.map((i) => assertions[i]!.category);
    if (cats.includes('exception') && (cats.includes('equality') || cats.includes('range')))
      problems.push(`${label} both throws and checks result (rule 2)`);
  }
  return { problems, act, actCode, quoted: [...quoted].sort(), assertions, cases };
}

const stepText = (sc: C3ScenarioInput) => sc.steps.map((st) => st.text).join(' ');

/**
 * C3-14 pilot: values written in the Given/When steps ("quoted text", numbers, true/false) that the act
 * does not contain. <column> placeholders are not values. Then-step values are checked by the assertions.
 */
export function unusedStepValues(
  sc: C3ScenarioInput,
  act: string,
): { value: string; step: string }[] {
  const out: { value: string; step: string }[] = [];
  let s = 0;
  for (const st of sc.steps) {
    if (st.keyword === 'Then') continue;
    const step = `S${++s}`;
    const quotedVals = [...st.text.matchAll(/"([^"]*)"/g)]
      .map((m) => m[1]!)
      .filter((v) => !/^<[^<>]+>$/.test(v));
    // <column> placeholders of Given/When steps must reach the call too (compileTrust(2) without <hop>)
    for (const m of st.text.matchAll(/<([^<>]+)>/g))
      if (!act.includes(`<${m[1]}>`)) out.push({ value: `<${m[1]}>`, step });
    const rest = st.text.replace(/"[^"]*"/g, ' ').replace(/<[^<>]+>/g, ' ');
    const bare = [...rest.matchAll(/(?<![\w.])(-?\d+(?:\.\d+)?|true|false|null)(?![\w.])/g)].map(
      (m) => m[1]!,
    );
    // a list value may be passed split up: "127.0.0.1, 10.0.0.1" -> ["127.0.0.1", "10.0.0.1"]
    const usedText = (v: string) =>
      act.includes(v) ||
      // fix-6: "src\app.js" is written "src\\app.js" in a JavaScript string (eslint-23)
      (v.includes('\\') && act.includes(JSON.stringify(v).slice(1, -1))) ||
      (v.includes(',') &&
        v
          .split(',')
          .map((x) => x.trim())
          .filter(Boolean)
          .every((x) => act.includes(x)));
    for (const v of quotedVals) if (v && !usedText(v)) out.push({ value: `"${v}"`, step });
    for (const v of bare)
      if (!new RegExp(`(?<![\\w.])${v.replace('.', '\\.')}(?![\\w.])`).test(act))
        out.push({ value: v, step });
  }
  return out;
}

/** typeof answers are words of JavaScript, not values the steps must state. */
const TYPEOF_WORDS = new Set(['function', 'object', 'string', 'number', 'boolean', 'undefined']);

/**
 * C3-14 run 2: strings in "expected" that no step states (rule 1). <column> values and typeof answers are
 * fine. Compared without case and quote marks.
 */
export function ungroundedStrings(
  expected: unknown,
  actual: string,
  sc: C3ScenarioInput,
): string[] {
  // the Examples table is part of the scenario: its cells are stated values too
  const cells = sc.examples.flatMap((r) => Object.values(r.values));
  const text = `${stepText(sc)} ${cells.join(' ')}`.toLowerCase();
  const out: string[] = [];
  const walk = (v: unknown) => {
    if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') Object.values(v).forEach(walk);
    else if (typeof v === 'string') {
      if (/<[^<>]+>/.test(v)) return;
      if (/^typeof\b/.test(actual.trim()) && TYPEOF_WORDS.has(v)) return;
      if (v.trim() && !text.includes(v.toLowerCase())) out.push(v);
    }
  };
  walk(expected);
  return out;
}

/**
 * C3-14 control run: result compared with a value of a Then-step column ("accepted", "<result>") when a mocked
 * dependency exists. Such a column says what happens (refused / saved), so rule 5 applies: success is shown by
 * the call to the mock, not by result equal to the label. Without a mock the label may be a real return value
 * (a grade "A"), so nothing is said then.
 */
export function outcomeLabel(
  expected: unknown,
  actual: string,
  sc: C3ScenarioInput,
  ctx: PlanContext,
): { value: string; column: string } | undefined {
  if (!sc.isOutline || !ctx.mocks.length || actual.trim() !== 'result') return undefined;
  if (typeof expected !== 'string') return undefined;
  for (const cols of thenColumns(sc, ctx).values()) {
    for (const col of cols) {
      if (expected === `<${col}>`) return { value: expected, column: col };
      const vals = (ctx.columnValues.get(col) ?? []).map((v) => v.toLowerCase());
      if (vals.includes(expected.toLowerCase())) return { value: expected, column: col };
    }
  }
  return undefined;
}

/** The type in "@return {Object}" of the function under test, when it is not a plain value. */
export function documentedReturn(ctx: PlanContext): string | undefined {
  for (const t of ctx.targets) {
    const doc = ctx.exports.find((e) => e.name === t)?.doc;
    const m = doc && /@returns?\s*\{([^}]+)\}/.exec(doc);
    if (!m) continue;
    const kinds = m[1]!.split('|').map((k) => k.trim().toLowerCase());
    if (kinds.every((k) => ['object', 'array', 'function'].includes(k) || k.endsWith('[]')))
      return m[1]!.trim();
  }
  return undefined;
}

/** Examples columns named in each Then step ("Then the function is \"<kind>\"" -> T1: kind). */
export function thenColumns(sc: C3ScenarioInput, ctx: PlanContext): Map<string, string[]> {
  const out = new Map<string, string[]>();
  let t = 0;
  for (const st of sc.steps) {
    if (st.keyword !== 'Then') continue;
    const cols = [...st.text.matchAll(/<([^<>]+)>/g)]
      .map((m) => m[1]!)
      .filter((c) => ctx.params.has(c));
    out.set(`T${++t}`, [...new Set(cols)]);
  }
  return out;
}

/** Built-in properties a step need not name (2 normalized types are returned -> result.length). */
const BUILTIN_FIELDS = new Set(['length', 'size']);

/**
 * C3-14 pilot: field names in "actual" (result.a.b) that the Then steps do not name. Words inside quotes
 * are values, not names, so they do not count ("the type \"text/html; q=0.5\"" names no field q).
 * A field may be a short form of a Then word ("params" for "parameters"); Examples columns count.
 */
export function inventedResultFields(
  actual: string,
  sc: C3ScenarioInput,
  ctx: PlanContext,
): string[] {
  const thenText = sc.steps
    .filter((st) => st.keyword === 'Then')
    .map((st) => st.text.replace(/"[^"]*"/g, ' '))
    .join(' ');
  const words = `${thenText} ${[...ctx.params.keys()].join(' ')}`
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
  // same word, or a short form: one starts with the other (4+ letters), or 5+ shared first letters
  // ("params" ~ "parameters", "value" ~ "values"); one or two letters ("q") never count.
  const shared = (a: string, b: string) => {
    let i = 0;
    while (i < a.length && i < b.length && a[i] === b[i]) i++;
    return i;
  };
  const named = (f: string) =>
    words.some(
      (w) =>
        w === f ||
        (Math.min(f.length, w.length) >= 4 && (w.startsWith(f) || f.startsWith(w))) ||
        shared(f, w) >= 5,
    );
  // method calls such as .trim() are not fields
  const fields = [...actual.matchAll(/\??\.([A-Za-z_$][\w$]*)(?![\w$])(?!\s*\()/g)].map(
    (m) => m[1]!,
  );
  return fields.filter((f) => !BUILTIN_FIELDS.has(f) && !named(f.toLowerCase()));
}

/**
 * C3-14 pilot: Qwen copied the step's quote marks into the value ("\"text/html\""). A string that is the
 * text of a step value wrapped in quotes is unwrapped. Deterministic, recorded in the plan as the clean value.
 */
export function unquoteValue(v: unknown, sc: C3ScenarioInput): unknown {
  if (Array.isArray(v)) return v.map((x) => unquoteValue(x, sc));
  if (v && typeof v === 'object')
    return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, unquoteValue(x, sc)]));
  if (typeof v === 'string') {
    const m = /^(["'])(.+)\1$/.exec(v);
    if (m && stepText(sc).includes(m[2]!)) return m[2]!;
    // fix-6 (C3 batch eslint-267): a list or object written as JSON text ("[\"warn\", \"allow-null\"]") that a
    // step states is that list or object, not a string; toBe(text) failed on correct code.
    const t = v.trim();
    if (/^[[{]/.test(t)) {
      try {
        const parsed: unknown = JSON.parse(t);
        const key = canonical(parsed);
        if (jsonLiterals(stepText(sc)).some((x) => canonical(x) === key)) return parsed;
      } catch {
        /* not JSON: keep the string */
      }
    }
  }
  return v;
}

/** JSON with object keys sorted, so two equal values give the same text. */
export function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(',')}]`;
  if (v && typeof v === 'object')
    return `{${Object.keys(v as object)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonical((v as Record<string, unknown>)[k])}`)
      .join(',')}}`;
  return JSON.stringify(v);
}

/** Every JSON list or object written in a text ("the configurations are [2, [2, \"always\"]]" -> [2, [2, "always"]]). */
export function jsonLiterals(text: string): unknown[] {
  const out: unknown[] = [];
  for (let i = 0; i < text.length; i++) {
    const open = text[i];
    if (open !== '[' && open !== '{') continue;
    let depth = 0;
    let inStr = false;
    for (let j = i; j < text.length; j++) {
      const ch = text[j]!;
      if (inStr) {
        if (ch === '\\') j++;
        else if (ch === '"') inStr = false;
      } else if (ch === '"') inStr = true;
      else if (ch === '[' || ch === '{') depth++;
      else if (ch === ']' || ch === '}') {
        depth--;
        if (depth === 0) {
          try {
            out.push(JSON.parse(text.slice(i, j + 1)));
            i = j;
          } catch {
            /* not JSON */
          }
          break;
        }
      }
    }
  }
  return out;
}

/** Every object key inside a JSON value (args of called_with, expected of equality). */
export function objectKeys(v: unknown): string[] {
  const out: string[] = [];
  const walk = (x: unknown) => {
    if (Array.isArray(x)) x.forEach(walk);
    else if (x && typeof x === 'object')
      for (const [k, y] of Object.entries(x)) {
        out.push(k);
        walk(y);
      }
  };
  walk(v);
  return [...new Set(out)];
}

const word = (k: string) =>
  new RegExp(`(^|[^A-Za-z0-9_$])${k.replace(/[$]/g, '\\$')}([^A-Za-z0-9_$]|$)`, 'i');

/**
 * Rule 4 for called_with: a field the act does not pass in is invented when it only comes from a mock's
 * return value, or when no step names it. (The function under test decides what it passes on; the test may
 * only expect fields that come from its input or from the requirement.)
 */
export function inventedArgFields(args: unknown[], act: unknown, ctx: PlanContext): string[] {
  const actText = typeof act === 'string' ? act : '';
  const steps = ctx.sc.steps.map((s) => s.text).join(' \n ');
  const out: string[] = [];
  for (const k of objectKeys(args)) {
    if (word(k).test(actText)) continue;
    const mock = ctx.mocks.find((m) => m.mockFields?.includes(k));
    if (mock)
      out.push(
        `args field "${k}" only comes from the mock ${mock.target} (${mock.decision_id}), not from the act (rule 4)`,
      );
    else if (!word(k).test(steps))
      out.push(
        `args field "${k}" is not passed in by the act and no step names it; do not invent fields (rule 4)`,
      );
  }
  return out;
}

/** Which assertions hold for each test (one per outline row, else one). */
export function buildCases(sc: C3ScenarioInput, assertions: AssertionSlot[]): PlanCase[] {
  const rows = sc.isOutline ? sc.examples : [undefined];
  return rows.map((r) => {
    const idx = assertions
      .map((a, i) => ({ a, i }))
      .filter(({ a }) => !a.when || (r && r.values[a.when.column] === a.when.equals))
      .map(({ i }) => i);
    const cats = [...new Set(idx.map((i) => assertions[i]!.category))];
    return { ...(r ? { row: r.rowIndex } : {}), assertions: idx, categories: cats };
  });
}

/** Rule-based category per (case, Then step); outline rows fill in their values first. */
export function ruleCategories(sc: C3ScenarioInput): ScenarioPlan['rule_categories'] {
  const thens = sc.steps.filter((s) => s.keyword === 'Then');
  const rows = sc.isOutline ? sc.examples : [undefined];
  const out: ScenarioPlan['rule_categories'] = [];
  for (const r of rows) {
    thens.forEach((t, i) => {
      const text = r ? t.text.replace(/<([^<>]+)>/g, (m, c: string) => r.values[c] ?? m) : t.text;
      out.push({
        then: `T${i + 1}`,
        ...(r ? { row: r.rowIndex } : {}),
        category: ruleCategory(text),
      });
    });
  }
  return out;
}

function agreement(
  rules: ScenarioPlan['rule_categories'],
  cases: PlanCase[],
  assertions: AssertionSlot[],
): number {
  if (!rules.length) return 0;
  let agree = 0;
  for (const r of rules) {
    const c = cases.find((x) => x.row === r.row);
    const cats = (c?.assertions ?? [])
      .map((i) => assertions[i]!)
      .filter((a) => a.then === r.then)
      .map((a) => a.category);
    if (cats.includes(r.category)) agree++;
  }
  return Math.round((agree / rules.length) * 1000) / 1000;
}

// ---------------------------------------------------------------- derive

export interface PlanOptions {
  retries?: number; // default 1
  log?: (line: string) => void;
  /** C3-12 repair: messages added after the prompt (the previous answer and the Jest error). */
  followUp?: ChatMessage[];
  /** Label for the model call, e.g. 'C3-12 repair 2'. */
  purpose?: string;
}

/** C3-08 for one scenario. Never throws for a bad model answer: the plan is marked `failed`. */
export async function planScenario(
  ctx: PlanContext,
  client: ModelClient,
  options: PlanOptions = {},
): Promise<ScenarioPlan> {
  const { sc } = ctx;
  const retries = options.retries ?? 1;
  const { system, user } = assertionPrompt(ctx);
  const messages: ChatMessage[] = [
    { role: 'system', content: system },
    { role: 'user', content: user },
    ...(options.followUp ?? []),
  ];
  const rules = ruleCategories(sc);
  const problems: string[] = [];
  let attempts = 0;
  for (let attempt = 0; attempt <= retries; attempt++) {
    attempts++;
    const res = await client.complete({
      messages: [...messages],
      temperature: 0,
      maxTokens: 900,
      purpose: `${options.purpose ?? 'C3-08 assertions'} ${sc.scenarioId}`,
    });
    let raw: RawAnswer | undefined;
    let found: string[];
    try {
      raw = parseJsonAnswer<RawAnswer>(res.text);
      found = isObj(raw) ? [] : ['not a JSON object'];
    } catch (err) {
      found = [err instanceof Error ? err.message : String(err)];
    }
    const checked = raw && !found.length ? checkAssertionAnswer(raw, ctx) : undefined;
    if (checked) found = checked.problems;
    if (checked && !found.length) {
      const fut = ctx.exports.find(
        (e) => ctx.targets.includes(e.name) && checkCall(checked.act!, e.name),
      );
      return {
        scenario_id: sc.scenarioId,
        requirement_id: sc.requirementId,
        source: 'model',
        model: `${res.model}@${res.provider}`,
        attempts,
        problems,
        function_under_test: ctx.targets,
        act: checked.act,
        act_code: checked.actCode,
        await: raw?.await === true || fut?.isAsync === true,
        params: Object.fromEntries(ctx.params),
        quoted_columns: checked.quoted,
        assertions: checked.assertions,
        cases: checked.cases,
        rule_categories: rules,
        category_agreement: agreement(rules, checked.cases, checked.assertions),
      };
    }
    problems.push(...found.map((p) => `attempt ${attempts}: ${p}`));
    messages.push(
      { role: 'assistant', content: res.text },
      {
        role: 'user',
        content: `Your answer has problems:\n- ${found.join('\n- ')}\nAnswer again with one corrected JSON object.`,
      },
    );
  }
  options.log?.(`  ${sc.scenarioId} assertion answer unusable after ${attempts} call(s)`);
  return failedPlan(ctx, attempts, problems, rules);
}

const checkCall = (act: string, name: string) => new RegExp(`(^|[^\\w$.])${name}\\s*\\(`).test(act);

function failedPlan(
  ctx: PlanContext,
  attempts: number,
  problems: string[],
  rules: ScenarioPlan['rule_categories'],
): ScenarioPlan {
  return {
    scenario_id: ctx.sc.scenarioId,
    requirement_id: ctx.sc.requirementId,
    source: 'failed',
    attempts,
    problems,
    function_under_test: ctx.targets,
    params: Object.fromEntries(ctx.params),
    quoted_columns: [],
    assertions: [],
    cases: [],
    rule_categories: rules,
    category_agreement: 0,
  };
}

/** C3-08 for every scenario of a run. Without a model every plan is `failed` (no test can be written). */
export async function planAssertions(
  contexts: PlanContext[],
  client: ModelClient | undefined,
  options: PlanOptions = {},
): Promise<AssertionWorkFile> {
  const plans: ScenarioPlan[] = [];
  for (const ctx of contexts) {
    if (!client) {
      plans.push(failedPlan(ctx, 0, ['no model configured'], ruleCategories(ctx.sc)));
      continue;
    }
    const p = await planScenario(ctx, client, options);
    options.log?.(
      p.source === 'model'
        ? `  ${p.scenario_id} act ${p.act}; ${p.cases.length} case(s); categories ${[...new Set(p.assertions.map((a) => a.category))].join(', ')}; rule agreement ${p.category_agreement}`
        : `  ${p.scenario_id} FAILED (${p.problems.length} problem(s))`,
    );
    plans.push(p);
  }
  return {
    prompt_version: ASSERTION_PROMPT_VERSION,
    model: client?.modelTag ?? null,
    plans,
  };
}

export type { C3Inputs };

/**
 * fix-6: object keys in the act (makeBadge({ text: ..., status: ... })) that no step text, the scenario name,
 * an Examples column, or the documented interface (JSDoc, parameter list) of the function under test names.
 */
export function inventedActKeys(code: string, sc: C3ScenarioInput, ctx: PlanContext): string[] {
  const sf = ts.createSourceFile(
    'act.js',
    `(${code}\n);`,
    ts.ScriptTarget.ES2022,
    true,
    ts.ScriptKind.JS,
  );
  const keys = new Set<string>();
  const visit = (n: ts.Node) => {
    if (ts.isObjectLiteralExpression(n))
      for (const p of n.properties) {
        const name =
          p.name && (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name))
            ? p.name.text
            : undefined;
        if (name) keys.add(name);
      }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  if (!keys.size) return [];
  const byName = new Map(ctx.exports.map((e) => [e.name, e]));
  const docs = ctx.targets.map(
    (t) => `${byName.get(t)?.doc ?? ''} ${(byName.get(t)?.params ?? []).join(' ')}`,
  );
  const text = [stepText(sc), sc.scenarioName, sc.featureName, ...ctx.params.keys(), ...docs].join(
    ' \n ',
  );
  return [...keys].filter((k) => !word(k).test(text));
}

/** fix-6: quoted Given/When values with a backslash that the act writes without doubling it. */
export function unescapedBackslashValues(sc: C3ScenarioInput, act: string): string[] {
  const out: string[] = [];
  for (const st of sc.steps) {
    if (st.keyword === 'Then') continue;
    for (const m of st.text.matchAll(/"([^"]*\\[^"]*)"/g)) {
      const v = m[1]!;
      if (!act.includes(JSON.stringify(v).slice(1, -1))) out.push(v);
    }
  }
  return [...new Set(out)];
}

const thenText = (sc: C3ScenarioInput) =>
  sc.steps
    .filter((st) => st.keyword === 'Then')
    .map((st) => st.text)
    .join(' \n ');

/**
 * fix-6: an expected text or number that a Given/When step states but no Then step does (and that is not a
 * <column>, a typeof word, or a value of a Then column). Returns that value, else undefined.
 */
export function copiedFromInput(
  v: unknown,
  sc: C3ScenarioInput,
  ctx: PlanContext,
): string | number | undefined {
  if (typeof v !== 'string' && typeof v !== 'number') return undefined;
  if (typeof v === 'string' && (/^<[^<>]+>$/.test(v) || TYPEOF_WORDS.has(v) || !v.trim()))
    return undefined;
  const text = String(v);
  const has = (t: string) =>
    typeof v === 'number'
      ? new RegExp(`(?<![\\w.])${text.replace('.', '\\.')}(?![\\w.])`).test(t)
      : t.toLowerCase().includes(text.toLowerCase());
  const then = thenText(sc);
  if (has(then)) return undefined;
  // a value of an Examples column the Then step uses (<kind> -> "weak")
  const thenCols = [...then.matchAll(/<([^<>]+)>/g)].map((m) => m[1]!);
  if (
    thenCols.some((c) =>
      (ctx.columnValues.get(c) ?? []).some((x) => x.toLowerCase() === text.toLowerCase()),
    )
  )
    return undefined;
  const given = sc.steps
    .filter((st) => st.keyword !== 'Then')
    .map((st) => st.text)
    .join(' \n ');
  return has(given) ? v : undefined;
}
