# Write a blind annotation packet. Usage: python3 scripts/annotation-packet.py <fixture dir> <mutation.json> <packet.md>
import json, os, re, sys
fixture, mutation_json, out = sys.argv[1:4]
m = json.load(open(mutation_json))
meta = json.load(open(os.path.join(fixture, 'c2/scenario_metadata.json')))
[(fname, f)] = m['files'].items()
lines = f['source'].split('\n')
surv = sorted([x for x in f['mutants'] if x['status'] in ('Survived', 'NoCoverage')], key=lambda x: int(x['id']))
P = ['# Annotation packet: Express-5 pilot (C4-08)', '',
     'Read `docs/trace-annotation-guideline.md` first. Label every survivor in section 5.', '',
     '## 1. Requirements and scenarios', '']
for ft in meta['features']:
    P += [f"### {ft['requirement_id']}: {ft['feature_name']}", '', ft['requirement_text_used'], '']
    feat = open(os.path.join(fixture, ft['feature_file'])).read()
    P += ['```gherkin', feat.rstrip(), '```', '']
P += ['## 2. Tests (C3 output)', '']
for t in sorted(os.listdir(os.path.join(fixture, 'c3/runnable_tests'))):
    P += [f'### {t}', '', '```js', open(os.path.join(fixture, 'c3/runnable_tests', t)).read().rstrip(), '```', '']
P += ['## 3. Module under test: `lib/utils.js` (with line numbers)', '', '```js']
P += [f'{i+1:4d}  {l}' for i, l in enumerate(lines)]
P += ['```', '', '## 4. Status', '',
      '- `Survived`: at least one test ran the mutated code, and no test failed.',
      '- `NoCoverage`: no test ran the mutated code.', '',
      f'## 5. Survivors ({len(surv)})', '']
for x in surv:
    s, e = x['location']['start'], x['location']['end']
    orig_lines = lines[s['line']-1:e['line']]
    if s['line'] == e['line']:
        orig = orig_lines[0][s['column']-1:e['column']-1]
    else:
        orig = '\n'.join(orig_lines)[s['column']-1:]
        orig = orig[:len(orig) - (len(orig_lines[-1]) - (e['column']-1))]
    P += [f"### Mutant {x['id']}", '',
          f"- Status: {x['status']}",
          f"- Location: line {s['line']}:{s['column']} to line {e['line']}:{e['column']}",
          f"- Mutator: {x['mutatorName']}",
          '- Original code:', '', '```js', orig, '```', '',
          '- Replacement:', '', '```js', x.get('replacement', ''), '```', '']
os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, 'w').write('\n'.join(P) + '\n')
json.dump([x['id'] for x in surv], open(out.replace('.md', '.ids.json'), 'w'))
print(len(surv), 'survivors ->', out)
