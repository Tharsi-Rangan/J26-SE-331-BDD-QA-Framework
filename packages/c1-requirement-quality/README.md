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

Validate your output against the shared contract (from the repo root):

```
node packages/contracts/scripts/validate.mjs runs/<RUN-ID>
```

Stage A writes both `c1/parsed_requirements.json` and the contract-compliant
`c1/validated_requirements.json`. The latter intentionally keeps every
requirement pending review. Because the frozen contract has no unchecked
consistency status, Stage A uses `potential_conflict` as a conservative
sentinel with no reported conflict; this does not claim that a conflict was
detected. An empty `defects` array means only that no detector has reported a
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
analyser provides. The CLI does not yet use this analyser, so its contract
output leaves `defects` empty and the quality check skipped.

Add dependencies to `pyproject.toml` (not a global pip install), so CI and teammates get them too.
Copy `.env.example` to `.env` for model settings. Never commit `.env`.

Stage C adds deterministic standalone grounding analysis in
`src/c1_requirement_quality/grounding_analyser.py`. It compares candidate
claims with supplied SRS text using conservative exact-claim matching and
returns exact evidence spans. It does not infer support from general lexical
overlap, and its narrow conflict checks do not resolve conflicting source
statements. The CLI does not yet use this analyser, so its contract output
retains the Stage A grounding placeholder and skipped grounding check.

## First Planner tasks

- C1-02 Mini-SRS for the 3 pilot modules + golden `c1/validated_requirements.json`
- C1-04 SRS parser + requirement extraction with stable `REQ` IDs (FR-C1-01)
- C1-03 Datasets: PURE subset + 40 annotated requirements + 10 contradictory pairs
