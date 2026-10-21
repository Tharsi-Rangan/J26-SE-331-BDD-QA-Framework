// C3-04 dependency scan (FR2).
// Reads one subject module with ts-morph and lists:
//   1. what it imports (require / import),
//   2. what it really uses from each import, plus risky globals (Date, Math.random, process, timers ...),
//   3. which of those each exported function reaches (directly or through local helpers).
// No decisions are made here. C3-05 turns this into mock / no_mock decisions.
import fs from 'node:fs';
import { builtinModules } from 'node:module';
import path from 'node:path';
import {
  Node,
  Project,
  SyntaxKind,
  ts,
  type CallExpression,
  type Identifier,
  type SourceFile,
} from 'ts-morph';
import {
  guessExternalOrBuiltin,
  guessInternal,
  LOGGING,
  packageName,
  type SideEffect,
} from './side-effects.js';
import type {
  DependencyKind,
  ModuleScan,
  ScannedDependency,
  ScannedExport,
  ScannedImport,
} from './types.js';

const BUILTINS = new Set(builtinModules.map((m) => m.replace(/^node:/, '')));
const RESOLVE_EXTENSIONS = ['.js', '.cjs', '.mjs', '.ts', '.json'];

/**
 * Globals worth reporting, because a test may need to control them.
 * 'all' = any use counts; a Set = only these members count (Math.floor is pure, Math.random is not).
 */
const GLOBALS: ReadonlyMap<string, 'all' | ReadonlySet<string>> = new Map<
  string,
  'all' | ReadonlySet<string>
>([
  ['Date', 'all'],
  ['Math', new Set(['random'])],
  ['process', 'all'],
  ['console', 'all'],
  ['setTimeout', 'all'],
  ['setInterval', 'all'],
  ['setImmediate', 'all'],
  ['clearTimeout', 'all'],
  ['clearInterval', 'all'],
  ['queueMicrotask', 'all'],
  ['fetch', 'all'],
  ['crypto', 'all'],
  ['performance', 'all'],
]);

/** Which of the 4 contract kinds an import specifier is (globals are found separately). */
export function classifySpecifier(spec: string): Exclude<DependencyKind, 'global_object'> {
  if (spec.startsWith('node:')) return 'node_builtin';
  if (spec.startsWith('.') || spec.startsWith('/')) return 'internal_module';
  if (BUILTINS.has(spec)) return 'node_builtin';
  return 'external_package';
}

/** Resolve './x' the way Node does (x, x.js, x/index.js ...). Returns a subject-relative '/' path. */
export function resolveInternal(
  subjectRoot: string,
  fromFile: string,
  spec: string,
): string | undefined {
  const base = path.resolve(path.dirname(fromFile), spec);
  const candidates = [
    base,
    ...RESOLVE_EXTENSIONS.map((e) => base + e),
    ...RESOLVE_EXTENSIONS.map((e) => path.join(base, 'index' + e)),
  ];
  const hit = candidates.find((c) => fs.existsSync(c) && fs.statSync(c).isFile());
  return hit === undefined ? undefined : toPosix(path.relative(subjectRoot, hit));
}

function toPosix(p: string): string {
  return p.split(path.sep).join('/');
}

/** How a local name is tied to an import. */
interface Binding {
  spec: string;
  kind: Exclude<DependencyKind, 'global_object'>;
  resolvedPath?: string;
  /** namespace = whole module object (members refine the symbol); named/derived = fixed symbol. */
  mode: 'namespace' | 'named' | 'derived';
  symbol: string;
}

interface Usage {
  key: string;
  node: Node; // where it is used (also used to ask the checker for its type)
}

interface ExportEntry {
  name: string;
  node: Node; // the value: function, class, object, expression ...
  style: ScannedExport['style'];
}

export interface ScanOptions {
  /** Export names from subject-manifest.json; a warning is added for any the scan cannot find. */
  expectedExports?: string[];
  /** How deep to follow internal modules for the side-effect guess (default 2). */
  internalDepth?: number;
}

/**
 * Scan one module of a subject.
 * @param subjectRoot folder of the checked-out subject (e.g. a BugsJS project at buggy_ref)
 * @param modulePath  module_path from subject-manifest.json, relative to subjectRoot
 */
