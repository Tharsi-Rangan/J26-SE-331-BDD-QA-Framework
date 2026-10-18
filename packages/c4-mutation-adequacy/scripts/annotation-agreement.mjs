#!/usr/bin/env node
// Compare 2 label files from docs/trace-annotation-guideline.md.
// Usage: node scripts/annotation-agreement.mjs <labels-a.json> <labels-b.json> [--md <out.md>]
import fs from 'node:fs';
import path from 'node:path';

const [fileA, fileB, ...rest] = process.argv.slice(2);
if (!fileA || !fileB) {
  console.error('Usage: annotation-agreement.mjs <labels-a.json> <labels-b.json> [--md <out.md>]');
  process.exit(1);
}
const mdOut = rest[0] === '--md' ? rest[1] : undefined;
const read = (f) => JSON.parse(fs.readFileSync(f, 'utf8'));
const a = new Map(read(fileA).map((l) => [l.mutant_id, l]));
const b = new Map(read(fileB).map((l) => [l.mutant_id, l]));
const ids = [...a.keys()].filter((id) => b.has(id));
const missing = [...a.keys(), ...b.keys()].filter((id) => !(a.has(id) && b.has(id)));

const round = (x) => Math.round(x * 1000) / 1000;
const testKey = (l) => [...(l.test_ids ?? [])].sort().join(',');

/** Percent agreement and Cohen's kappa for one nominal field. */
function agreement(get) {
  const n = ids.length;
  const pairs = ids.map((id) => [get(a.get(id)), get(b.get(id))]);
  const po = pairs.filter(([x, y]) => x === y).length / n;
  const cats = new Set(pairs.flat());
  let pe = 0;
  for (const c of cats)
    pe +=
      (pairs.filter(([x]) => x === c).length / n) * (pairs.filter(([, y]) => y === c).length / n);
  return { agree: round(po), kappa: pe === 1 ? 1 : round((po - pe) / (1 - pe)) };
}

const fields = {
  requirement_id: (l) => l.requirement_id,
  scenario_id: (l) => l.scenario_id,
  test_ids: testKey,
  gap_type: (l) => l.gap_type,
};
const results = Object.fromEntries(Object.entries(fields).map(([k, g]) => [k, agreement(g)]));
const disagreements = ids.filter((id) =>
  Object.values(fields).some((g) => g(a.get(id)) !== g(b.get(id))),
);

const nameA = path.basename(fileA, '.json');
const nameB = path.basename(fileB, '.json');
const md = [
  `# Annotation agreement: ${nameA} vs ${nameB}`,
  '',
  `Survivors labelled by both: ${ids.length}.` +
    (missing.length ? ` Missing in one file: ${missing.join(', ')}.` : ''),
  '',
  '| Field | Agreement | Cohen kappa |',
  '|---|---|---|',
  ...Object.entries(results).map(([k, r]) => `| \`${k}\` | ${r.agree} | ${r.kappa} |`),
  '',
  `## Disagreements (${disagreements.length})`,
  '',
  `| Mutant | Field | ${nameA} | ${nameB} |`,
  '|---|---|---|---|',
  ...disagreements.flatMap((id) =>
    Object.entries(fields)
      .filter(([, g]) => g(a.get(id)) !== g(b.get(id)))
      .map(([k, g]) => `| ${id} | \`${k}\` | ${g(a.get(id)) || '-'} | ${g(b.get(id)) || '-'} |`),
  ),
  '',
].join('\n');

console.log(md);
if (mdOut) fs.writeFileSync(mdOut, md);
