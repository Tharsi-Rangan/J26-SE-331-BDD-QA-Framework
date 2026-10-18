// Write adequacy_report.html from an existing adequacy_report.json, in the same folder.
// Usage: tsx scripts/render-html.ts <adequacy_report.json>
import fs from 'node:fs';
import path from 'node:path';
import { renderHtml } from '../src/html.js';
import type { AdequacyReport } from '../src/report.js';

const file = process.argv[2];
if (!file) {
  console.error('Usage: render-html.ts <adequacy_report.json>');
  process.exit(1);
}
const report = JSON.parse(fs.readFileSync(file, 'utf8')) as AdequacyReport;
const out = path.join(path.dirname(file), 'adequacy_report.html');
fs.writeFileSync(out, renderHtml(report));
console.log(`wrote ${out}`);
