import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, test } from 'vitest';
import { escapeHtml, renderHtml, writeHtml } from '../src/html.js';
import type { AdequacyReport } from '../src/report.js';

const golden = path.resolve(
  import.meta.dirname,
  '../../contracts/fixtures/golden/example-registration/c4/adequacy_report.json',
);
const report = JSON.parse(fs.readFileSync(golden, 'utf8')) as AdequacyReport;

describe('c4 HTML view', () => {
  test('escapeHtml escapes the 5 special characters', () => {
    expect(escapeHtml(`<a href="x">'&'</a>`)).toBe(
      '&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;',
    );
  });

  test('the golden report shows summary, requirements, recommendations and survivors', () => {
    const html = renderHtml(report);
    expect(html).toContain('<h1>C4 adequacy report: SUB-EX-1</h1>');
    expect(html).toContain('Mutation score<b>92.9%</b>');
    expect(html).toContain('<span class="tag at_risk">at_risk</span>');
    expect(html).toContain('<h2>Recommendations (1)</h2>');
    expect(html).toContain('<span class="tag C3">C3</span>');
    expect(html).toContain('<h2>Surviving mutants (1)</h2>');
    expect(html).toContain(
      '<span class="id">TST-EX-001-02-01</span><br><span class="id">TST-EX-001-02-06</span>',
    );
    expect(html).toContain('<b>weak_assertion</b>');
  });

  test('an action shows its backtick parts as code', () => {
    const html = renderHtml({
      ...report,
      recommendations: [{ ...report.recommendations[0], action: 'Check `a < b` here.' }],
    });
    expect(html).toContain('Check <code>a &lt; b</code> here.');
  });

  test('code and text from the report are escaped', () => {
    const html = renderHtml(report);
    expect(html).toContain('toThrow(ValidationError);');
    expect(html).toContain('<code>&quot;&quot;</code>');
    const bad = { ...report, subject_id: '<script>alert(1)</script>' };
    expect(renderHtml(bad)).not.toContain('<script>');
  });

  test('a report with no survivors and no recommendations says so', () => {
    const html = renderHtml({ ...report, survivors: [], recommendations: [] });
    expect(html).toContain('No surviving mutants.');
    expect(html).toContain('No recommendations.');
  });

  test('writeHtml writes c4/adequacy_report.html', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'c4-html-'));
    try {
      const file = writeHtml(report, dir);
      expect(file).toBe(path.join(dir, 'c4', 'adequacy_report.html'));
      expect(fs.readFileSync(file, 'utf8')).toMatch(/^<!doctype html>/);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
