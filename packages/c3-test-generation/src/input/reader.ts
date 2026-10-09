// C3-03 input reader (FR1).
// Reads a run folder: subject-manifest.json + c2/scenario_metadata.json + c2/features/*.feature,
// joins scenario -> requirement -> subject, and keeps only scenarios C2 fully verified.
import fs from 'node:fs';
import path from 'node:path';
import { parseFeature, type ParsedFeature, type ParsedScenario } from './feature.js';
import type {
  C2ScenarioMeta,
  C3Inputs,
  C3ScenarioInput,
  ExampleRow,
  SkippedScenario,
  SubjectRef,
} from './types.js';

/** Thrown when the inputs are missing or do not agree. Lists every problem found, not just the first. */
export class C3InputError extends Error {
  constructor(public readonly problems: string[]) {
    super(`C3 input problems (${problems.length}):\n  - ${problems.join('\n  - ')}`);
    this.name = 'C3InputError';
  }
}

const METADATA = 'c2/scenario_metadata.json';
const MANIFEST = 'subject-manifest.json';

function readJson(inDir: string, rel: string): any {
  const file = path.join(inDir, rel);
  if (!fs.existsSync(file)) throw new C3InputError([`missing ${rel} in ${inDir}`]);
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (err) {
    throw new C3InputError([
      `${rel} is not valid JSON: ${err instanceof Error ? err.message : String(err)}`,
    ]);
  }
}

function need(obj: any, field: string, where: string, problems: string[]): void {
  if (obj?.[field] === undefined || obj?.[field] === null)
    problems.push(`${where}: missing required field "${field}"`);
}

/** Tags on a scenario that start with `prefix`, with the prefix removed ('@type:boundary' -> 'boundary'). */
function tagValue(sc: ParsedScenario, prefix: string): string[] {
  return sc.tags.filter((t) => t.startsWith(prefix)).map((t) => t.slice(prefix.length));
}

function failedChecks(v: C2ScenarioMeta['verification']): string[] {
  return Object.entries(v)
    .filter(
      ([, st]) =>
        st === 'fail' ||
        (typeof st === 'object' && st !== null && (st as { status?: string }).status === 'fail'),
    )
    .map(([k]) => k);
}

/**
 * Read and join C3's inputs from a run folder (or a golden fixture folder).
 * Throws C3InputError if files are missing or the files disagree with each other.
 */
