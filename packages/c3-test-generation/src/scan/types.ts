// Types for the C3-04 dependency scan (FR2).
// Field names follow the `dependency` object in packages/contracts/schemas/c3-mock-decisions.schema.json,
// so C3-05 can copy a scanned dependency straight into mock_decisions.json.
import type { SideEffect } from './side-effects.js';

export type { SideEffect } from './side-effects.js';

/** Same 4 values as `dependency.kind` in the mock-decisions contract. */
export type DependencyKind =
  'external_package' | 'node_builtin' | 'internal_module' | 'global_object';

/** One `require(...)` / `import` line at the top of (or anywhere in) the module. */
export interface ScannedImport {
  importSpecifier: string; // text inside require('...'), e.g. './userRepository', 'path', 'qs'
  kind: Exclude<DependencyKind, 'global_object'>;
  resolvedPath?: string; // internal modules only: file path relative to the subject root, with '/'
  localNames: string[]; // names this file gives it, e.g. ['userRepository'] or ['basename']
  line: number;
}

/** One thing the module really uses from a dependency, e.g. `save` from './userRepository'. */
export interface ScannedDependency {
  key: string; // stable id inside one scan: '<importSpecifier>#<symbol>'
  importSpecifier: string; // for globals: the global's name, e.g. 'Date'
  symbol: string; // e.g. 'save', 'basename', 'now'; 'default' = the whole module / value is used
  kind: DependencyKind;
  resolvedPath?: string;
  typeSignature?: string; // from the TypeScript checker, e.g. '(user: any) => never'
  sideEffect: SideEffect; // guess, same enum as dependency.side_effect in the contract
  sideEffectBasis: string; // why, e.g. "node builtin 'fs'" or "file name 'src/userRepository.js'"
  lines: number[]; // every line where it is used (sorted, unique)
}

/** One exported function/value of the module and the dependencies it reaches. */
export interface ScannedExport {
  name: string; // exported name, e.g. 'registerUser'; for `module.exports = makeBadge` -> 'makeBadge'
  /** named: `const { name } = require(module)`; module: the module itself is the value (`module.exports = fn`). */
  style: 'named' | 'module';
  line: number;
  /** Keys of ScannedDependency used directly or through local helper functions in the same file. */
  dependencies: string[];
}

export interface ModuleScan {
  subjectRoot: string; // absolute path of the checked-out subject
  modulePath: string; // relative to subjectRoot, with '/'
  imports: ScannedImport[];
  dependencies: ScannedDependency[];
  exports: ScannedExport[];
  /**
   * Keys used while the module loads (top-level code, callbacks run during loading, local functions
   * that code calls), e.g. require('depd')('express'). These run as soon as a test requires the module.
   */
  moduleLoadDependencies: string[];
  warnings: string[];
}
