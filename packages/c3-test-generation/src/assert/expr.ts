// C3-08 helpers for the small JavaScript expressions the model writes into slots (act, actual, expected, ...).
// The model never writes whole statements: C3 checks each slot here and the templates (templates.ts) build the code.
import { ts } from 'ts-morph';

/** Globals a slot expression may use (no I/O, no process, no require). */
export const SAFE_GLOBALS: ReadonlySet<string> = new Set([
  'undefined',
  'NaN',
  'Infinity',
  'Math',
  'JSON',
  'Number',
  'String',
  'Boolean',
  'Array',
  'Object',
  'Date',
  'Buffer',
  'Error',
  'TypeError',
  'RangeError',
  'SyntaxError',
  'Symbol',
  'BigInt',
  'Map',
  'Set',
  'Promise',
  'RegExp',
  'parseInt',
  'parseFloat',
  'isNaN',
]);

export const BUILTIN_ERRORS: ReadonlySet<string> = new Set([
  'Error',
  'TypeError',
  'RangeError',
  'SyntaxError',
  'ReferenceError',
]);

/** A valid JS identifier for an Examples column ('max age' -> 'max_age', '1st' -> 'c_1st'). */
export function paramName(column: string, taken: ReadonlySet<string> = new Set()): string {
  let name =
    column
      .trim()
      .replace(/[^A-Za-z0-9_$]+/g, '_')
      .replace(/^_+|_+$/g, '') || 'value';
  if (/^[0-9]/.test(name)) name = `c_${name}`;
  if (taken.has(name) || SAFE_GLOBALS.has(name) || RESERVED.has(name)) name = `ex_${name}`;
  return name;
}

const RESERVED = new Set(
  'break case catch class const continue debugger default delete do else enum export extends false finally for function if import in instanceof new null return super switch this throw true try typeof var void while with yield let static await async result'.split(
    ' ',
  ),
);

export interface Placeholders {
  /** Text with every <column> replaced by its parameter name. */
  code: string;
  /** Columns used, and whether each was written inside quotes ("<path>" -> a string). */
  used: Map<string, { param: string; quoted: boolean }>;
  /** <names> that are not Examples columns. */
  unknown: string[];
}

/**
 * Replace Gherkin placeholders with parameter names. `"<path>"` (quoted) becomes the parameter itself,
 * so the row value is passed as a string; a bare `<age>` becomes the parameter with the row's typed value.
 */
