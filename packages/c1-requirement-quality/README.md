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
c1 run --srs <file> --out runs/<RUN-ID>
pytest
```

Validate your output against the shared contract (from the repo root):

```
node packages/contracts/scripts/validate.mjs runs/<RUN-ID>
```

Add dependencies to `pyproject.toml` (not a global pip install), so CI and teammates get them too.
Copy `.env.example` to `.env` for model settings. Never commit `.env`.

## First Planner tasks

- C1-02 Mini-SRS for the 3 pilot modules + golden `c1/validated_requirements.json`
- C1-04 SRS parser + requirement extraction with stable `REQ` IDs (FR-C1-01)
- C1-03 Datasets: PURE subset + 40 annotated requirements + 10 contradictory pairs
