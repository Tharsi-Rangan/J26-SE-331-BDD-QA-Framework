import type { ManifestTest, MutationReport } from './types.js';

/** Map StrykerJS test id -> manifest test, joined on the exact Jest full name. */
export function testsByStrykerId(
  report: MutationReport,
  tests: ManifestTest[],
): Map<string, ManifestTest> {
  const byName = new Map(tests.map((t) => [t.jest_full_name, t]));
  const out = new Map<string, ManifestTest>();
  for (const file of Object.values(report.testFiles ?? {})) {
    for (const t of file.tests) {
      const m = byName.get(t.name);
      if (m) out.set(t.id, m);
    }
  }
  return out;
}
