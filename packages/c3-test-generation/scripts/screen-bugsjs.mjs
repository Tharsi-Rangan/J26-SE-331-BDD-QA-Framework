// Screen every BugsJS bug: which production file/function did the developers' fix change, and can C3 (PP1) test it?
// Usage: node scripts/screen-bugsjs.mjs <folder with the 10 BugsJS clones> <out.json> [<out.csv>]
//   The folder must hold git clones of github.com/BugsJS/<project> (bower, eslint, express, hessian.js, hexo,
//   karma, mongoose, node_redis, pencilblue, shields); the script reads the Bug-N / Bug-N-fix tags, never runs code.
// In scope = the fix is in ONE production file, inside an exported function (directly or through a local helper)
// that C3 can call with plain values: no request/callback/context/AST parameters, no `this`, no constructor.
// MANUAL holds the reviewed exceptions (with the reason), so the result can be repeated exactly.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { Project, Node, SyntaxKind } = require('ts-morph');

const [, , SUBJECTS, OUT, CSV] = process.argv;
if (!SUBJECTS || !OUT) {
  console.error(
    'Usage: node scripts/screen-bugsjs.mjs <BugsJS clones folder> <out.json> [<out.csv>]',
  );
  process.exit(1);
}
/** Manual review of the automatic candidates (21 Oct 2026). */
const MANUAL = {
  'eslint-87': ['out', 'manual review: reads a config file from disk (needs file fixtures)'],
  'eslint-105': ['out', 'manual review: reads a config file from disk (needs file fixtures)'],
  'eslint-141': ['out', 'manual review: reads package.json files from disk'],
  'eslint-225': [
    'out',
    'manual review: validateRuleOptions needs a rulesContext object as 4th input',
  ],
  'eslint-273': [
    'in',
    'manual review: generateConfigsFromSchema(schema) takes a plain JSON schema',
  ],
  'karma-6': ['out', 'manual review: needs fs and path objects as parameters'],
  'karma-10': ['out', 'manual review: starts a file watcher (I/O)'],
  'shields-1': ['out', 'manual review: returns HTTP middleware (needs requests)'],
  'hessian.js-8': [
    'out',
    'manual review: needs a Long object as input (C3 builds only plain values)',
  ],
};
const PROJECTS = [
  'bower',
  'eslint',
  'express',
  'hessian.js',
  'hexo',
  'karma',
  'mongoose',
  'node_redis',
  'pencilblue',
  'shields',
];

const git = (repo, args) =>
  execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });

const NOT_PROD =
  /(^|\/)(test|tests|spec|specs|__tests__|docs?|benchmark|fixtures|examples?|bin|scripts|Makefile\.js)(\/|$)|\.(spec|test)\.js$|(^|\/)(Gruntfile|Makefile|gulpfile)\.js$/i;
// Parameters that mean the function needs something C3 cannot build from literal values in PP1.
const HARD_PARAM =
  /^(req|request|res|response|next|cb|callback|done|fn|func|context|ctx|node|ast|stream|socket|client|db|conn|connection|app|server|router|layer|route|model|schema|doc|document|query|session|stats?|file|files|dir|hexo|config|karma|emitter|log|logger|injector|buffer|buf)$/i;

function changedLines(repo, from, to, file) {
  const out = git(repo, ['diff', '-U0', from, to, '--', file]);
  const lines = [];
  for (const m of out.matchAll(/^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@/gm)) {
    const start = +m[1];
    const count = m[2] === undefined ? 1 : +m[2];
    if (count === 0)
      lines.push(start); // pure insertion after this line
    else for (let i = 0; i < count; i++) lines.push(start + i);
  }
  return lines;
}

function fnInfo(fnNode) {
  const params = fnNode.getParameters ? fnNode.getParameters().map((p) => p.getText()) : [];
  return {
    start: fnNode.getStartLineNumber(),
    end: fnNode.getEndLineNumber(),
    params,
    async: !!(fnNode.isAsync && fnNode.isAsync()),
    usesThis: fnNode.getDescendantsOfKind(SyntaxKind.ThisKeyword).some((t) => {
      for (let q = t.getParent(); q && q !== fnNode; q = q.getParent())
        if (
          Node.isFunctionExpression(q) ||
          Node.isFunctionDeclaration(q) ||
          Node.isMethodDeclaration(q) ||
          Node.isConstructorDeclaration(q)
        )
          return false;
      return true;
    }),
  };
}
const isFn = (n) =>
  n &&
  (Node.isFunctionExpression(n) ||
    Node.isArrowFunction(n) ||
    Node.isFunctionDeclaration(n) ||
    Node.isMethodDeclaration(n));

