# c1-requirement-quality — Grounded Requirement Quality and Refinement

**Owner:** Jathusan J. (@Jathusan-Jesuthasan). Only the owner edits this folder (see `docs/INTEGRATION_RULES.md`).

This package is **Python** (Presidio, NLI, sentence-transformers and ML classifiers are Python tools).
It talks to C2 only through `c1/validated_requirements.json`, so the language does not affect anyone else.

## Set up (once)

The whole team uses **Python 3.12** (CI too). `pyproject.toml` refuses other versions.

```
cd packages/c1-requirement-quality
py -3.12 -m venv .venv            # Windows  (macOS/Linux: python3.12 -m venv .venv)
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
python --version                  # must print Python 3.12.x
pip install -e ".[dev]"
```

## Run and test

```
c1 run --srs <file> --out runs/<RUN-DIRECTORY> --run-id <RUN-ID>
pytest
```

### Requirement registry selection

Until the team confirms which existing C1 registry history is authoritative,
pass `--registry <path>` explicitly when running `c1 run`. The default
`.c1-state/requirement-registry.json` is relative to the process working
directory, and the repository currently contains two incompatible histories
at the repository root and in this package. They both contain retired IDs
`REQ-EX-001` through `REQ-EX-079`, while `REQ-EX-080` is active in the root
registry and retired in the package registry. Do not merge, replace, or select
one history based only on its location; resolve ownership and continuity with
the team first. Tests should continue to pass a temporary registry path.

Validate your output against the shared contract (from the repo root):

```
node packages/contracts/scripts/validate.mjs runs/<RUN-ID>
```

Stage A writes both `c1/parsed_requirements.json` and the contract-compliant
`c1/validated_requirements.json`. The latter intentionally keeps every
requirement pending review. Because the frozen contract has no unchecked
consistency status, the analyzer uses `potential_conflict` as a conservative
sentinel when no supported pairwise conclusion is available; this does not
claim that a conflict was detected. An empty `defects` array means only that no detector has reported a
defect, not that the requirement is defect-free.

Stage B adds deterministic lexical analysis in
`src/c1_requirement_quality/quality_analyser.py`. The independent rules report
signals for vague, ambiguous, incomplete, non-measurable, and non-verifiable
wording. They preserve overlapping findings and copy matched evidence exactly.
They are explainable heuristics, not a complete quality assessment: they can
produce false positives for wording that is clarified elsewhere and false
negatives for defects expressed without the implemented signal phrases.
The analyser suppresses only `reliable` when the same requirement contains an
explicit percentage-based availability or reliability target, such as `99.9%
monthly availability` or `reliability of at least 99.9%`. It does not suppress
`may`, `could`, or `secure` merely because technical terms or surrounding
details are present; those signals require richer context than this lexical
analyser provides. The CLI records findings in `defects` and maps the quality
check to `pass` or `fail` without promoting a requirement to ready.

Add dependencies to `pyproject.toml` (not a global pip install), so CI and teammates get them too.
Copy `.env.example` to `.env` for model settings. Never commit `.env`.

### Cross-requirement consistency

`src/c1_requirement_quality/consistency_analyser.py` compares every unordered
pair from the same parsed SRS. `c1/consistency_diagnostics.json` records pair
classifications, both requirement IDs, explanations, and exact evidence spans
with half-open character offsets. The `refine` workflow rechecks proposed
candidates against the untouched input requirement texts, then recomputes
consistency for the complete final-text set after all human decisions.

The analyzer reports a confirmed `conflict` only for (a) the same normalized
obligation and condition with opposite explicit `shall`/`must` negation or a
narrow supported opposing action verb, or (b) explicit numeric bounds on the
same normalized attribute, unit, and condition whose allowed intervals do not
overlap. Compatible explicit bounds and identical normalized obligations are
reported `consistent`. Missing/different units create `potential_conflict`;
different conditions, unrelated text, unsupported wording, and comparisons
that do not match a rule remain internally `unassessed`. No similarity score,
general semantic guess, or model is used.

The frozen contract has no `unassessed` status and no structured evidence-span
field for consistency. C1 retains the true analysis state and spans in its
separate diagnostics file. In the contract, unassessed or single-requirement
cases retain the conservative `potential_conflict` sentinel and the validation
check stays `skipped`; this does not assert that a conflict was detected.
Confirmed conflicts use the existing `conflict` status, both IDs, and an
explanation containing quoted evidence. A consistency check is marked `pass`
only when all comparisons for that requirement match supported rules and are
consistent; a confirmed conflict makes it `fail`. An inconclusive comparison
cannot make it pass. BDD readiness still requires every existing gate and an
eligible human decision.