export function scanModule(
  subjectRoot: string,
  modulePath: string,
  options: ScanOptions = {},
): ModuleScan {
  const root = path.resolve(subjectRoot);
  const file = path.resolve(root, modulePath);
  if (!fs.existsSync(file)) {
    throw new Error(`C3-04 scan: module ${modulePath} not found under ${root}`);
  }

  const project = new Project({
    skipAddingFilesFromTsConfig: true,
    compilerOptions: {
      allowJs: true,
      checkJs: false,
      noEmit: true,
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
      moduleResolution: ts.ModuleResolutionKind.Node10,
      ignoreDeprecations: '6.0',
      esModuleInterop: true,
      skipLibCheck: true,
      types: [],
    },
  });
  const sf = project.addSourceFileAtPath(file);
  project.resolveSourceFileDependencies(); // loads internal modules so the checker knows their types

  const warnings: string[] = [];
  const imports = new Map<string, ScannedImport>();
  const bindings = new Map<ts.Symbol, Binding>();
  const usages: Usage[] = [];

  const addImport = (spec: string, line: number, localName?: string): Binding => {
    const kind = classifySpecifier(spec);
    const resolvedPath = kind === 'internal_module' ? resolveInternal(root, file, spec) : undefined;
    if (kind === 'internal_module' && resolvedPath === undefined) {
      warnings.push(`line ${line}: cannot resolve internal module '${spec}'`);
    }
    const imp = imports.get(spec) ?? {
      importSpecifier: spec,
      kind,
      ...(resolvedPath ? { resolvedPath } : {}),
      localNames: [],
      line,
    };
    if (localName && !imp.localNames.includes(localName)) imp.localNames.push(localName);
    imports.set(spec, imp);
    return { spec, kind, resolvedPath, mode: 'namespace', symbol: 'default' };
  };
  const declarationNames = new Set<Node>(); // the names in `const x = require(...)` are not usages
  const bind = (nameNode: Node, b: Binding) => {
    declarationNames.add(nameNode);
    const sym = nameNode.getSymbol()?.compilerSymbol;
    if (sym) bindings.set(sym, b);
  };
  const keyOf = (spec: string, symbol: string) => `${spec}#${symbol}`;

  // ---- 1. require(...) calls ----
  for (const call of sf.getDescendantsOfKind(SyntaxKind.CallExpression)) {
    if (!isRequireCall(call)) continue;
    const line = call.getStartLineNumber();
    const spec = requireSpecifier(call);
    if (spec === undefined) {
      warnings.push(`line ${line}: require() with a non-literal argument is skipped`);
      continue;
    }

    // Climb `require('x').a.b(...)` to the outermost expression of the chain.
    let top: Node = call;
    const chain: Node[] = [];
    for (;;) {
      const p = top.getParent();
      if (
        p &&
        (Node.isPropertyAccessExpression(p) ||
          Node.isCallExpression(p) ||
          Node.isElementAccessExpression(p)) &&
        p.getExpression() === top
      ) {
        chain.push(p);
        top = p;
      } else break;
    }
    const firstSymbol = chainSymbol(chain[0]);
    const decl = top.getParent();

    if (decl && Node.isVariableDeclaration(decl) && decl.getInitializer() === top) {
      const nameNode = decl.getNameNode();
      if (Node.isIdentifier(nameNode)) {
        const base = addImport(spec, line, nameNode.getText());
        if (chain.length === 0) {
          bind(nameNode, base); // const repo = require('./repo')
        } else if (chain.length === 1 && Node.isPropertyAccessExpression(chain[0])) {
          bind(nameNode, { ...base, mode: 'named', symbol: firstSymbol }); // var basename = require('path').basename
        } else {
          // var deprecate = require('depd')('express'): the module runs while loading
          bind(nameNode, { ...base, mode: 'derived', symbol: firstSymbol });
          usages.push({ key: keyOf(spec, firstSymbol), node: chain[0]! });
        }
      } else if (Node.isObjectBindingPattern(nameNode)) {
        for (const el of nameNode.getElements()) {
          const local = el.getNameNode();
          const prop = el.getPropertyNameNode()?.getText() ?? el.getName();
          const base = addImport(spec, line, local.getText());
          bind(
            local,
            chain.length === 0
              ? { ...base, mode: 'named', symbol: prop }
              : { ...base, mode: 'derived', symbol: firstSymbol },
          );
        }
      } else {
        addImport(spec, line);
        warnings.push(`line ${line}: array destructuring of require('${spec}') is not tracked`);
      }
    } else {
      // Used inline, e.g. require('fs').readFileSync(p) inside a function, or a bare require('x').
      addImport(spec, line);
      usages.push({ key: keyOf(spec, firstSymbol), node: chain[0] ?? call });
    }
  }

  // ---- 2. ES import declarations ----
  for (const imp of sf.getImportDeclarations()) {
    const spec = imp.getModuleSpecifierValue();
    const line = imp.getStartLineNumber();
    const def = imp.getDefaultImport();
    const ns = imp.getNamespaceImport();
    const named = imp.getNamedImports();
    if (!def && !ns && named.length === 0) addImport(spec, line);
    // A default import of a CommonJS module is the whole module object (esModuleInterop), so
    // `fs.readFileSync` counts as readFileSync, the same as with `const fs = require('fs')`.
    if (def) bind(def, addImport(spec, line, def.getText()));
    if (ns) bind(ns, addImport(spec, line, ns.getText()));
    for (const n of named) {
      const local = n.getAliasNode() ?? n.getNameNode();
      bind(local, {
        ...addImport(spec, line, local.getText()),
        mode: 'named',
        symbol: n.getName(),
      });
    }
  }

  // ---- 3. Every place an imported name or a reported global is used ----
  for (const id of sf.getDescendantsOfKind(SyntaxKind.Identifier)) {
    if (declarationNames.has(id)) continue;
    const sym = id.getSymbol()?.compilerSymbol;
    const b = sym ? bindings.get(sym) : undefined;
    if (b) {
      const parent = id.getParent();
      if (
        b.mode === 'namespace' &&
        Node.isPropertyAccessExpression(parent) &&
        parent.getExpression() === id
      ) {
        usages.push({ key: keyOf(b.spec, parent.getName()), node: parent });
      } else {
        usages.push({ key: keyOf(b.spec, b.symbol), node: id });
      }
      continue;
    }
    const g = globalUse(id);
    if (g) usages.push({ key: keyOf(g.name, g.symbol), node: g.node });
  }

  // ---- 4. Merge usages into one entry per (specifier, symbol) ----
  const deps = new Map<string, ScannedDependency>();
  for (const u of usages) {
    const line = u.node.getStartLineNumber();
    const existing = deps.get(u.key);
    if (existing) {
      if (!existing.lines.includes(line)) existing.lines.push(line);
      continue;
    }
    const hash = u.key.lastIndexOf('#');
    const spec = u.key.slice(0, hash);
    const symbol = u.key.slice(hash + 1);
    const imp = imports.get(spec);
    const kind: DependencyKind = imp ? imp.kind : 'global_object';
    deps.set(u.key, {
      key: u.key,
      importSpecifier: spec,
      symbol,
      kind,
      ...(imp?.resolvedPath ? { resolvedPath: imp.resolvedPath } : {}),
      ...typeOf(u.node),
      sideEffect: 'unknown',
      sideEffectBasis: '',
      lines: [line],
    });
  }
  for (const d of deps.values()) d.lines.sort((a, b) => a - b);

  // ---- 4b. Side-effect guess (C3-04 checklist). Internal modules: look at what they use. ----
  const depth = options.internalDepth ?? 2;
  const innerCache = new Map<string, ModuleScan | null>();
  const innerScan = (resolvedPath: string): ModuleScan | null => {
    if (!innerCache.has(resolvedPath)) {
      let inner: ModuleScan | null = null;
      try {
        inner = scanModule(root, resolvedPath, { internalDepth: depth - 1 });
      } catch {
        inner = null;
      }
      innerCache.set(resolvedPath, inner);
    }
    return innerCache.get(resolvedPath)!;
  };
  /** Effects of what `symbol` of an internal module reaches when called (not what its file does on load). */
  const innerEffects = (resolvedPath: string, symbol: string): SideEffect[] => {
    if (depth <= 0 || resolvedPath.endsWith('.json')) return [];
    const inner = innerScan(resolvedPath);
    if (!inner) return ['unknown'];
    const exp =
      inner.exports.find((e) => e.name === symbol) ??
      (symbol === 'default' ? inner.exports.find((e) => e.style === 'module') : undefined);
    const keys = exp ? new Set(exp.dependencies) : new Set(inner.dependencies.map((d) => d.key));
    return inner.dependencies
      .filter((d) => keys.has(d.key) && !LOGGING.has(packageName(d.importSpecifier)))
      .map((d) => d.sideEffect);
  };
  for (const d of deps.values()) {
    const guess =
      d.kind === 'internal_module'
        ? guessInternal(
            d.resolvedPath,
            d.resolvedPath ? innerEffects(d.resolvedPath, d.symbol) : [],
          )
        : guessExternalOrBuiltin(d.kind, d.importSpecifier, d.symbol);
    d.sideEffect = guess.sideEffect;
    d.sideEffectBasis = guess.basis;
  }

  // ---- 5. Exports, and the dependencies each one reaches ----
  const exportEntries = collectExports(sf, warnings);
  const exportsByName = new Map(exportEntries.map((e) => [e.name, e]));
  const reach = (start: Node): string[] => {
    const found = new Set<string>();
    const seen = new Set<Node>();
    const visit = (n: Node) => {
      if (seen.has(n)) return;
      seen.add(n);
      for (const u of usages) if (contains(n, u.node)) found.add(u.key);
      for (const id of n.getDescendantsOfKind(SyntaxKind.Identifier)) {
        const local = localDeclaration(id, sf);
        if (local && !contains(n, local)) visit(local);
      }
      // exports.other(...) / module.exports.other(...) inside this export
      for (const pa of n.getDescendantsOfKind(SyntaxKind.PropertyAccessExpression)) {
        const obj = pa.getExpression().getText();
        if (obj === 'exports' || obj === 'module.exports') {
          const other = exportsByName.get(pa.getName());
          if (other && !contains(n, other.node)) visit(other.node);
        }
      }
    };
    if (Node.isIdentifier(start)) {
      const local = localDeclaration(start, sf);
      if (local) visit(local);
    } else {
      visit(start);
    }
    return [...found].sort();
  };
  const exportScans: ScannedExport[] = exportEntries.map((e) => ({
    name: e.name,
    style: e.style,
    line: e.node.getStartLineNumber(),
    dependencies: reach(e.node),
    ...exportShape(e.node),
    ...docOf(e.node),
  }));
  for (const name of options.expectedExports ?? []) {
    if (!exportsByName.has(name))
      warnings.push(`export '${name}' from the subject manifest was not found`);
  }

  // Code that runs as soon as a test does require(module): top-level code, callbacks it calls
  // right away (forEach(function(){...}), IIFEs), and local functions that code calls.
  const moduleLoad = new Set<string>();
  for (const u of usages) if (runsAtLoad(u.node)) moduleLoad.add(u.key);
  for (const call of [
    ...sf.getDescendantsOfKind(SyntaxKind.CallExpression),
    ...sf.getDescendantsOfKind(SyntaxKind.NewExpression),
  ]) {
    const callee = call.getExpression();
    if (!Node.isIdentifier(callee) || !runsAtLoad(call)) continue;
    const local = localDeclaration(callee, sf);
    if (local) for (const k of reach(local)) moduleLoad.add(k);
  }

  return {
    subjectRoot: root,
    modulePath: toPosix(path.relative(root, file)),
    imports: [...imports.values()].sort(
      (a, b) => a.line - b.line || cmp(a.importSpecifier, b.importSpecifier),
    ),
    dependencies: [...deps.values()].sort((a, b) => cmp(a.key, b.key)),
    exports: exportScans.sort((a, b) => a.line - b.line || cmp(a.name, b.name)),
    moduleLoadDependencies: [...moduleLoad].sort(),
    warnings,
  };
}