/** Exported functions, local functions and prototype methods of one CommonJS/ES file. */
function analyse(text, file) {
  const project = new Project({ useInMemoryFileSystem: true, compilerOptions: { allowJs: true } });
  const sf = project.createSourceFile('/m/' + path.basename(file).replace(/\.\w+$/, '.js'), text);
  const locals = new Map(); // name -> fn info
  const exportsList = []; // {name, style, info}
  const methods = []; // {name, info}
  let esm = false;

  for (const fd of sf.getDescendantsOfKind(SyntaxKind.FunctionDeclaration)) {
    if (fd.getName()) locals.set(fd.getName(), fnInfo(fd));
    if (fd.isExported && fd.isExported()) {
      esm = true;
      exportsList.push({ name: fd.getName() ?? 'default', style: 'esm', info: fnInfo(fd) });
    }
  }
  for (const vd of sf.getDescendantsOfKind(SyntaxKind.VariableDeclaration)) {
    const init = vd.getInitializer();
    if (isFn(init)) locals.set(vd.getName(), fnInfo(init));
  }
  const addObjectExports = (obj) => {
    for (const p of obj.getProperties()) {
      if (Node.isPropertyAssignment(p)) {
        const init = p.getInitializer();
        if (isFn(init)) exportsList.push({ name: p.getName(), style: 'named', info: fnInfo(init) });
        else if (init && Node.isIdentifier(init) && locals.has(init.getText()))
          exportsList.push({ name: p.getName(), style: 'named', info: locals.get(init.getText()) });
      } else if (Node.isShorthandPropertyAssignment(p) && locals.has(p.getName())) {
        exportsList.push({ name: p.getName(), style: 'named', info: locals.get(p.getName()) });
      } else if (Node.isMethodDeclaration(p)) {
        exportsList.push({ name: p.getName(), style: 'method-of-export', info: fnInfo(p) });
      }
    }
  };
  for (const be of sf.getDescendantsOfKind(SyntaxKind.BinaryExpression)) {
    if (be.getOperatorToken().getKind() !== SyntaxKind.EqualsToken) continue;
    const left = be.getLeft().getText().replace(/\s/g, '');
    const right = be.getRight();
    let m;
    if ((m = /^(?:module\.)?exports\.([A-Za-z_$][\w$]*)$/.exec(left))) {
      if (isFn(right)) exportsList.push({ name: m[1], style: 'named', info: fnInfo(right) });
      else if (Node.isIdentifier(right) && locals.has(right.getText()))
        exportsList.push({ name: m[1], style: 'named', info: locals.get(right.getText()) });
    } else if (left === 'module.exports' || left === 'exports') {
      if (isFn(right))
        exportsList.push({
          name: right.getName?.() || 'module',
          style: 'module',
          info: fnInfo(right),
        });
      else if (Node.isIdentifier(right) && locals.has(right.getText()))
        exportsList.push({
          name: right.getText(),
          style: 'module',
          info: locals.get(right.getText()),
        });
      else if (Node.isObjectLiteralExpression(right)) addObjectExports(right);
    } else if ((m = /\.prototype\.([A-Za-z_$][\w$]*)$/.exec(left)) && isFn(right)) {
      methods.push({ name: m[1], info: fnInfo(right) });
    }
  }
  for (const cls of sf.getDescendantsOfKind(SyntaxKind.ClassDeclaration))
    for (const md of cls.getMethods()) methods.push({ name: md.getName(), info: fnInfo(md) });
  return { exportsList, locals, methods, esm, text };
}

function innermost(list, line) {
  return list
    .filter((x) => x.info.start <= line && line <= x.info.end)
    .sort((a, b) => a.info.end - a.info.start - (b.info.end - b.info.start))[0];
}