This is intentionally a narrow rule set. It does not normalize units across
dimensions or convert values, infer actor-role overlap, resolve exceptions or
precedence, or establish whether differently worded predicates are equivalent.
Those cases remain for human review; team approval is needed before expanding
the rule vocabulary or treating analyzer coverage as a complete consistency
proof.

### Requirement tier classification

`src/c1_requirement_quality/tier_classifier.py` applies the existing C1
methodology using quality findings, traceable grounding evidence, and
cross-requirement consistency results. Run output keeps the explanation and
evidence in `c1/tier_diagnostics.json`; refinement diagnostics include
assessments for each candidate and the final requirement text. Refinement
recalculates tiers after all selected final texts are known.

| Tier | Deterministic rule | Handling meaning |
| --- | --- | --- |
| `TIER_1_AUTO_REFINE` | No quality findings; grounding is supported with evidence; and every peer comparison is consistent, or no peer requirement exists. For a candidate, its content must match the original exactly after whitespace normalization. | Only whitespace-level, meaning-preserving structural edits are in scope. The tier does not generate or approve an edit. |
| `TIER_2_CLARIFY` | Any quality finding; unsupported, partial, missing, or untraceable grounding; or any potential/unassessed peer comparison. | Human review or clarification is needed before adding or changing facts or behavior. |
| `TIER_3_ESCALATE` | A confirmed pairwise contradiction, including a grounding contradiction corroborated by the deterministic consistency rules. | Human resolution is required before proceeding. |

Conflict evidence takes precedence over other findings. Tier is not computed
from defect count or the severity/priority labels. An unassessed pair cannot
produce Tier 1. A one-requirement SRS has no peer pair to compare; it can still
reach Tier 1 only when quality findings are empty and grounding is supported
by traceable evidence. Tier does not set validation status, human decision, or
`bdd_ready`; those safeguards remain independent.

Under the current team direction, Tier 3 is reserved for confirmed
contradictions. The existing analyses do not define an objective threshold
for calling a standalone quality defect “too broken”; such defects currently
require clarification under Tier 2 unless a supported contradiction is also
found. A new non-contradiction Tier 3 trigger requires a separate policy decision.
The rule-based analyzer also cannot establish that a requirement is globally
defect-free; Tier 1 means only that the implemented checks found no blocker.

### Defect severity and remediation priority

C1 writes `c1/quality_assessments.json` beside the normal run artifacts. The
refinement workflow includes corresponding per-candidate and final-text
assessments in `c1/refinement_diagnostics.json`. These are internal diagnostics;
the frozen v1.0.0 contract has no severity or priority fields, and the validated
artifact is unchanged by these assessments.

The deterministic rubric describes specification-quality impact only:

| Defect category | Severity | Rationale |
| --- | --- | --- |
| Incomplete | high | An explicit unresolved placeholder can leave required behavior undefined. |
| Ambiguous | high | Multiple plausible interpretations can lead to different implementations. |
| Vague | moderate | Subjective wording obscures the intended behavior or acceptance boundary. |
| Non-measurable | moderate | A target lacks a measurable threshold. |
| Non-verifiable | moderate | A stated quality lacks an objective verification criterion. |

For multiple findings, the highest known severity is reported. Priority is a
remediation ordering derived only from severity: high severity maps to high
priority and moderate severity maps to normal priority. C1 currently has no
validated dependency-impact or blocking data for this assessment, so neither
is inferred. These labels do not represent business, safety, security, or
operational risk and do not assign or change a refinement tier, validation
status, human decision, or BDD readiness.

An unknown finding type, missing evidence span, or no detected findings is
marked `needs_review`; severity is `unknown` when no known finding can be
assessed. In particular, an empty finding list means only that existing rules
did not match. The per-finding diagnostics retain the exact evidence span and
give a plain-language rationale. This initial rubric is an explicit C1
proposal and should be confirmed by the research team before interpreting its
labels as project-approved risk or policy.

Stage C adds deterministic standalone grounding analysis in
`src/c1_requirement_quality/grounding_analyser.py`. It compares candidate
claims with supplied SRS text using conservative exact-claim matching and
returns exact evidence spans. It does not infer support from general lexical
overlap, and its narrow conflict checks do not resolve conflicting source
statements. The CLI uses this lexical analyser by default. RAG is opt-in with
`--grounding-mode rag`; its diagnostics are written separately to
`c1/rag_diagnostics.json` and are excluded from the contract object. In RAG
mode, successfully loaded local model IDs are recorded in the schema-approved
optional `producer.model` field. Neither grounding mode sets `bdd_ready` to
true.