// ---------------------------------------------------------------- helpers

function cmp(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function isRequireCall(call: CallExpression): boolean {
  const e = call.getExpression();
  return Node.isIdentifier(e) && e.getText() === 'require';
}

/**
 * The module name a require() asks for: require('x'), or the common static form
 * require(path.join(__dirname, 'a', 'b.json')) -> './a/b.json'. Undefined when it is computed at runtime.
 */
function requireSpecifier(call: CallExpression): string | undefined {
  const arg = call.getArguments()[0];
  if (!arg) return undefined;
  if (Node.isStringLiteral(arg) || Node.isNoSubstitutionTemplateLiteral(arg)) {
    return arg.getLiteralValue();
  }
  if (Node.isCallExpression(arg) && /^path\.(join|resolve)$/.test(arg.getExpression().getText())) {
    const [first, ...rest] = arg.getArguments();
    if (first?.getText() !== '__dirname' || rest.length === 0) return undefined;
    const parts: string[] = [];
    for (const r of rest) {
      if (!(Node.isStringLiteral(r) || Node.isNoSubstitutionTemplateLiteral(r))) return undefined;
      parts.push(r.getLiteralValue());
    }
    const joined = path.posix.normalize(parts.join('/'));
    return joined.startsWith('..') ? joined : './' + joined;
  }
  return undefined;
}

/** The symbol name the first step of a require chain picks: `.mime` -> 'mime', `(...)` -> 'default'. */
function chainSymbol(step: Node | undefined): string {
  if (step && Node.isPropertyAccessExpression(step)) return step.getName();
  if (step && Node.isElementAccessExpression(step)) {
    const a = step.getArgumentExpression();
    if (a && Node.isStringLiteral(a)) return a.getLiteralValue();
  }
  return 'default';
}

/** If `id` is a reported global (not shadowed by a local name), the global and member it uses. */
function globalUse(id: Identifier): { name: string; symbol: string; node: Node } | undefined {
  const name = id.getText();
  const rule = GLOBALS.get(name);
  if (!rule) return undefined;
  const parent = id.getParent();
  // Skip `import { setTimeout as wait }`, `obj.Date`, `{ Date: 1 }`, `function Date() {}` and other
  // places where the word is not the global itself.
  if (
    id.getFirstAncestorByKind(SyntaxKind.ImportDeclaration) ||
    id.getFirstAncestorByKind(SyntaxKind.ExportDeclaration)
  ) {
    return undefined;
  }
  if (Node.isPropertyAccessExpression(parent) && parent.getNameNode() === id) return undefined;
  if (Node.isPropertyAssignment(parent) && parent.getNameNode() === id) return undefined;
  if (
    (Node.isVariableDeclaration(parent) ||
      Node.isFunctionDeclaration(parent) ||
      Node.isParameterDeclaration(parent)) &&
    parent.getNameNode() === id
  )
    return undefined;
  const decls = id.getSymbol()?.getDeclarations() ?? [];
  if (decls.some((d) => !d.getSourceFile().isDeclarationFile())) return undefined; // a local variable called e.g. `process`
  const member =
    Node.isPropertyAccessExpression(parent) && parent.getExpression() === id
      ? parent.getName()
      : undefined;
  if (rule !== 'all' && (member === undefined || !rule.has(member))) return undefined;
  return {
    name,
    symbol: member ?? 'default',
    node: member !== undefined ? parent! : id,
  };
}

/** Type text from the TypeScript checker, e.g. '(user: any) => never'. Left out when it is only 'any'. */
function typeOf(node: Node): { typeSignature?: string } {
  try {
    const text = node
      .getType()
      .getText(
        node,
        ts.TypeFormatFlags.NoTruncation | ts.TypeFormatFlags.UseAliasDefinedOutsideCurrentScope,
      );
    if (!text || text === 'any') return {};
    return { typeSignature: text.length > 300 ? text.slice(0, 297) + '...' : text };
  } catch {
    return {};
  }
}

function contains(outer: Node, inner: Node): boolean {
  return (
    outer.getSourceFile() === inner.getSourceFile() &&
    inner.getStart() >= outer.getStart() &&
    inner.getEnd() <= outer.getEnd()
  );
}

/**
 * True when `n` runs while the module is loading: it is not inside a function, or only inside
 * functions that are called right away during loading (callbacks passed to a call, IIFEs).
 */
function runsAtLoad(n: Node): boolean {
  const fn = enclosingFunction(n);
  if (!fn) return true;
  if (!(Node.isFunctionExpression(fn) || Node.isArrowFunction(fn))) return false;
  let p = fn.getParent();
  while (p && Node.isParenthesizedExpression(p)) p = p.getParent();
  if (p && (Node.isCallExpression(p) || Node.isNewExpression(p))) return runsAtLoad(p);
  return false;
}

function enclosingFunction(n: Node): Node | undefined {
  return n.getFirstAncestor(
    (a) =>
      Node.isFunctionDeclaration(a) ||
      Node.isFunctionExpression(a) ||
      Node.isArrowFunction(a) ||
      Node.isMethodDeclaration(a) ||
      Node.isConstructorDeclaration(a) ||
      Node.isGetAccessorDeclaration(a) ||
      Node.isSetAccessorDeclaration(a),
  );
}

/** The top-level function / class / variable in this file that `id` refers to (not imports). */
function localDeclaration(id: Identifier, sf: SourceFile): Node | undefined {
  const parent = id.getParent();
  if (Node.isPropertyAccessExpression(parent) && parent.getNameNode() === id) return undefined;
  for (const d of id.getSymbol()?.getDeclarations() ?? []) {
    if (d.getSourceFile() !== sf) continue;
    if (Node.isFunctionDeclaration(d) || Node.isClassDeclaration(d)) {
      if (d.getParent() === sf) return d;
    }
    if (Node.isVariableDeclaration(d)) {
      const init = d.getInitializer();
      const statement = d.getVariableStatement();
      if (!init || !statement || statement.getParent() !== sf) continue;
      if (Node.isCallExpression(init) && isRequireCall(init)) continue; // an import, already counted
      return init;
    }
  }
  return undefined;
}

/**
 * Name for `module.exports = <value>`: the identifier or function/class name. A nameless function or class
 * (`module.exports = function (results) {...}`) is named after its file (`formatters/junit.js` -> `junit`,
 * `make-badge.js` -> `makeBadge`), because the test needs a variable name for it (`const junit = require(...)`).
 * Anything else stays 'default'.
 */
function moduleExportName(right: Node, value: Node, sf?: SourceFile): string {
  if (Node.isIdentifier(right)) return right.getText();
  const fnOrClass =
    Node.isFunctionDeclaration(value) ||
    Node.isFunctionExpression(value) ||
    Node.isArrowFunction(value) ||
    Node.isClassDeclaration(value) ||
    Node.isClassExpression(value);
  if (fnOrClass && !Node.isArrowFunction(value) && value.getName()) return value.getName()!;
  if (fnOrClass && sf) return nameFromFile(sf.getFilePath());
  return 'default';
}

const JS_RESERVED = new Set(
  'break case catch class const continue debugger default delete do else enum export extends false finally for function if import in instanceof new null return super switch this throw true try typeof var void while with yield let static await async'.split(
    ' ',
  ),
);

/** 'lib/formatters/junit.js' -> 'junit', 'lib/make-badge.js' -> 'makeBadge', 'lib/index.js' -> 'lib' (folder). */
export function nameFromFile(file: string): string {
  const parts = file.replace(/\\/g, '/').split('/').filter(Boolean);
  let base = (parts.at(-1) ?? 'module').replace(/\.[^.]+$/, '');
  if (base === 'index' && parts.length > 1) base = parts.at(-2)!;
  let name = base
    .split(/[^A-Za-z0-9_$]+/)
    .filter(Boolean)
    .map((w, i) => (i === 0 ? w : w[0]!.toUpperCase() + w.slice(1)))
    .join('');
  if (!name) name = 'module';
  if (/^[0-9]/.test(name)) name = '_' + name;
  return JS_RESERVED.has(name) ? name + 'Module' : name;
}

/** C3-08: kind, parameter list and async flag of an exported value. */
/** Tags kept from a JSDoc comment: the ones that describe the interface, not visibility or build hints. */
const DOC_TAGS = /^@(param|arg|argument|returns?|throws|exception)\b/;

/**
 * C3-14: the JSDoc comment written just before the export's statement, cleaned to its description and
 * interface tags. `exports.x = function` -> the comment above the assignment; `function f` -> above f.
 */
export function docOf(node: Node): Pick<ScannedExport, 'doc'> {
  let st: Node | undefined = node;
  while (
    st &&
    !Node.isExpressionStatement(st) &&
    !Node.isFunctionDeclaration(st) &&
    !Node.isClassDeclaration(st) &&
    !Node.isVariableStatement(st) &&
    !Node.isExportAssignment(st) &&
    !Node.isPropertyAssignment(st) &&
    !Node.isMethodDeclaration(st)
  ) {
    st = st.getParent();
  }
  if (!st) return {};
  const comments = st.getLeadingCommentRanges().map((r) => r.getText());
  const jsdoc = [...comments].reverse().find((c) => c.startsWith('/**'));
  if (!jsdoc) return {};
  const lines = jsdoc
    .replace(/^\/\*\*/, '')
    .replace(/\*\/$/, '')
    .split(/\r?\n/)
    .map((l) => l.replace(/^\s*\*\s?/, '').trim())
    .filter(Boolean);
  const kept: string[] = [];
  let inTag = false;
  for (const l of lines) {
    if (l.startsWith('@')) {
      inTag = DOC_TAGS.test(l);
      if (inTag) kept.push(l.replace(/\s+/g, ' '));
    } else if (!inTag) {
      kept.push(l);
    }
  }
  const doc = kept.join(' | ').slice(0, 500);
  return doc ? { doc } : {};
}

function exportShape(node: Node): Pick<ScannedExport, 'valueKind' | 'params' | 'isAsync'> {
  if (
    Node.isFunctionDeclaration(node) ||
    Node.isFunctionExpression(node) ||
    Node.isArrowFunction(node) ||
    Node.isMethodDeclaration(node)
  ) {
    return {
      valueKind: 'function',
      params: node.getParameters().map((p) => p.getText()),
      isAsync: node.isAsync(),
    };
  }
  if (Node.isClassDeclaration(node) || Node.isClassExpression(node)) {
    const ctor = node.getConstructors()[0];
    return { valueKind: 'class', params: ctor ? ctor.getParameters().map((p) => p.getText()) : [] };
  }
  return { valueKind: 'value' };
}

/** CommonJS (`exports.x =`, `module.exports = {...}`) and ES (`export ...`) exports. */
function collectExports(sf: SourceFile, warnings: string[]): ExportEntry[] {
  const out: ExportEntry[] = [];
  const add = (name: string, node: Node, style: ExportEntry['style'] = 'named') => {
    if (!out.some((e) => e.name === name)) out.push({ name, node, style });
  };
  const resolveIdent = (n: Node): Node => {
    if (Node.isIdentifier(n)) return localDeclaration(n, sf) ?? n;
    return n;
  };

  for (const st of sf.getStatements()) {
    if (!Node.isExpressionStatement(st)) continue;
    const e = st.getExpression();
    if (!Node.isBinaryExpression(e) || e.getOperatorToken().getKind() !== SyntaxKind.EqualsToken)
      continue;
    const left = e.getLeft().getText();
    let right = e.getRight();
    // module.exports = exports = fn
    while (
      Node.isBinaryExpression(right) &&
      right.getOperatorToken().getKind() === SyntaxKind.EqualsToken
    ) {
      right = right.getRight();
    }
    const m = /^(?:module\.)?exports\.([A-Za-z_$][\w$]*)$/.exec(left);
    if (m) {
      add(m[1]!, resolveIdent(right));
    } else if (left === 'module.exports') {
      if (Node.isObjectLiteralExpression(right)) {
        for (const p of right.getProperties()) {
          if (Node.isShorthandPropertyAssignment(p)) {
            const local =
              sf.getFunction(p.getName()) ??
              sf.getClass(p.getName()) ??
              sf.getVariableDeclaration(p.getName())?.getInitializer();
            if (local) add(p.getName(), local);
            else warnings.push(`export '${p.getName()}' has no local declaration`);
          } else if (Node.isPropertyAssignment(p)) {
            const init = p.getInitializer();
            if (init) add(p.getName(), resolveIdent(init));
          } else if (Node.isMethodDeclaration(p)) {
            add(p.getName(), p);
          }
        }
      } else {
        // module.exports = makeBadge -> the test does `const makeBadge = require(...)`
        const value = resolveIdent(right);
        add(moduleExportName(right, value, sf), value, 'module');
      }
    }
  }

  // ES modules
  for (const [name, decls] of sf.getExportedDeclarations()) {
    const d = decls[0];
    if (!d || d.getSourceFile() !== sf || out.some((e) => e.name === name)) continue;
    if (
      sf.getImportDeclarations().length === 0 &&
      sf.getExportDeclarations().length === 0 &&
      !sf.getStatements().some((s) => Node.isExportable(s) && s.isExported())
    )
      continue;
    add(
      name,
      Node.isVariableDeclaration(d) ? (d.getInitializer() ?? d) : d,
      name === 'default' ? 'module' : 'named',
    );
  }
  return out;
}
