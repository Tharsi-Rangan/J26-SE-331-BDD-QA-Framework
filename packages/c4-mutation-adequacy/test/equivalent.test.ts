import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, test } from 'vitest';
import {
  applyMutant,
  findEquivalentMutants,
  logArgumentRanges,
  offsetOf,
  tokenize,
} from '../src/equivalent.js';
import { aggregateScores } from '../src/scores.js';
import { buildSurvivors } from '../src/trace.js';
import type { MutationReport, StrykerMutant } from '../src/types.js';

const golden = path.resolve(
  import.meta.dirname,
  '../../contracts/fixtures/golden/example-registration',
);
const goldenRaw = JSON.parse(
  fs.readFileSync(path.join(golden, 'c4', 'raw', 'mutation.json'), 'utf8'),
) as MutationReport;

/** Mutant that replaces the first `find` in `src` (on one line) with `replacement`. */
function mutantAt(
  src: string,
  find: string,
  replacement: string,
  status: StrykerMutant['status'] = 'Survived',
  id = '1',
): StrykerMutant {
  const at = src.indexOf(find);
  const pos = (offset: number) => {
    const before = src.slice(0, offset).split('\n');
    return { line: before.length, column: before.at(-1)!.length + 1 };
  };
  return {
    id,
    status,
    mutatorName: 'StringLiteral',
    replacement,
    location: { start: pos(at), end: pos(at + find.length) },
  };
}

const reportOf = (source: string, mutants: StrykerMutant[]): MutationReport => ({
  files: { 'src/a.js': { source, mutants } },
});

describe('c4 equivalent filter: helpers', () => {
  test('offsetOf and applyMutant on the golden survivor', () => {
    const f = goldenRaw.files['subject-src/src/registration.js']!;
    const m12 = f.mutants.find((m) => m.id === '12')!;
    expect(
      f.source!.slice(
        offsetOf(f.source!, m12.location.start),
        offsetOf(f.source!, m12.location.end),
      ),
    ).toBe("'age out of range'");
    expect(applyMutant(f.source!, m12)).toContain('throw new ValidationError("");');
  });

  test('tokenize drops comments and keeps // inside strings', () => {
    expect(tokenize("a = 'http://x'; // note\n/* b */ c++").map((t) => t.text)).toEqual([
      'a',
      '=',
      "'http://x'",
      ';',
      'c',
      '++',
    ]);
  });
});

describe('c4 equivalent filter: rules', () => {
  test('golden example: no mutant is flagged', () => {
    expect(findEquivalentMutants(goldenRaw)).toEqual([]);
  });

  test('E1: a change in quote style only (\'x\' -> "x") is the same code', () => {
    const src = "const a = 'x';\nmodule.exports = a;\n";
    expect(findEquivalentMutants(reportOf(src, [mutantAt(src, "'x'", '"x"')]))).toEqual([
      expect.objectContaining({ mutant_id: '1', rule: 'E1-same-code' }),
    ]);
  });

  test('E1: a different value is not the same code', () => {
    const src = "const a = 'x';\n";
    expect(findEquivalentMutants(reportOf(src, [mutantAt(src, "'x'", '""')]))).toEqual([]);
  });

  test('E2: a string in console.log or debug arguments is log-only', () => {
    const src =
      "function f(id) {\n  console.log('saved ' + id);\n  debug('id %s', id);\n  return id;\n}\n";
    const found = findEquivalentMutants(
      reportOf(src, [
        mutantAt(src, "'saved '", '""', 'Survived', '1'),
        mutantAt(src, "'id %s'", '""', 'NoCoverage', '2'),
      ]),
    );
    expect(found.map((e) => [e.mutant_id, e.rule])).toEqual([
      ['1', 'E2-log-only'],
      ['2', 'E2-log-only'],
    ]);
  });

  test('E2: no flag when the log arguments can change state', () => {
    const src = "console.log('n', count++);\nconsole.warn('x', save(user));\n";
    expect(logArgumentRanges(src)).toEqual([]);
    expect(
      findEquivalentMutants(
        reportOf(src, [mutantAt(src, "'n'", '""'), mutantAt(src, "'x'", '""', 'Survived', '2')]),
      ),
    ).toEqual([]);
  });

  test('E2: no flag for a mutant that removes the whole log call', () => {
    const src = "function f() {\n  console.log('a');\n}\n";
    const m = mutantAt(src, "{\n  console.log('a');\n}", '{}');
    expect(findEquivalentMutants(reportOf(src, [m]))).toEqual([]);
  });

  test('E2: a function named debug is not a log call', () => {
    expect(logArgumentRanges("function debug(a) { return a; }\nobj.debug('x');\n")).toEqual([]);
  });

  test('a killed mutant is never flagged', () => {
    const src = "console.log('a');\n";
    expect(findEquivalentMutants(reportOf(src, [mutantAt(src, "'a'", '""', 'Killed')]))).toEqual(
      [],
    );
  });

  test('a file without source is skipped', () => {
    const r: MutationReport = { files: { 'src/a.js': { mutants: [mutantAt('x', 'x', 'y')] } } };
    expect(findEquivalentMutants(r)).toEqual([]);
  });
});

describe('c4 equivalent filter: scores and survivors', () => {
  test('flagged survivors are marked and leave the filtered score', () => {
    const src = "function f(id) {\n  console.log('saved');\n  return id > 1;\n}\n";
    const r = reportOf(src, [
      mutantAt(src, "'saved'", '""', 'Survived', '1'),
      mutantAt(src, 'id > 1', 'id >= 1', 'Survived', '2'),
      mutantAt(src, 'id > 1', 'true', 'Killed', '3'),
    ]);
    const ids = new Set(findEquivalentMutants(r).map((e) => e.mutant_id));
    expect([...ids]).toEqual(['1']);
    const { summary } = aggregateScores(r, [], [], ids);
    expect(summary).toMatchObject({
      equivalent_filtered: 1,
      mutation_score: 0.3333,
      mutation_score_filtered: 0.5,
    });
    expect(buildSurvivors(r, new Map(), ids).map((s) => [s.mutant_id, s.equivalent])).toEqual([
      ['1', true],
      ['2', false],
    ]);
  });
});
