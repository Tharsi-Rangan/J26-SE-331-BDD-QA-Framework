#!/usr/bin/env node
// Validate one run folder (or fixture folder) against the shared contracts.
// Usage: node scripts/validate.mjs <folder> [<folder> ...]
// Exit code 1 if anything fails, so CI blocks the PR.
//
// Two kinds of checks:
//   1. Schema checks  - each file matches its JSON Schema.
//   2. Link checks    - IDs agree ACROSS files (the bugs that schemas alone cannot catch).
//
// Added after the SH-04 review, before the v1.0.0 freeze (stricter link checks only, no schema change):
//   - .feature @type: tag must equal scenario_type
//   - fully_verified = true is not allowed when one of C2's 5 checks failed
//   - C3 stubs are checked like tests (scenario, ID, file)
//   - confidence report: route <-> test_ids/stub_id, route <-> threshold, route <-> C2 fully_verified,
//     IDs belong to the same scenario, nothing in the manifest is missing from the report

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import { AstBuilder, GherkinClassicTokenMatcher, Parser } from '@cucumber/gherkin';
import { IdGenerator } from '@cucumber/messages';

const here = path.dirname(fileURLToPath(import.meta.url));
const schemaDir = path.join(here, '..', 'schemas');

const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);
for (const f of fs.readdirSync(schemaDir).filter((n) => n.endsWith('.schema.json'))) {
  ajv.addSchema(JSON.parse(fs.readFileSync(path.join(schemaDir, f), 'utf8')), f);
}

// file name inside a run folder -> schema
const FILES = {
  'subject-manifest.json': 'subject-manifest.schema.json',
  'c1/validated_requirements.json': 'c1-validated-requirements.schema.json',
  'c2/scenario_metadata.json': 'c2-scenario-metadata.schema.json',
  'c3/test_manifest.json': 'c3-test-manifest.schema.json',
  'c3/mock_decisions.json': 'c3-mock-decisions.schema.json',
  'c3/generation_confidence_report.json': 'c3-confidence-report.schema.json',
  'c4/adequacy_report.json': 'c4-adequacy-report.schema.json',
};

let failures = 0;
const fail = (msg) => { failures++; console.error('  FAIL ' + msg); };
const ok = (msg) => console.log('  ok   ' + msg);
let mark = 0;
const start = () => { mark = failures; };
const done = (msg) => { if (failures === mark) ok(msg); };

function load(root, rel) {
  const p = path.join(root, rel);
  return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : null;
}

function parseFeature(file) {
  const parser = new Parser(new AstBuilder(IdGenerator.uuid()), new GherkinClassicTokenMatcher());
  return parser.parse(fs.readFileSync(file, 'utf8'));
}

