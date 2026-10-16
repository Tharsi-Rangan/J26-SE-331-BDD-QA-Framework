// Parse one .feature file with the official Gherkin parser (C3-03).
import { AstBuilder, GherkinClassicTokenMatcher, Parser } from '@cucumber/gherkin';
import { IdGenerator } from '@cucumber/messages';
import type { ScenarioStep } from './types.js';

/** A scenario as written in the .feature file. */
export interface ParsedScenario {
  name: string;
  line: number;
  tags: string[]; // e.g. ['@SCN-EX-001-02', '@type:boundary']
  isOutline: boolean;
  steps: ScenarioStep[]; // Background steps first, then the scenario's own
  exampleHeader: string[]; // columns of the Examples table(s); every block must have the same set
  exampleRows: Record<string, string>[]; // one per Examples row, keyed by its own block's header
}

export interface ParsedFeature {
  name: string;
  tags: string[]; // e.g. ['@REQ-EX-001']
  scenarios: ParsedScenario[];
}

type MainKeyword = ScenarioStep['keyword'];

interface GherkinStep {
  keyword: string;
  keywordType?: string;
  text: string;
  location: { line: number };
}

/** Turn Gherkin steps into Given/When/Then; And/But continue the previous step type. */
function toSteps(
  steps: readonly GherkinStep[],
  start: MainKeyword | undefined,
  where: string,
): ScenarioStep[] {
  const out: ScenarioStep[] = [];
  let current = start;
  for (const s of steps) {
    const kw = s.keyword.trim();
    if (kw === 'Given' || kw === 'When' || kw === 'Then') {
      current = kw;
    } else if (kw !== 'And' && kw !== 'But' && kw !== '*') {
      throw new Error(
        `${where}:${s.location.line} unknown step keyword "${kw}" (English Gherkin only)`,
      );
    }
    if (!current) {
      throw new Error(`${where}:${s.location.line} "${kw}" step has no Given/When/Then before it`);
    }
    out.push({ keyword: current, text: s.text, line: s.location.line });
  }
  return out;
}

interface GherkinExamples {
  location: { line: number };
  tableHeader?: { cells: readonly { value: string }[] };
  tableBody: readonly { cells: readonly { value: string }[] }[];
}

/**
 * Read all Examples blocks of one Scenario Outline.
 * Each row is keyed by its OWN block's header, so a later block with reordered columns
 * still gets the right values. All blocks must have the same set of columns.
 */
function readExamples(
  examples: readonly GherkinExamples[],
  where: string,
): { header: string[]; rows: Record<string, string>[] } {
  let header: string[] = [];
  const rows: Record<string, string>[] = [];
  for (const [i, ex] of examples.entries()) {
    const cols = ex.tableHeader?.cells.map((c) => c.value) ?? [];
    if (new Set(cols).size !== cols.length) {
      throw new Error(`${where}:${ex.location.line} Examples table has a repeated column name`);
    }
    if (i === 0) {
      header = cols;
    } else if (cols.length !== header.length || cols.some((c) => !header.includes(c))) {
      throw new Error(
        `${where}:${ex.location.line} Examples columns [${cols.join(', ')}] differ from the first block [${header.join(', ')}]`,
      );
    }
    for (const row of ex.tableBody) {
      rows.push(Object.fromEntries(cols.map((c, j) => [c, row.cells[j]?.value ?? ''])));
    }
  }
  return { header, rows };
}

/** Parse .feature text. `where` (the file path) is used in error messages. */
export function parseFeature(text: string, where: string): ParsedFeature {
  let doc;
  try {
    const parser = new Parser(
      new AstBuilder(IdGenerator.incrementing()),
      new GherkinClassicTokenMatcher(),
    );
    doc = parser.parse(text);
  } catch (err) {
    throw new Error(
      `${where}: Gherkin syntax error: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
  const feature = doc.feature;
  if (!feature) throw new Error(`${where}: no Feature found`);

  const scenarios: ParsedScenario[] = [];
  const walk = (children: typeof feature.children, inherited: ScenarioStep[]) => {
    let background = inherited;
    for (const child of children) {
      if (child.background) {
        background = [...inherited, ...toSteps(child.background.steps, undefined, where)];
      } else if (child.rule) {
        walk(child.rule.children as typeof feature.children, background);
      } else if (child.scenario) {
        const sc = child.scenario;
        const lastBg = background.at(-1)?.keyword;
        const examples = sc.examples ?? [];
        const table = readExamples(examples, where);
        scenarios.push({
          name: sc.name.trim(),
          line: sc.location.line,
          tags: sc.tags.map((t) => t.name),
          isOutline: examples.length > 0,
          steps: [...background, ...toSteps(sc.steps, lastBg, where)],
          exampleHeader: table.header,
          exampleRows: table.rows,
        });
      }
    }
  };
  walk(feature.children, []);

  return { name: feature.name.trim(), tags: feature.tags.map((t) => t.name), scenarios };
}
