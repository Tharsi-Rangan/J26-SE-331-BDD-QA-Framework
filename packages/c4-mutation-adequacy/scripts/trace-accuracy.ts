// Compare a C4 report with a ground truth.
// Usage: tsx scripts/trace-accuracy.ts <adequacy_report.json> <ground-truth.json> [--md <out.md>] [--title <text>]
import fs from 'node:fs';
import { parseArgs } from 'node:util';
import { accuracyMarkdown, traceAccuracy, type TruthLabel } from '../src/accuracy.js';
import type { AdequacyReport } from '../src/report.js';

const { positionals, values } = parseArgs({
  allowPositionals: true,
  options: { md: { type: 'string' }, title: { type: 'string' } },
});
const [reportFile, truthFile] = positionals;
if (!reportFile || !truthFile) {
  console.error(
    'Usage: trace-accuracy.ts <adequacy_report.json> <ground-truth.json> [--md <out.md>]',
  );
  process.exit(1);
}
const read = <T>(f: string) => JSON.parse(fs.readFileSync(f, 'utf8')) as T;
const report = read<AdequacyReport>(reportFile);
const result = traceAccuracy(report.survivors, read<TruthLabel[]>(truthFile));
const md = accuracyMarkdown(
  result,
  values.title ?? `C4 trace accuracy (${report.subject_id}, ${report.config.trace_signal})`,
);
console.log(md);
if (result.unmatched.survivors.length || result.unmatched.labels.length)
  console.warn(
    `warning: survivors with no label: ${result.unmatched.survivors.join(', ') || 'none'}; labels with no survivor: ${result.unmatched.labels.join(', ') || 'none'}`,
  );
if (values.md) fs.writeFileSync(values.md, md);