for (const root of process.argv.slice(2)) {
  console.log(`\n== ${root}`);
  const docs = {};

  // 1. Schema checks
  for (const [rel, schema] of Object.entries(FILES)) {
    const data = load(root, rel);
    if (!data) { console.log(`  skip ${rel} (not present)`); continue; }
    docs[rel] = data;
    const validate = ajv.getSchema(schema);
    if (validate(data)) ok(`${rel} matches ${schema}`);
    else for (const e of validate.errors) fail(`${rel} ${e.instancePath || '/'} ${e.message}`);
  }

  // 2. Link checks
  const c1 = docs['c1/validated_requirements.json'];
  const c2 = docs['c2/scenario_metadata.json'];
  const c3 = docs['c3/test_manifest.json'];
  const md = docs['c3/mock_decisions.json'];
  const cr = docs['c3/generation_confidence_report.json'];
  const c4 = docs['c4/adequacy_report.json'];
  const sm = docs['subject-manifest.json'];

  const reqIds = new Set(c1?.requirements.map((r) => r.requirement_id) ?? []);
  const scn = new Map(c2?.scenarios.map((s) => [s.scenario_id, s]) ?? []);
  const testIds = new Set(c3?.tests.map((t) => t.test_id) ?? []);

  // run_id must be the same in every stage of one run
  const runIds = new Set(Object.values(docs).map((d) => d.run_id).filter(Boolean));
  start();
  if (runIds.size > 1) fail(`different run_id values in one folder: ${[...runIds].join(', ')}`);

  start();
  if (c1) {
    const dup = c1.requirements.map((r) => r.requirement_id).filter((id, i, a) => a.indexOf(id) !== i);
    dup.length ? fail(`C1 duplicate requirement_id: ${dup}`) : done('C1 requirement IDs unique');
  }

  start();
  if (c1 && c2) {
    for (const s of c2.scenarios) {
      const r = c1.requirements.find((x) => x.requirement_id === s.requirement_id);
      if (!r) fail(`C2 ${s.scenario_id} points to unknown ${s.requirement_id}`);
      else if (!r.bdd_ready) fail(`C2 ${s.scenario_id} built from ${s.requirement_id} which is NOT bdd_ready`);
      if (!s.scenario_id.startsWith('SCN-' + s.requirement_id.slice(4) + '-'))
        fail(`C2 ${s.scenario_id} does not embed its requirement number ${s.requirement_id}`);
    }
    done('C2 -> C1 requirement links checked');
  }

  start();
  if (c2) {
    // .feature tags and names must match the metadata
    for (const f of c2.features) {
      const file = path.join(root, f.feature_file);
      if (!fs.existsSync(file)) { fail(`missing feature file ${f.feature_file}`); continue; }
      let doc;
      try { doc = parseFeature(file); } catch (e) { fail(`${f.feature_file} is not valid Gherkin: ${e.message}`); continue; }
      const feat = doc.feature;
      if (!feat.tags.some((t) => t.name === '@' + f.requirement_id)) fail(`${f.feature_file} missing feature tag @${f.requirement_id}`);
      for (const child of feat.children.filter((c) => c.scenario)) {
        const sc = child.scenario;
        const tag = sc.tags.map((t) => t.name.slice(1)).find((t) => t.startsWith('SCN-'));
        if (!tag) { fail(`${f.feature_file}: scenario "${sc.name}" has no @SCN- tag`); continue; }
        const meta = scn.get(tag);
        if (!meta) { fail(`${f.feature_file}: @${tag} not in scenario_metadata.json`); continue; }
        if (meta.scenario_name !== sc.name) fail(`${tag}: name in metadata "${meta.scenario_name}" != feature "${sc.name}"`);
        // [SH-04] exactly one @type:<...> tag, and it must equal scenario_type in the metadata
        const types = sc.tags.map((t) => t.name).filter((t) => t.startsWith('@type:')).map((t) => t.slice(6));
        if (types.length !== 1) fail(`${tag}: needs exactly one @type: tag, found ${types.length}`);
        else if (types[0] !== meta.scenario_type) fail(`${tag}: tag @type:${types[0]} != scenario_type "${meta.scenario_type}" in metadata`);
        if (meta.is_outline !== sc.examples.length > 0) fail(`${tag}: is_outline does not match the .feature file`);
        const rows = sc.examples.reduce((n, e) => n + e.tableBody.length, 0);
        if (meta.is_outline && (meta.examples?.length ?? 0) !== rows) fail(`${tag}: ${rows} Examples rows in feature but ${meta.examples?.length ?? 0} in metadata`);
      }
    }
    done('C2 .feature files <-> metadata checked');
  }

  // [SH-04] fully_verified = true is only allowed when none of the 5 checks failed
  // ("skipped" is fine, e.g. bva_coverage on a positive scenario with no boundaries).
  start();
  if (c2) {
    for (const s of c2.scenarios) {
      const v = s.verification;
      const checks = {
        syntax: v.syntax,
        requirement_consistency: v.requirement_consistency?.status,
        ep_coverage: v.ep_coverage,
        bva_coverage: v.bva_coverage,
        completeness: v.completeness,
      };
      const failed = Object.entries(checks).filter(([, st]) => st === 'fail').map(([k]) => k);
      if (v.fully_verified && failed.length) fail(`C2 ${s.scenario_id} is fully_verified but these checks failed: ${failed.join(', ')}`);
    }
    done('C2 fully_verified agrees with its 5 checks');
  }

  start();
  if (c2 && c3) {
    for (const t of c3.tests) {
      const s = scn.get(t.scenario_id);
      if (!s) fail(`C3 ${t.test_id} points to unknown ${t.scenario_id}`);
      else {
        if (!s.verification.fully_verified) fail(`C3 ${t.test_id} built from NOT fully verified ${t.scenario_id}`);
        if (s.requirement_id !== t.requirement_id) fail(`C3 ${t.test_id} requirement ${t.requirement_id} != scenario's ${s.requirement_id}`);
      }
      if (!t.test_id.startsWith('TST-' + t.scenario_id.slice(4) + '-')) fail(`C3 ${t.test_id} does not embed ${t.scenario_id}`);
      if (!t.jest_full_name.includes(`[${t.scenario_id}][${t.test_id}]`)) fail(`C3 ${t.test_id} jest_full_name missing [${t.scenario_id}][${t.test_id}]`);
      if (!t.jest_full_name.startsWith(`[${t.requirement_id}] `)) fail(`C3 ${t.test_id} jest_full_name must start with [${t.requirement_id}]`);
      if (!fs.existsSync(path.join(root, t.file))) fail(`C3 ${t.test_id} file not found: ${t.file}`);
    }
    const dup = c3.tests.map((t) => t.test_id).filter((id, i, a) => a.indexOf(id) !== i);
    dup.length ? fail(`C3 duplicate test_id: ${dup}`) : done('C3 -> C2 links and Jest names checked');
  }

  // [SH-04] stubs follow the same rules as tests: known, fully verified scenario; ID embeds it; file exists
  start();
  if (c3) {
    for (const st of c3.stubs) {
      if (st.stub_id !== 'STB-' + st.scenario_id.slice(4)) fail(`C3 ${st.stub_id} does not match its scenario ${st.scenario_id}`);
      if (!fs.existsSync(path.join(root, st.file))) fail(`C3 ${st.stub_id} file not found: ${st.file}`);
      if (c2) {
        const s = scn.get(st.scenario_id);
        if (!s) fail(`C3 ${st.stub_id} points to unknown ${st.scenario_id}`);
        else {
          if (!s.verification.fully_verified) fail(`C3 ${st.stub_id} built from NOT fully verified ${st.scenario_id}`);
          if (s.requirement_id !== st.requirement_id) fail(`C3 ${st.stub_id} requirement ${st.requirement_id} != scenario's ${s.requirement_id}`);
        }
      }
    }
    const dup = c3.stubs.map((s) => s.stub_id).filter((id, i, a) => a.indexOf(id) !== i);
    if (dup.length) fail(`C3 duplicate stub_id: ${dup}`);
    done('C3 stubs checked');
  }

  start();
  if (c3 && md) {
    const mdIds = new Set(md.decisions.map((d) => d.decision_id));
    for (const t of c3.tests) for (const id of t.mock_decision_ids ?? []) if (!mdIds.has(id)) fail(`C3 ${t.test_id} uses unknown ${id}`);
    for (const d of md.decisions) if (d.decision === 'mock' && !d.behaviour) fail(`${d.decision_id} is 'mock' but has no behaviour`);
    done('C3 mock decision links checked');
  }

  // [SH-04] confidence report: each route has what it needs, routes follow the threshold (SO5),
  // and every ID points to a real test/stub of the SAME scenario.
  start();
  if (cr) {
    const th = cr.formula.threshold;
    for (const s of cr.scenarios) {
      const id = s.scenario_id;
      const nTests = s.test_ids?.length ?? 0;
      if (s.route === 'runnable') {
        if (nTests === 0) fail(`confidence report ${id}: route "runnable" but no test_ids`);
        if (s.stub_id) fail(`confidence report ${id}: route "runnable" must not have a stub_id`);
        if (s.confidence < th) fail(`confidence report ${id}: confidence ${s.confidence} < threshold ${th} but route is "runnable" (should be "stub")`);
      } else if (s.route === 'stub') {
        if (!s.stub_id) fail(`confidence report ${id}: route "stub" but no stub_id`);
        if (nTests) fail(`confidence report ${id}: route "stub" must not list test_ids`);
        if (s.confidence >= th) fail(`confidence report ${id}: confidence ${s.confidence} >= threshold ${th} but route is "stub" (should be "runnable")`);
      } else if (s.route === 'skipped_not_verified') {
        if (nTests || s.stub_id) fail(`confidence report ${id}: route "skipped_not_verified" must not have test_ids or stub_id`);
      }
    }
    const dup = cr.scenarios.map((s) => s.scenario_id).filter((x, i, a) => a.indexOf(x) !== i);
    if (dup.length) fail(`confidence report lists a scenario more than once: ${dup}`);

    if (c3) {
      const testById = new Map(c3.tests.map((t) => [t.test_id, t]));
      const stubById = new Map(c3.stubs.map((st) => [st.stub_id, st]));
      for (const s of cr.scenarios) {
        for (const tid of s.test_ids ?? []) {
          const t = testById.get(tid);
          if (!t) fail(`confidence report lists unknown ${tid}`);
          else if (t.scenario_id !== s.scenario_id) fail(`confidence report puts ${tid} under ${s.scenario_id}, but the test belongs to ${t.scenario_id}`);
        }
        if (s.stub_id) {
          const st = stubById.get(s.stub_id);
          if (!st) fail(`confidence report lists ${s.stub_id}, which is not in test_manifest.stubs`);
          else if (st.scenario_id !== s.scenario_id) fail(`confidence report puts ${s.stub_id} under ${s.scenario_id}, but the stub belongs to ${st.scenario_id}`);
        }
      }
      // nothing in the manifest may be missing from the report
      const listedTests = new Set(cr.scenarios.flatMap((s) => s.test_ids ?? []));
      const listedStubs = new Set(cr.scenarios.map((s) => s.stub_id).filter(Boolean));
      for (const t of c3.tests) if (!listedTests.has(t.test_id)) fail(`${t.test_id} is in test_manifest but not in the confidence report`);
      for (const st of c3.stubs) if (!listedStubs.has(st.stub_id)) fail(`${st.stub_id} is in test_manifest.stubs but not in the confidence report`);
    }

    if (c2) {
      // one entry per scenario C3 received; "skipped_not_verified" exactly when C2 did not fully verify it
      const crIds = new Set(cr.scenarios.map((s) => s.scenario_id));
      for (const s of c2.scenarios) if (!crIds.has(s.scenario_id)) fail(`confidence report has no entry for ${s.scenario_id}`);
      for (const s of cr.scenarios) {
        const m = scn.get(s.scenario_id);
        if (!m) { fail(`confidence report lists unknown ${s.scenario_id}`); continue; }
        const skipped = s.route === 'skipped_not_verified';
        if (skipped && m.verification.fully_verified) fail(`confidence report ${s.scenario_id}: "skipped_not_verified" but C2 marked it fully_verified`);
        if (!skipped && !m.verification.fully_verified) fail(`confidence report ${s.scenario_id}: route "${s.route}" but C2 did NOT fully verify it`);
        if (s.requirement_id !== m.requirement_id) fail(`confidence report ${s.scenario_id}: requirement ${s.requirement_id} != scenario's ${m.requirement_id}`);
      }
    }
    done('C3 confidence report routes and links checked');
  }

  start();
  if (c4) {
    for (const m of c4.survivors) {
      for (const id of m.trace.test_ids) if (c3 && !testIds.has(id)) fail(`C4 mutant ${m.mutant_id} traces to unknown ${id}`);
      for (const id of m.trace.scenario_ids) if (c2 && !scn.has(id)) fail(`C4 mutant ${m.mutant_id} traces to unknown ${id}`);
      for (const id of m.trace.requirement_ids) if (c1 && !reqIds.has(id)) fail(`C4 mutant ${m.mutant_id} traces to unknown ${id}`);
    }
    const s = c4.summary;
    if (s.killed + s.survived + s.no_coverage + s.timeout > s.mutants_total) fail('C4 summary counts add up to more than mutants_total');
    done('C4 trace links checked');
  }

  start();
  if (sm && c1) {
    for (const sub of sm.subjects) for (const id of sub.requirement_ids) if (!reqIds.has(id)) fail(`subject ${sub.subject_id} lists ${id} which C1 did not produce`);
    done('subject manifest -> C1 links checked');
  }
}

console.log(failures ? `\n${failures} problem(s) found.` : '\nAll contract checks passed.');
process.exit(failures ? 1 : 0);
