# Write the C4 Express-5 pilot fixture. Usage: python3 scripts/pilot-express-5-fixture.py <out dir> <subject-manifest.json> [rec-001]
# With rec-001, the fixture also has the scenario and test that REC-001 of the first run asks for (C4-12).
import json, os, sys
OUT = sys.argv[1]
APPLY_REC_001 = len(sys.argv) > 3 and sys.argv[3] == 'rec-001'
RUN = 'RUN-FIXTURE-EXPRESS-5'
SUB = 'SUB-EXPRESS-5'
TS = '2026-10-18T09:00:00+05:30'
REL = '../../subject-src/lib/utils'
env = lambda c, up=None: {"contract": c, "schema_version": "1.0.0",
    "producer": {"component": "MANUAL_FIXTURE", "tool_version": "fixture"},
    "run_id": RUN, "generated_at": TS, **({"upstream": up} if up else {})}

# requirement -> (feature name, text, [scenarios])
# scenario = (n, name, type, [tests]); test = (n, case, categories, body lines) or table rows
REQS = [
 ('001', 'Absolute path detection',
  "The system shall treat a path as absolute when it starts with '/', when it starts with a drive letter followed by ':' and '\\', or when it starts with '\\\\'.",
  [('01', 'Detect absolute POSIX and Windows paths', 'positive', [
      ('01', "path '/home/user'", ['equality'], ["expect(utils.isAbsolute('/home/user')).toBe(true);"]),
      ('02', "path 'C:\\\\Users'", ['equality'], ["expect(utils.isAbsolute('C:\\\\Users')).toBe(true);"]),
   ]),
   ('02', 'Reject relative paths', 'negative', [
      ('01', "path 'foo/bar'", ['equality'], ["expect(utils.isAbsolute('foo/bar')).toBeFalsy();"]),
   ])]),
 ('002', 'Media type normalisation',
  "The system shall convert a short type name such as 'html' to its full MIME type, and shall split a full type into its value, quality and parameters.",
  [('01', 'Expand a short type name', 'positive', [
      ('01', "type 'html'", ['equality'], ["expect(utils.normalizeType('html')).toEqual({ value: 'text/html', params: {} });"]),
   ]),
   ('02', 'Parse the quality of a full type', 'positive', [
      ('01', "type 'text/html; q=0.5'", ['equality'], [
          "const r = utils.normalizeType('text/html; q=0.5');",
          "expect(r.value).toBe('text/html');",
          "expect(r.quality).toBeDefined();"]),
   ]),
   ('03', 'Normalize a list of types', 'positive', [
      ('01', "types ['html', 'json']", ['equality'], ["expect(utils.normalizeTypes(['html', 'json'])).toHaveLength(2);"]),
   ])] + ([
   ('04', 'Parse the parameters of a full type', 'positive', [
      ('01', "type 'text/html; charset=utf-8; q=0.5'", ['equality'], [
          "expect(utils.normalizeType('text/html; charset=utf-8; q=0.5')).toEqual({",
          "  value: 'text/html',",
          "  quality: 0.5,",
          "  params: { charset: 'utf-8' },",
          "});"]),
   ])] if APPLY_REC_001 else [])),
 ('003', 'ETag function selection',
  "The system shall select the weak ETag function for true or 'weak', the strong ETag function for 'strong', no function for false, and shall reject any other value with a TypeError.",
  [('01', 'Select the ETag function from the setting', 'positive', 'ETAG_TABLE'),
   ('02', 'Reject an unknown ETag setting', 'negative', [
      ('01', "setting 'bogus'", ['exception'], ["expect(() => utils.compileETag('bogus')).toThrow(TypeError);"]),
   ])]),
 ('004', 'Proxy trust',
  "The system shall build a proxy trust function from true (trust all proxies), from a hop count n (trust the first n hops), from a comma-separated list of addresses, or from a function.",
  [('01', 'Trust all proxies with true', 'positive', [
      ('01', 'setting true', ['equality'], ["expect(utils.compileTrust(true)('10.0.0.1', 7)).toBe(true);"]),
   ]),
   ('02', 'Trust a number of hops', 'boundary', 'HOP_TABLE'),
   ('03', 'Trust a list of addresses', 'positive', [
      ('01', "list '127.0.0.1, 10.0.0.1'", ['equality'], [
          "const trust = utils.compileTrust('127.0.0.1, 10.0.0.1');",
          "expect(trust('10.0.0.1', 0)).toBe(true);"]),
   ])]),
 ('005', 'Content-Type charset',
  "The system shall set the charset parameter of a Content-Type value, and shall return the type unchanged when the type or the charset is missing.",
  [('01', 'Set the charset of a type', 'positive', [
      ('01', "type 'text/html', charset 'utf-8'", ['equality'], ["expect(utils.setCharset('text/html', 'utf-8')).toBe('text/html; charset=utf-8');"]),
   ]),
   ('02', 'Keep the type when the charset is missing', 'edge', [
      ('01', "type 'text/html', no charset", ['equality'], ["expect(utils.setCharset('text/html')).toBe('text/html');"]),
   ])]),
]
STEPS = {
 '001-01': ['Given the path "/home/user"', 'When the path is checked', 'Then the path is absolute'],
 '001-02': ['Given the path "foo/bar"', 'When the path is checked', 'Then the path is not absolute'],
 '002-01': ['Given the type "html"', 'When the type is normalized', 'Then the value is "text/html" with no parameters'],
 '002-02': ['Given the type "text/html; q=0.5"', 'When the type is normalized', 'Then the value is "text/html" and the quality is 0.5'],
 '002-03': ['Given the types "html" and "json"', 'When the types are normalized', 'Then 2 normalized types are returned'],
 '002-04': ['Given the type "text/html; charset=utf-8; q=0.5"', 'When the type is normalized', 'Then the value is "text/html", the quality is 0.5 and the charset parameter is "utf-8"'],
 '003-01': ['Given the ETag setting <setting>', 'When the ETag function is compiled', 'Then the function is "<kind>"'],
 '003-02': ['Given the ETag setting "bogus"', 'When the ETag function is compiled', 'Then a TypeError is thrown'],
 '004-01': ['Given the trust setting true', 'When the trust function is compiled', 'Then every proxy is trusted'],
 '004-02': ['Given the trust setting 2', 'When hop <hop> is checked', 'Then the trust result is <trusted>'],
 '004-03': ['Given the trust setting "127.0.0.1, 10.0.0.1"', 'When the address "10.0.0.1" is checked', 'Then the address is trusted'],
 '005-01': ['Given the type "text/html" and the charset "utf-8"', 'When the charset is set', 'Then the type is "text/html; charset=utf-8"'],
 '005-02': ['Given the type "text/html" and no charset', 'When the charset is set', 'Then the type is "text/html"'],
}
TABLES = {
 'ETAG_TABLE': {'rows': [('01', 'true', 'weak'), ('02', "'weak'", 'weak'), ('03', 'false', 'none')],
   'title': 'setting %s -> %s',
   'params': '(_id, setting, kind)',
   'body': ["const fn = utils.compileETag(setting);",
            "if (kind === 'none') expect(fn).toBeUndefined();",
            "else expect(fn('hello')).toMatch(/^W\\//);"],
   'each': lambda r: f"['{{id}}', {r[1]}, '{r[2]}']", 'cats': ['equality'], 'case': lambda r: f"setting {r[1].strip(chr(39))} -> {r[2]}", 'keys': ('setting', 'kind')},
 'HOP_TABLE': {'rows': [('01', '0', 'true'), ('02', '5', 'false')],
   'title': 'hops 2, hop %i -> %s',
   'params': '(_id, hop, trusted)',
   'body': ["expect(utils.compileTrust(2)('10.0.0.1', hop)).toBe(trusted);"],
   'each': lambda r: f"['{{id}}', {r[1]}, {r[2]}]", 'cats': ['equality'], 'case': lambda r: f"hops 2, hop {r[1]} -> {r[2]}", 'keys': ('hop', 'trusted')},
}