export function replacePlaceholders(
  text: string,
  params: ReadonlyMap<string, string>,
): Placeholders {
  const used = new Map<string, { param: string; quoted: boolean }>();
  const unknown: string[] = [];
  const swap = (col: string, quoted: boolean, whole: string) => {
    const p = params.get(col);
    if (!p) {
      if (!unknown.includes(col)) unknown.push(col);
      return whole;
    }
    const prev = used.get(col);
    used.set(col, { param: p, quoted: prev ? prev.quoted && quoted : quoted });
    return p;
  };
  const code = text
    .replace(/(["'`])<([^<>"'`]+)>\1/g, (whole, _q, col: string) => swap(col, true, whole))
    .replace(/<([A-Za-z_][^<>"'`\n]*?)>/g, (whole, col: string) => swap(col, false, whole));
  return { code, used, unknown };
}

export interface ExprCheck {
  ok: boolean;
  problems: string[];
  /** Free identifiers the expression uses. */
  identifiers: string[];
  /** For a call: the called name ('registerUser', or 'utils' for utils.isAbsolute(...)). */
  callee?: string;
  calleeText?: string;
}

/** Parse one JS expression and list the free names it uses. */
export function checkExpression(code: string, allowed: ReadonlySet<string>): ExprCheck {
  const problems: string[] = [];
  const src = `(${code}\n);`;
  const sf = ts.createSourceFile('slot.js', src, ts.ScriptTarget.ES2022, true, ts.ScriptKind.JS);
  const diags =
    (sf as unknown as { parseDiagnostics?: { messageText: unknown }[] }).parseDiagnostics ?? [];
  if (!code.trim()) problems.push('empty expression');
  if (diags.length) {
    const m = diags[0]!.messageText;
    problems.push(`not a valid JS expression (${typeof m === 'string' ? m : 'syntax error'})`);
  }
  const stmt = sf.statements[0];
  if (sf.statements.length !== 1 || !stmt || !ts.isExpressionStatement(stmt)) {
    if (!diags.length) problems.push('must be one expression');
    return { ok: false, problems, identifiers: [] };
  }
  let expr: ts.Expression = stmt.expression;
  while (ts.isParenthesizedExpression(expr)) expr = expr.expression;

  const locals = new Set<string>();
  const ids = new Set<string>();
  const visit = (n: ts.Node): void => {
    if (
      (ts.isArrowFunction(n) || ts.isFunctionExpression(n)) &&
      n.parameters.every((p) => ts.isIdentifier(p.name))
    ) {
      for (const p of n.parameters) locals.add((p.name as ts.Identifier).text);
    }
    if (ts.isIdentifier(n)) {
      const parent = n.parent;
      const isPropName =
        (ts.isPropertyAccessExpression(parent) && parent.name === n) ||
        (ts.isPropertyAssignment(parent) && parent.name === n) ||
        (ts.isMethodDeclaration(parent) && parent.name === n) ||
        ts.isParameter(parent);
      if (!isPropName && !locals.has(n.text)) ids.add(n.text);
    }
    if (n.kind === ts.SyntaxKind.ThisKeyword) problems.push('`this` is not allowed');
    ts.forEachChild(n, visit);
  };
  visit(expr);
  const identifiers = [...ids].sort();
  const bad = identifiers.filter((i) => !allowed.has(i) && !SAFE_GLOBALS.has(i));
  if (bad.length) problems.push(`unknown name(s): ${bad.join(', ')}`);

  let callee: string | undefined;
  let calleeText: string | undefined;
  let inner: ts.Expression = expr;
  if (ts.isAwaitExpression(inner)) inner = inner.expression;
  if (ts.isCallExpression(inner) || ts.isNewExpression(inner)) {
    let c: ts.Expression = inner.expression;
    calleeText = c.getText(sf);
    while (ts.isPropertyAccessExpression(c)) c = c.expression;
    if (ts.isIdentifier(c)) callee = c.text;
  }
  return { ok: problems.length === 0, problems, identifiers, callee, calleeText };
}

/** True when the expression text is a literal that toBe() compares well (number, string, boolean, null). */
export function isPrimitiveLiteral(code: string): boolean {
  const t = code.trim();
  return (
    /^-?\d+(\.\d+)?([eE][-+]?\d+)?$/.test(t) ||
    /^(true|false|null|undefined|NaN)$/.test(t) ||
    /^"([^"\\]|\\.)*"$/.test(t) ||
    /^'([^'\\]|\\.)*'$/.test(t)
  );
}

/**
 * Turn a JSON value from the model into JS code. A string that is exactly "<column>" becomes the column's
 * parameter; "<column>" inside a longer string becomes a template literal part. Other values are literals.
 */
export function renderValue(
  v: unknown,
  params: ReadonlyMap<string, string>,
  unknown: string[] = [],
): string {
  if (typeof v === 'string') {
    const whole = /^<([^<>]+)>$/.exec(v);
    if (whole) {
      const p = params.get(whole[1]!);
      if (p) return p;
      unknown.push(whole[1]!);
      return JSON.stringify(v);
    }
    if (/<[^<>]+>/.test(v)) {
      let any = false;
      const body = v
        .replace(/[`\\$]/g, (c) => `\\${c}`)
        .replace(/<([^<>]+)>/g, (m, col: string) => {
          const p = params.get(col);
          if (!p) {
            unknown.push(col);
            return m;
          }
          any = true;
          return `\${${p}}`;
        });
      if (any) return `\`${body}\``;
    }
    return JSON.stringify(v);
  }
  if (Array.isArray(v)) return `[${v.map((x) => renderValue(x, params, unknown)).join(', ')}]`;
  if (v && typeof v === 'object') {
    const parts = Object.entries(v).map(
      ([k, x]) =>
        `${/^[A-Za-z_$][\w$]*$/.test(k) ? k : JSON.stringify(k)}: ${renderValue(x, params, unknown)}`,
    );
    return parts.length ? `{ ${parts.join(', ')} }` : '{}';
  }
  if (v === undefined) return 'undefined';
  return JSON.stringify(v);
}