## Local RAG grounding (opt-in)

Lexical grounding remains the default and does not load RAG models. To use
RAG, install the optional dependencies and explicitly cache the two local
models. The CLI never downloads model weights automatically.

PowerShell, from this package directory:

```powershell
pip install -e ".[rag]"
$env:HF_HOME = "$env:USERPROFILE\.cache\huggingface"
hf download sentence-transformers/all-MiniLM-L6-v2
hf download cross-encoder/nli-deberta-v3-small
c1 run --srs <file> --out runs/<RUN-ID> --run-id <RUN-ID> --grounding-mode rag
```

Run the `hf download` commands on a network-enabled machine. For a restricted
or offline machine, copy the complete Hugging Face cache directory to that
machine and set `HF_HOME` to the copied directory before running C1. To prevent
any Hub network access during inference, also set
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. Use the same `HF_HOME` for
model preparation and inference. A missing package or model file is reported
in the separate `c1/rag_diagnostics.json`; it is not treated as evidence that
the requirement is false. The contract output remains conservative when no
grounding evidence can be established.

## User-authored refinement candidates and decisions

C1 does not generate rewrite text. The `refine` command accepts alternatives
written by a requirement engineer, evaluates each with the existing lexical
quality, grounding, and consistency checks, and applies only an explicitly supplied human
decision. The original requirement is preserved in `original_text` in every
case. Explicit `[placeholder]`, `TBD`, and `TBC` markers produce clarification
questions; answers are never inferred.

Create an actions JSON file. Answers and candidate text are supplied by the
human; answers are retained in the separate run-local diagnostics file and are
not added as new contract fields:

```json
{
  "requirements": [
    {
      "requirement_id": "REQ-EX-001",
      "candidate_texts": [
        "The system shall return a result within 2 seconds."
      ],
      "clarification_questions": ["What response time is required?"],
      "clarification_answers": [
        {"question": "What response time is required?", "answer": "2 seconds"}
      ],
      "selected_candidate_text": "The system shall return a result within 2 seconds.",
      "human_decision": "pending"
    }
  ]
}
```

Process a validated C1 artifact into a **new** output folder (the folder must
not already exist). The artifact keeps the input `run_id`:

```powershell
c1 refine --in runs/<RUN-ID>/c1/validated_requirements.json `
  --srs <source-srs.md> --actions <actions.json> --out runs/<RUN-ID>-refined
```

Candidate IDs are deterministic hashes scoped to the requirement and exact
candidate text. A selection alone leaves `human_decision` pending and
`final_text` equal to `original_text`. `approved` requires a selected
candidate; `edited` requires `edited_text` and records that text as a
candidate. `rejected` and `pending` retain the original as `final_text`.
`not_required` is accepted only when explicitly present in the action file.
Candidate checks, evidence, unsupported claims, and supplied clarification
answers are written to `c1/refinement_diagnostics.json`; the validated output
contains only fields permitted by the frozen v1.0.0 schema.

Candidate diagnostics list quality, grounding, consistency, and BDD-readiness
checks independently. The BDD-readiness check is `skipped` because no approved
C1 criteria for that check are documented; the diagnostic records this reason
and keeps each candidate `bdd_ready: false`. Per current team direction, the
gate remains closed until approved criteria are supplied.

Candidate grounding uses the lexical exact-claim checker. This is deliberately
conservative: paraphrases or facts supplied only in a clarification answer may
remain unsupported against the SRS. The answer is visible in diagnostics but
is not treated as SRS evidence. Human approval does not override failed or
skipped checks. The CLI keeps `bdd_ready` false while consistency or BDD
readiness checks are skipped. Tier classification follows the documented
evidence rules above; it does not approve a candidate or set BDD readiness.
Inconclusive consistency comparisons keep the conservative
`potential_conflict` contract sentinel and do not pass the consistency check.

## First Planner tasks

- C1-02 Mini-SRS for the 3 pilot modules + golden `c1/validated_requirements.json`
- C1-04 SRS parser + requirement extraction with stable `REQ` IDs (FR-C1-01)
- C1-03 Datasets: PURE subset + 40 annotated requirements + 10 contradictory pairs