tests, features, scenarios, files = [], [], [], {}
for rq, fname, text, scns in REQS:
    req = f'REQ-EXPRESS-{rq}'
    ffile = f'c2/features/{req}.feature'
    tfile = f'c3/runnable_tests/{req}.test.js'
    describe = f'[{req}] {fname}'
    features.append({"feature_file": ffile, "requirement_id": req, "feature_name": fname, "requirement_text_used": text})
    js = [f'// @requirement {req}', f"const utils = require('{REL}');", '', f"describe('{describe}', () => {{"]
    gherkin = [f'@{req}', f'Feature: {fname}', f'  {text}', '']
    for sn, sname, stype, tl in scns:
        scn = f'SCN-EXPRESS-{rq}-{sn}'
        outline = isinstance(tl, str)
        sc = {"scenario_id": scn, "requirement_id": req, "feature_file": ffile, "scenario_name": sname,
              "scenario_type": stype, "is_outline": outline,
              "verification": {"syntax": "pass", "requirement_consistency": {"status": "pass"}, "ep_coverage": "skipped",
                               "bva_coverage": "skipped", "completeness": "pass", "fully_verified": True}}
        gherkin += [f'  @{scn} @type:{stype}', f"  Scenario{' Outline' if outline else ''}: {sname}",
                    *['    ' + x for x in STEPS[f'{rq}-{sn}']]]
        if outline:
            t = TABLES[tl]
            gherkin += ['', '    Examples:', f"      | {t['keys'][0]} | {t['keys'][1]} |",
                        *[f"      | {r[1].strip(chr(39))} | {r[2]} |" for r in t['rows']]]
        gherkin.append('')
        if outline:
            t = TABLES[tl]
            sc["examples"] = []
            rows = []
            for i, r in enumerate(t['rows'], 1):
                tid = f'TST-EXPRESS-{rq}-{sn}-{r[0]}'
                rows.append('    ' + t['each'](r).format(id=tid) + ',')
                sc["examples"].append({"row_index": i, "values": {t['keys'][0]: json.loads(r[1].replace(chr(39), '"')), t['keys'][1]: json.loads(r[2]) if r[2] in ('true', 'false') else r[2]}})
                tests.append({"test_id": tid, "scenario_id": scn, "requirement_id": req, "file": tfile,
                    "jest_full_name": f"{describe} [{scn}][{tid}] {sname} :: {t['case'](r)}",
                    "examples_row": i, "strategy": "parametrised", "assertion_categories": t['cats']})
            js += ['  test.each([', *rows, f"  ])('[{scn}][%s] {sname} :: {t['title']}', {t['params']} => {{",
                   *['    ' + b for b in t['body']], '  });', '']
        else:
            for tn, case, cats, body in tl:
                tid = f'TST-EXPRESS-{rq}-{sn}-{tn}'
                name = f'[{scn}][{tid}] {sname} :: {case}'
                tests.append({"test_id": tid, "scenario_id": scn, "requirement_id": req, "file": tfile,
                    "jest_full_name": f'{describe} {name}', "strategy": "factory", "assertion_categories": cats})
                js += [f"  test({json.dumps(name)}, () => {{", *['    ' + b for b in body], '  });', '']
        scenarios.append(sc)
    js[-1:] = ['});', '']
    files[tfile] = '\n'.join(js)
    files[ffile] = '\n'.join(gherkin)

