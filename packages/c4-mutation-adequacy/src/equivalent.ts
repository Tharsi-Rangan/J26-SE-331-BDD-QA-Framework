import type { MutationReport, Position, StrykerMutant } from './types.js';

export type EquivalentRule = 'E1-same-code' | 'E2-log-only';

export interface EquivalentMutant {
  mutant_id: string;
  file: string;
  rule: EquivalentRule;
  reason: string;
}

interface Token {
  text: string;
  start: number;
  end: number;
}

const TOKEN =
  /\s+|\/\/[^\n]*|\/\*[\s\S]*?\*\/|'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|`(?:\\.|[^`\\])*`|[A-Za-z_$][\w$]*|\d[\w.]*|>>>=|\*\*=|&&=|\|\|=|\?\?=|<<=|>>=|>>>|===|!==|\.\.\.|=>|==|!=|<=|>=|&&|\|\||\?\?|\?\.|\+\+|--|\*\*|<<|>>|[+\-*/%&|^]=|[^\s]/g;

/** Split JavaScript into tokens, without whitespace and comments. Regex literals are not handled. */
export function tokenize(src: string): Token[] {
  const out: Token[] = [];
  for (const m of src.matchAll(TOKEN)) {
    const text = m[0];
    if (/^\s/.test(text) || text.startsWith('//') || text.startsWith('/*')) continue;
    out.push({ text, start: m.index, end: m.index + text.length });
  }
  return out;
}

/** Token text where 'a' and "a" are the same string. */
const canonical = (t: string) =>
  t.startsWith("'") || t.startsWith('"') ? 'S:' + t.slice(1, -1).replace(/\\(['"])/g, '$1') : t;

const sameCode = (a: string, b: string) => {
  const ta = tokenize(a).map((t) => canonical(t.text));
  const tb = tokenize(b).map((t) => canonical(t.text));
  return ta.length === tb.length && ta.every((t, i) => t === tb[i]);
};

/** Offset of a StrykerJS position in `src`. Lines and columns start at 1. */
export function offsetOf(src: string, p: Position): number {
  let offset = 0;
  for (let line = 1; line < p.line; line++) offset = src.indexOf('\n', offset) + 1;
  return offset + p.column - 1;
}

export function applyMutant(src: string, m: StrykerMutant): string {
  return (
    src.slice(0, offsetOf(src, m.location.start)) +
    (m.replacement ?? '') +
    src.slice(offsetOf(src, m.location.end))
  );
}

const LOG_METHODS = new Set(['log', 'info', 'warn', 'error', 'debug', 'trace']);
// Tokens that can change program state when a log call evaluates its arguments.
const SIDE_EFFECTS = new Set([
  '=',
  '++',
  '--',
  '+=',
  '-=',
  '*=',
  '/=',
  '%=',
  '**=',
  '<<=',
  '>>=',
  '>>>=',
  '&=',
  '|=',
  '^=',
  '&&=',
  '||=',
  '??=',
  '(',
  'new',
  'await',
  'yield',
  'delete',
]);

/**
 * Source ranges of `console.<method>(...)` and `debug(...)` calls whose arguments have no side effects.
 * A range starts at the first argument token and ends at the closing parenthesis.
 */
export function logArgumentRanges(src: string): [number, number][] {
  const toks = tokenize(src);
  const ranges: [number, number][] = [];
  for (let i = 0; i < toks.length; i++) {
    const t = (k: number) => toks[k]?.text;
    let open = -1;
    if (
      t(i) === 'console' &&
      t(i + 1) === '.' &&
      LOG_METHODS.has(t(i + 2) ?? '') &&
      t(i + 3) === '('
    )
      open = i + 3;
    else if (t(i) === 'debug' && t(i + 1) === '(' && t(i - 1) !== '.' && t(i - 1) !== 'function')
      open = i + 1;
    if (open < 0) continue;
    let depth = 0;
    let close = -1;
    for (let k = open; k < toks.length; k++) {
      if (['(', '[', '{'].includes(t(k)!)) depth++;
      else if ([')', ']', '}'].includes(t(k)!) && --depth === 0) {
        close = k;
        break;
      }
    }
    if (close < 0) continue;
    const args = toks.slice(open + 1, close);
    if (args.some((a) => SIDE_EFFECTS.has(a.text))) continue;
    ranges.push([toks[open]!.end, toks[close]!.start]);
  }
  return ranges;
}

/**
 * Flag surviving mutants that are likely equivalent, with the rule that matched.
 * Killed mutants are never flagged: a test saw a change in behaviour.
 */
export function findEquivalentMutants(report: MutationReport): EquivalentMutant[] {
  const out: EquivalentMutant[] = [];
  for (const [file, f] of Object.entries(report.files)) {
    if (f.source === undefined) continue;
    const src = f.source;
    const logRanges = logArgumentRanges(src);
    for (const m of f.mutants) {
      if (m.status !== 'Survived' && m.status !== 'NoCoverage') continue;
      if (sameCode(src, applyMutant(src, m))) {
        out.push({
          mutant_id: m.id,
          file,
          rule: 'E1-same-code',
          reason: 'The mutated code has the same tokens as the original code.',
        });
        continue;
      }
      const start = offsetOf(src, m.location.start);
      const end = offsetOf(src, m.location.end);
      if (logRanges.some(([a, b]) => start >= a && end <= b)) {
        out.push({
          mutant_id: m.id,
          file,
          rule: 'E2-log-only',
          reason:
            'The change is only in the arguments of a log call, so the program result does not change.',
        });
      }
    }
  }
  return out;
}
