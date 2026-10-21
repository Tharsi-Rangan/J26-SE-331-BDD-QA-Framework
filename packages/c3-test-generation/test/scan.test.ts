import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';
import { classifySpecifier, nameFromFile, scanModule } from '../src/scan/scanner.js';
import type { ModuleScan } from '../src/scan/types.js';

const GOLDEN_SUBJECT = fileURLToPath(
  new URL('../../contracts/fixtures/golden/example-registration/subject-src', import.meta.url),
);
const SUBJECT = fileURLToPath(new URL('./fixtures/scan-subject', import.meta.url));

const dep = (scan: ModuleScan, key: string) => scan.dependencies.find((d) => d.key === key);
const reach = (scan: ModuleScan, name: string) =>
  scan.exports.find((e) => e.name === name)?.dependencies;

describe('C3-04 classifySpecifier', () => {
  test.each([
    ['fs', 'node_builtin'],
    ['node:fs', 'node_builtin'],
    ['fs/promises', 'node_builtin'],
    ['querystring', 'node_builtin'],
    ['qs', 'external_package'],
    ['@scope/pkg/sub', 'external_package'],
    ['./userRepository', 'internal_module'],
    ['../lib/x.js', 'internal_module'],
  ])('%s -> %s', (spec, kind) => {
    expect(classifySpecifier(spec)).toBe(kind);
  });
});

describe('C3-04 scanModule on the golden example', () => {
  const scan = scanModule(GOLDEN_SUBJECT, 'src/registration.js', {
    expectedExports: ['registerUser'],
  });

  test('finds userRepository.save as an internal module with a resolved path and type', () => {
    expect(scan.imports).toEqual([
      {
        importSpecifier: './userRepository',
        kind: 'internal_module',
        resolvedPath: 'src/userRepository.js',
        localNames: ['userRepository'],
        line: 2,
      },
    ]);
    expect(scan.dependencies).toHaveLength(1);
    expect(scan.dependencies[0]).toMatchObject({
      key: './userRepository#save',
      importSpecifier: './userRepository',
      symbol: 'save',
      kind: 'internal_module',
      resolvedPath: 'src/userRepository.js',
      lines: [10],
    });
    expect(scan.dependencies[0]!.typeSignature).toMatch(/\(user: any\) =>/);
  });

  test('registerUser reaches save; ValidationError reaches nothing', () => {
    expect(reach(scan, 'registerUser')).toEqual(['./userRepository#save']);
    expect(reach(scan, 'ValidationError')).toEqual([]);
    expect(scan.moduleLoadDependencies).toEqual([]);
    expect(scan.warnings).toEqual([]);
  });

  test('same input gives the same output every time', () => {
    expect(scanModule(GOLDEN_SUBJECT, 'src/registration.js')).toEqual(
      scanModule(GOLDEN_SUBJECT, 'src/registration.js'),
    );
  });
});

describe('C3-04 scanModule require patterns (lib/main.js)', () => {
  const scan = scanModule(SUBJECT, 'lib/main.js', { expectedExports: ['isAbsolute', 'notThere'] });

  test('lists every import with its kind; ./helpers resolves to helpers/index.js', () => {
    expect(scan.imports.map((i) => [i.importSpecifier, i.kind, i.resolvedPath])).toEqual([
      ['fs', 'node_builtin', undefined],
      ['path', 'node_builtin', undefined],
      ['node:path', 'node_builtin', undefined],
      ['./repo', 'internal_module', 'lib/repo.js'],
      ['debug', 'external_package', undefined],
      ['./helpers', 'internal_module', 'lib/helpers/index.js'],
      ['./limits.json', 'internal_module', 'lib/limits.json'],
      ['crypto', 'node_builtin', undefined],
    ]);
  });

  test('an unused import (basename) is listed as an import but not as a dependency', () => {
    expect(scan.imports.find((i) => i.importSpecifier === 'path')!.localNames).toContain(
      'basename',
    );
    expect(scan.dependencies.some((d) => d.symbol === 'basename')).toBe(false);
  });

  test('a function that uses nothing reaches no dependency (like Express-5 isAbsolute)', () => {
    expect(reach(scan, 'isAbsolute')).toEqual([]);
  });

  test('member use of a whole-module require gives the member as symbol, with JSDoc types', () => {
    expect(reach(scan, 'saveUser')).toEqual(['./repo#save', 'Date#now']);
    expect(dep(scan, './repo#save')!.typeSignature).toContain('name: string');
    expect(dep(scan, 'Date#now')).toMatchObject({ kind: 'global_object', symbol: 'now' });
  });

  test('dependencies reached through a local helper and through another export are included', () => {
    const expected = ['./limits.json#maxName', 'fs#readFileSync', 'node:path#join'];
    expect(reach(scan, 'loadConfig')).toEqual(expected);
    expect(reach(scan, 'reloadConfig')).toEqual(expected);
  });

  test('Math.random counts, Math.floor and a parameter called process do not', () => {
    expect(reach(scan, 'pickId')).toEqual(['./helpers#pad', 'Math#random']);
    expect(dep(scan, 'Math#floor')).toBeUndefined();
  });

  test('an inline require inside a function is found', () => {
    expect(reach(scan, 'hash')).toEqual(['crypto#createHash']);
  });

  test('code that runs on require() is reported, including a forEach callback', () => {
    expect(scan.moduleLoadDependencies).toEqual([
      'debug#default',
      'fs#readdirSync',
      'node:path#join',
      'path#join',
      'process#env',
    ]);
    expect(dep(scan, 'debug#default')!.lines).toEqual([8, 15]);
  });

  test('warns about a computed require and a missing manifest export', () => {
    expect(scan.warnings).toEqual([
      'line 11: require() with a non-literal argument is skipped',
      "export 'notThere' from the subject manifest was not found",
    ]);
  });
});