function screenBug(project, repo, n) {
  const buggy = `Bug-${n}`;
  const fix = `Bug-${n}-fix`;
  const row = { bug: `${project}-${n}`, project, n };
  let files;
  try {
    files = git(repo, ['diff', '--name-only', buggy, fix]).split('\n').filter(Boolean);
  } catch (e) {
    return { ...row, scope: 'out', reason: 'no fix tag' };
  }
  const prod = files.filter((f) => /\.(js|cjs|mjs)$/.test(f) && !NOT_PROD.test(f));
  row.prod_files = prod;
  if (prod.length === 0)
    return { ...row, scope: 'out', reason: 'fix changes no production JS file' };
  if (prod.length > 1)
    return { ...row, scope: 'out', reason: `fix spans ${prod.length} production files` };
  const file = prod[0];
  row.file = file;
  let text;
  try {
    text = git(repo, ['show', `${buggy}:${file}`]);
  } catch {
    return { ...row, scope: 'out', reason: 'file is new in the fix' };
  }
  const lines = changedLines(repo, buggy, fix, file);
  row.changed_lines = lines.length;
  let a;
  try {
    a = analyse(text, file);
  } catch (e) {
    return { ...row, scope: 'out', reason: 'parse error' };
  }
  if (a.esm) row.esm = true;
  const hits = new Map();
  for (const line of lines) {
    const ex = innermost(a.exportsList, line);
    if (ex) {
      hits.set(ex.name, { ...ex, via: 'direct' });
      continue;
    }
    const me = innermost(a.methods, line);
    if (me) {
      hits.set('#' + me.name, {
        name: me.name,
        style: 'prototype-method',
        info: me.info,
        via: 'method',
      });
      continue;
    }
    // inside a local helper: which exports call it?
    const local = [...a.locals.entries()]
      .filter(([, i]) => i.start <= line && line <= i.end)
      .sort((x, y) => x[1].end - x[1].start - (y[1].end - y[1].start))[0];
    if (local) {
      const callers = a.exportsList.filter((e) =>
        new RegExp(`\\b${local[0]}\\s*\\(`).test(
          a.text
            .split('\n')
            .slice(e.info.start - 1, e.info.end)
            .join('\n'),
        ),
      );
      for (const cEx of callers) hits.set(cEx.name, { ...cEx, via: `helper ${local[0]}` });
      if (!callers.length)
        hits.set('?' + local[0], {
          name: local[0],
          style: 'local-not-exported',
          info: local[1],
          via: 'local',
        });
    } else {
      hits.set('@top', { name: '(top level)', style: 'top-level', via: 'top' });
    }
  }
  const targets = [...hits.values()];
  row.targets = targets.map((t) => ({
    name: t.name,
    style: t.style,
    via: t.via,
    params: t.info?.params ?? [],
    async: t.info?.async,
  }));
  const exported = targets.filter((t) => ['named', 'module', 'esm'].includes(t.style));
  if (!exported.length) {
    const kinds = [...new Set(targets.map((t) => t.style))].join(', ');
    const why = {
      'method-of-export':
        'changed code is a method of an exported object (e.g. ESLint rule create(context))',
      'prototype-method': 'changed code is a method of a class/prototype (needs an instance)',
      'local-not-exported': 'changed code is in a function that no export calls directly',
      'top-level': 'changed code runs at module load, not inside a function',
    };
    return {
      ...row,
      scope: 'out',
      reason: why[targets[0]?.style] ?? `changed code not in an exported function (${kinds})`,
    };
  }
  if (exported.length < targets.length)
    row.note = 'some changed lines are outside the exported function';
  const hard = exported.filter((t) =>
    t.info.params.some((p) =>
      HARD_PARAM.test(
        p
          .replace(/[=:].*$/, '')
          .replace(/^\.\.\./, '')
          .trim(),
      ),
    ),
  );
  if (hard.length === exported.length)
    return {
      ...row,
      scope: 'out',
      reason: `needs inputs C3 cannot build yet (${hard[0].info.params.join(', ')})`,
    };
  const body = (t) =>
    text
      .split('\n')
      .slice(t.info.start - 1, t.info.end)
      .join('\n');
  const usesThis = exported.filter((t) => t.info.usesThis);
  if (usesThis.length === exported.length)
    return {
      ...row,
      scope: 'out',
      reason: 'function uses `this` (needs an object or framework context)',
    };
  const ctor = exported.filter((t) => /^[A-Z]/.test(t.name));
  if (ctor.length === exported.length)
    return {
      ...row,
      scope: 'out',
      reason: 'constructor or factory (test needs `new` and an instance)',
    };
  if (exported.every((t) => t.info.async))
    return {
      ...row,
      scope: 'out',
      reason: 'async function (PP1 C3 supports it, but needs mocks/await; review)',
      candidate: true,
    };
  return {
    ...row,
    scope: 'in',
    reason: 'exported function with plain-value parameters',
    functions: exported
      .filter((t) => !hard.includes(t))
      .map((t) => `${t.name}(${t.info.params.join(', ')})`),
  };
}

const rows = [];
for (const p of PROJECTS) {
  const repo = path.join(SUBJECTS, p);
  const tags = git(repo, ['tag'])
    .split('\n')
    .filter((t) => /^Bug-\d+$/.test(t))
    .map((t) => +t.slice(4))
    .sort((x, y) => x - y);
  for (const n of tags) {
    const r = screenBug(p, repo, n);
    const m = MANUAL[r.bug];
    if (m) [r.scope, r.reason] = m;
    rows.push(r);
  }
  process.stderr.write(`${p}: ${tags.length}\n`);
}
fs.writeFileSync(OUT, JSON.stringify(rows, null, 1));
if (CSV) {
  const q = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const lines = ['bug,project,scope,reason,file,function'];
  for (const r of rows)
    lines.push(
      [
        r.bug,
        r.project,
        r.scope,
        r.reason,
        r.file,
        (r.functions ?? r.targets?.map((t) => `${t.name}(${t.params.join(', ')})`) ?? []).join(
          '; ',
        ),
      ]
        .map(q)
        .join(','),
    );
  fs.writeFileSync(CSV, lines.join('\n') + '\n');
}
const by = (k) => rows.reduce((m, r) => ((m[r[k]] = (m[r[k]] ?? 0) + 1), m), {});
console.log('total', rows.length, by('scope'));
const perProject = {};
for (const r of rows) {
  perProject[r.project] ??= { total: 0, in: 0 };
  perProject[r.project].total++;
  if (r.scope === 'in') perProject[r.project].in++;
}
console.log(perProject);
const reasons = {};
for (const r of rows.filter((x) => x.scope === 'out')) {
  const k = r.reason.startsWith('manual review')
    ? 'manual review'
    : r.reason
        .replace(/\(.*\)$/, '')
        .replace(/\d+ production files/, 'N production files')
        .trim();
  reasons[k] = (reasons[k] ?? 0) + 1;
}
console.log(reasons);