export function readC3Inputs(inDir: string): C3Inputs {
  const meta = readJson(inDir, METADATA);
  const manifest = readJson(inDir, MANIFEST);
  const problems: string[] = [];

  need(meta, 'run_id', METADATA, problems);
  need(meta, 'scenarios', METADATA, problems);
  need(manifest, 'subjects', MANIFEST, problems);
  if (problems.length) throw new C3InputError(problems);

  // requirement_id -> subject
  const subjectOf = new Map<string, SubjectRef>();
  for (const s of manifest.subjects as any[]) {
    for (const reqId of s.requirement_ids ?? []) {
      if (subjectOf.has(reqId))
        problems.push(`${MANIFEST}: ${reqId} is listed under more than one subject`);
      subjectOf.set(reqId, {
        subjectId: s.subject_id,
        projectCode: s.project_code,
        modulePath: s.module_path,
        exports: s.exports ?? [],
        moduleSystem: s.module_system,
        source: s.source ?? {},
      });
    }
  }

  // Parse each feature file once.
  const features = new Map<string, ParsedFeature>();
  const scenariosMeta = meta.scenarios as C2ScenarioMeta[];
  for (const featureFile of new Set(scenariosMeta.map((s) => s.feature_file))) {
    const file = path.join(inDir, featureFile);
    if (!fs.existsSync(file)) {
      problems.push(`missing feature file ${featureFile}`);
      continue;
    }
    try {
      features.set(featureFile, parseFeature(fs.readFileSync(file, 'utf8'), featureFile));
    } catch (err) {
      problems.push(err instanceof Error ? err.message : String(err));
    }
  }

  // Every scenario in a .feature file must have exactly one @SCN tag and appear in the metadata.
  const metaIds = new Set(scenariosMeta.map((s) => s.scenario_id));
  for (const [featureFile, f] of features) {
    for (const sc of f.scenarios) {
      const ids = tagValue(sc, '@');
      const scn = ids.filter((t) => t.startsWith('SCN-'));
      if (scn.length !== 1)
        problems.push(
          `${featureFile}:${sc.line} scenario "${sc.name}" needs exactly one @SCN-... tag`,
        );
      else if (!metaIds.has(scn[0]!))
        problems.push(`${featureFile}:${sc.line} ${scn[0]} is not in ${METADATA}`);
    }
  }

  const scenarios: C3ScenarioInput[] = [];
  const skipped: SkippedScenario[] = [];
  for (const m of scenariosMeta) {
    const where = `${METADATA} ${m.scenario_id ?? '(no scenario_id)'}`;
    for (const field of [
      'scenario_id',
      'requirement_id',
      'feature_file',
      'scenario_name',
      'scenario_type',
      'is_outline',
      'verification',
    ]) {
      need(m, field, where, problems);
    }
    if (!m.verification || !m.scenario_id) continue;

    if (!m.verification.fully_verified) {
      const failed = failedChecks(m.verification);
      skipped.push({
        scenarioId: m.scenario_id,
        requirementId: m.requirement_id,
        reason: `not fully verified by C2${failed.length ? ` (failed: ${failed.join(', ')})` : ''}`,
      });
      continue;
    }

    const f = features.get(m.feature_file);
    if (!f) continue; // already reported as missing/unparsable
    const sc = f.scenarios.find((s) => tagValue(s, '@').includes(m.scenario_id));
    if (!sc) {
      problems.push(`${where}: not found in ${m.feature_file}`);
      continue;
    }
    if (sc.name !== m.scenario_name)
      problems.push(
        `${where}: scenario_name "${m.scenario_name}" but the .feature title is "${sc.name}"`,
      );
    const types = tagValue(sc, '@type:');
    if (types.length !== 1 || types[0] !== m.scenario_type) {
      problems.push(
        `${where}: scenario_type "${m.scenario_type}" but the .feature has @type:${types.join(',') || '(none)'}`,
      );
    }
    if (sc.isOutline !== m.is_outline)
      problems.push(
        `${where}: is_outline=${m.is_outline} but the .feature says ${sc.isOutline ? 'Scenario Outline' : 'Scenario'}`,
      );

    const subject = subjectOf.get(m.requirement_id);
    if (!subject) {
      problems.push(`${where}: requirement ${m.requirement_id} has no subject in ${MANIFEST}`);
      continue;
    }

    const metaRows = m.examples ?? [];
    if (sc.isOutline && metaRows.length && metaRows.length !== sc.exampleRows.length) {
      problems.push(
        `${where}: metadata has ${metaRows.length} examples but the .feature has ${sc.exampleRows.length} rows`,
      );
    }
    const examples: ExampleRow[] = sc.exampleRows.map((cells, i) => {
      const values = Object.fromEntries(sc.exampleHeader.map((h, j) => [h, cells[j] ?? '']));
      const linked = metaRows.find((r) => r.row_index === i + 1);
      return {
        rowIndex: i + 1,
        values,
        ...(linked?.boundary_ref ? { boundaryRef: linked.boundary_ref } : {}),
        ...(linked?.partition_ref ? { partitionRef: linked.partition_ref } : {}),
      };
    });

    scenarios.push({
      scenarioId: m.scenario_id,
      requirementId: m.requirement_id,
      scenarioName: m.scenario_name,
      scenarioType: m.scenario_type,
      isOutline: m.is_outline,
      featureFile: m.feature_file,
      line: sc.line,
      steps: sc.steps,
      examples,
      metadata: m,
      subject,
    });
  }

  if (problems.length) throw new C3InputError(problems);
  return { runId: meta.run_id, inDir, scenarios, skipped };
}
