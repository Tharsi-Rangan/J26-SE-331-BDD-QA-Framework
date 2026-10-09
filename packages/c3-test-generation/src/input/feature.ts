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
  exampleHeader: string[];
  exampleRows: string[][];
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
        scenarios.push({
          name: sc.name.trim(),
          line: sc.location.line,
          tags: sc.tags.map((t) => t.name),
          isOutline: examples.length > 0,
          steps: [...background, ...toSteps(sc.steps, lastBg, where)],
          exampleHeader: examples[0]?.tableHeader?.cells.map((c) => c.value) ?? [],
          exampleRows: examples.flatMap((ex) =>
            ex.tableBody.map((row) => row.cells.map((c) => c.value)),
          ),
        });
      }
    }
  };
  walk(feature.children, []);

  return { name: feature.name.trim(), tags: feature.tags.map((t) => t.name), scenarios };
}