for t in tests:
    t.update({"verification": {"syntactic": "pass", "referential": "pass", "traceability": "pass", "semantic": {"status": "skipped"}}, "repair_rounds": 0})

files['c3/test_manifest.json'] = {**env('c3.test-manifest', [{"contract": "c2.scenario-metadata", "path": "c2/scenario_metadata.json", "schema_version": "1.0.0"}]),
    "subject_id": SUB, "runner": {"name": "jest", "version": "29", "config_path": "jest.config.js", "test_root": "c3/runnable_tests"},
    "tests": tests, "stubs": []}
files['c2/scenario_metadata.json'] = {**env('c2.scenario-metadata'), "features": features, "scenarios": scenarios}
sm = json.load(open(sys.argv[2]))
subj = next(s for s in sm['subjects'] if s['subject_id'] == SUB)
subj = {**subj, "source": {**subj['source'], "repo_path": "subject-src"}, "jest_config": "jest.config.js",
        "requirement_ids": [f'REQ-EXPRESS-{r[0]}' for r in REQS],
        "notes": "C4 pilot fixture. Requirements, scenarios and tests are hand-written by C4 for C4-07, C4-08 and C4-12. They are not C1, C2 or C3 output. Run with --subject-root at BugsJS express, buggy_ref."}
files['subject-manifest.json'] = {"contract": "shared.subject-manifest", "schema_version": "1.0.0", "subjects": [subj]}
files['jest.config.js'] = "module.exports = { testEnvironment: 'node', roots: ['<rootDir>/c3/runnable_tests'] };\n"
for rel, content in files.items():
    p = os.path.join(OUT, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as f:
        f.write(content if isinstance(content, str) else json.dumps(content, indent=2) + '\n')
print(len(tests), 'tests', len(scenarios), 'scenarios')