describe('C3-04 scanModule export styles and problems', () => {
  test('module.exports = makeBadge is found by name with style "module"', () => {
    const scan = scanModule(SUBJECT, 'lib/badge.js', { expectedExports: ['makeBadge'] });
    expect(scan.exports.map((e) => [e.name, e.style])).toEqual([
      ['makeBadge', 'module'],
      ['version', 'named'],
    ]);
    expect(reach(scan, 'makeBadge')).toEqual(['./does-not-exist#suffix', 'util#format']);
    expect(scan.warnings).toEqual(["line 2: cannot resolve internal module './does-not-exist'"]);
  });

  test('a nameless module.exports = function is named after its file (BugsJS eslint-197)', () => {
    const scan = scanModule(SUBJECT, 'lib/formatters/junit-like.js');
    expect(scan.exports.map((e) => [e.name, e.style, e.params])).toEqual([
      ['junitLike', 'module', ['results']],
    ]);
    expect(reach(scan, 'junitLike')).toEqual(['util#format']);
  });

  test('nameFromFile gives a valid variable name', () => {
    expect(nameFromFile('lib/formatters/junit.js')).toBe('junit');
    expect(nameFromFile('lib/make-badge.js')).toBe('makeBadge');
    expect(nameFromFile('C:\\x\\lib\\index.js')).toBe('lib');
    expect(nameFromFile('lib/2fa.js')).toBe('_2fa');
    expect(nameFromFile('lib/default.js')).toBe('defaultModule');
  });

  test('ES modules: default, namespace and renamed imports', () => {
    const scan = scanModule(SUBJECT, 'lib/esm.mjs');
    expect(reach(scan, 'readCount')).toEqual(['node:fs#readFileSync', 'qs#parse']);
    expect(reach(scan, 'later')).toEqual(['node:timers/promises#setTimeout']);
    expect(dep(scan, 'setTimeout#default')).toBeUndefined(); // the import name is not the global
  });

  test('a clear error when the module does not exist', () => {
    expect(() => scanModule(SUBJECT, 'lib/nope.js')).toThrow(/module lib\/nope\.js not found/);
  });
});

describe('C3-04 scan inside c3 run', () => {
  test('run scans the golden subject via source.repo_path and writes c3/work/dependency_scan.json', async () => {
    const { run } = await import('../src/index.js');
    const fs = await import('node:fs');
    const os = await import('node:os');
    const path = await import('node:path');
    const golden = fileURLToPath(
      new URL('../../contracts/fixtures/golden/example-registration', import.meta.url),
    );
    const out = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-run-'));
    try {
      await run({ in: golden, out });
      const written = JSON.parse(
        fs.readFileSync(path.join(out, 'c3', 'work', 'dependency_scan.json'), 'utf8'),
      );
      expect(written).toHaveLength(1);
      expect(written[0]).toMatchObject({
        subjectId: 'SUB-EX-1',
        modulePath: 'src/registration.js',
      });
      expect(written[0].scan.exports[1]).toMatchObject({
        name: 'registerUser',
        dependencies: ['./userRepository#save'],
      });
    } finally {
      fs.rmSync(out, { recursive: true, force: true });
    }
  });
});

describe('C3-04 side-effect guess', () => {
  test('golden userRepository.save is a database dependency (from its file name)', () => {
    const scan = scanModule(GOLDEN_SUBJECT, 'src/registration.js');
    expect(dep(scan, './userRepository#save')).toMatchObject({
      sideEffect: 'database',
      sideEffectBasis: "file name 'src/userRepository.js' contains 'repository'",
    });
  });

  test.each([
    ['./repo#save', 'database'],
    ['Date#now', 'time'],
    ['Math#random', 'random'],
    ['fs#readFileSync', 'io'],
    ['node:path#join', 'none'],
    ['crypto#createHash', 'none'],
    ['debug#default', 'io'],
    ['./limits.json#maxName', 'none'],
    ['./helpers#pad', 'none'],
    ['process#env', 'io'],
  ])('%s -> %s', (key, effect) => {
    const scan = scanModule(SUBJECT, 'lib/main.js');
    expect(dep(scan, key)!.sideEffect).toBe(effect);
  });

  test('an internal module takes the effect of what it uses; unknown packages stay unknown', () => {
    const scan = scanModule(SUBJECT, 'lib/badge.js');
    expect(dep(scan, './does-not-exist#suffix')!.sideEffect).toBe('unknown');
    expect(dep(scan, 'util#format')!.sideEffect).toBe('none');
    const esm = scanModule(SUBJECT, 'lib/esm.mjs');
    expect(dep(esm, 'node:timers/promises#setTimeout')!.sideEffect).toBe('time');
    expect(dep(esm, 'qs#parse')!.sideEffect).toBe('none');
  });

  test('pathWords splits folders, dashes and camelCase', async () => {
    const { pathWords } = await import('../src/scan/side-effects.js');
    expect(pathWords('src/userRepository.js')).toEqual(['src', 'user', 'repository']);
    expect(pathWords('lib/measure-text.js')).toEqual(['lib', 'measure', 'text']);
  });
});
