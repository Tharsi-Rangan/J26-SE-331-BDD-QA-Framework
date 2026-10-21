import fs from 'node:fs';
import path from 'node:path';
import type { AdequacyReport } from './report.js';

/** Escape text for HTML element content and attribute values. */
export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const e = (v: unknown) => escapeHtml(String(v ?? ''));
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
const code = (t?: string) => (t ? `<code>${e(t)}</code>` : '');
const id = (t: string) => `<span class="id">${e(t)}</span>`;
const list = (xs: string[]) =>
  xs.length ? xs.map(id).join('<br>') : '<span class="none">none</span>';
/** Escaped text where each `...` part is shown as code. */
const withCode = (t: string) => e(t).replace(/`([^`]+)`/g, '<code>$1</code>');

const STYLE = `
body{font:14px/1.45 system-ui,sans-serif;margin:24px;color:#1b1f24;max-width:1400px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}
.meta{color:#57606a;margin-bottom:16px}
.cards{display:flex;gap:12px;flex-wrap:wrap}
.card{border:1px solid #d0d7de;border-radius:6px;padding:10px 14px;min-width:110px}
.card b{display:block;font-size:22px}
table{border-collapse:collapse;width:100%}
th,td{border:1px solid #d0d7de;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f6f8fa}
code{font:12px ui-monospace,monospace;background:#f6f8fa;padding:1px 4px;border-radius:4px;white-space:pre-wrap;word-break:break-word}
.none{color:#8c959f}
.id{white-space:nowrap}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600}
.protected{background:#dafbe1;color:#116329}.at_risk{background:#fff8c5;color:#7d4e00}.unprotected{background:#ffebe9;color:#a40e26}
.C1{background:#ddf4ff;color:#0550ae}.C2{background:#fbefff;color:#6639ba}.C3{background:#fff1e5;color:#953800}
`;

function summary(r: AdequacyReport): string {
  const s = r.summary;
  const cards: [string, string][] = [
    ['Mutation score', pct(s.mutation_score)],
    ['Filtered score', pct(s.mutation_score_filtered)],
    ['Mutants', String(s.mutants_total)],
    ['Killed', String(s.killed)],
    ['Survived', String(s.survived)],
    ['No coverage', String(s.no_coverage)],
    ['Timeout', String(s.timeout)],
    ['Equivalent', String(s.equivalent_filtered)],
  ];
  return `<div class="cards">${cards.map(([k, v]) => `<div class="card">${e(k)}<b>${e(v)}</b></div>`).join('')}</div>`;
}

function requirements(r: AdequacyReport): string {
  const rows = r.requirements.map(
    (q) =>
      `<tr><td>${id(q.requirement_id)}</td><td><span class="tag ${e(q.status)}">${e(q.status)}</span></td>` +
      `<td>${pct(q.score)}</td><td>${q.killed}</td><td>${q.survived}</td><td>${q.mutants_traced}</td></tr>`,
  );
  return `<table><tr><th>Requirement</th><th>Status</th><th>Score</th><th>Killed</th><th>Survived</th><th>Mutants traced</th></tr>${rows.join('')}</table>`;
}

function recommendations(r: AdequacyReport): string {
  if (r.recommendations.length === 0) return '<p class="none">No recommendations.</p>';
  const rows = r.recommendations.map((c) => {
    const t = c.target;
    return (
      `<tr><td>${c.rank}</td><td>${id(c.rec_id)}</td><td><span class="tag ${e(c.route_to)}">${e(c.route_to)}</span></td>` +
      `<td>${e(c.gap_type)}</td><td>${list([t.requirement_id, t.scenario_id, t.test_id].filter((x): x is string => !!x))}</td>` +
      `<td>${e(c.mutant_ids.join(', '))}</td><td>+${e(c.predicted_impact)}</td><td>${withCode(c.action)}</td><td>${e(c.status)}</td></tr>`
    );
  });
  return `<table><tr><th>Rank</th><th>ID</th><th>Route</th><th>Gap type</th><th>Target</th><th>Mutants</th><th>Predicted impact</th><th>Action</th><th>Status</th></tr>${rows.join('')}</table>`;
}

function survivors(r: AdequacyReport): string {
  if (r.survivors.length === 0) return '<p class="none">No surviving mutants.</p>';
  const rows = r.survivors.map((s) => {
    const t = s.trace;
    const conf = t.confidence !== undefined ? ` (${t.confidence})` : '';
    const gap = s.equivalent
      ? '<span class="none">equivalent</span>'
      : s.gap
        ? `<b>${e(s.gap.type)}</b><br>${code(s.gap.evidence)}<br>${e(s.gap.explanation)}`
        : '<span class="none">none</span>';
    return (
      `<tr><td>${e(s.mutant_id)}</td><td>${e(s.status)}</td><td>${e(s.file)}:${s.location.start.line}:${s.location.start.column}</td>` +
      `<td>${e(s.mutator)}<br>${code(s.replacement)}</td><td>${list(t.test_ids)}</td><td>${list(t.scenario_ids)}</td>` +
      `<td>${list(t.requirement_ids)}</td><td>${e(t.signal)}${e(conf)}</td><td>${gap}</td></tr>`
    );
  });
  return `<table><tr><th>Mutant</th><th>Status</th><th>Location</th><th>Mutator</th><th>Tests</th><th>Scenarios</th><th>Requirements</th><th>Signal</th><th>Gap</th></tr>${rows.join('')}</table>`;
}

/** The adequacy report as one self-contained HTML page. */
export function renderHtml(r: AdequacyReport): string {
  const c = r.config;
  const meta = [
    `Run ${r.run_id}`,
    `subject ${r.subject_id}`,
    `trace signal ${c.trace_signal}${c.embedding_model ? ` (${c.embedding_model})` : ''}`,
    `StrykerJS ${c.stryker_version}`,
    `generated ${r.generated_at}`,
  ].join(' · ');
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>C4 adequacy report: ${e(r.subject_id)}</title><style>${STYLE}</style></head>
<body>
<h1>C4 adequacy report: ${e(r.subject_id)}</h1>
<div class="meta">${e(meta)}<br>Mutated: ${e((c.mutate ?? []).join(', '))}</div>
${summary(r)}
<h2>Requirements (${r.requirements.length})</h2>
${requirements(r)}
<h2>Recommendations (${r.recommendations.length})</h2>
${recommendations(r)}
<h2>Surviving mutants (${r.survivors.length})</h2>
${survivors(r)}
</body></html>
`;
}

/** Write `c4/adequacy_report.html` next to the JSON report. */
export function writeHtml(report: AdequacyReport, outDir: string): string {
  const file = path.join(outDir, 'c4', 'adequacy_report.html');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, renderHtml(report));
  return file;
}
