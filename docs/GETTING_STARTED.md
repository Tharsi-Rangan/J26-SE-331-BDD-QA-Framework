# Getting started (every member, once)

Read `docs/INTEGRATION_RULES.md` after this page. It has the full rules.

## 1. Install tools

| Tool | Version | Check |
|---|---|---|
| Git | any recent | `git --version` |
| Node.js | **22 LTS** (22.12 or newer) | `node -v` |
| pnpm | **9.12.0** exactly | `npm install -g pnpm@9.12.0`, then `pnpm -v` |
| Python | **3.12** (all members, CI too) | `py -3.12 --version` |
| VS Code | any | accept the "recommended extensions" pop-up |

## 2. Clone and check that everything works

```
git clone https://github.com/Tharsi-Rangan/J26-SE-331-BDD-QA-Framework.git
cd J26-SE-331-BDD-QA-Framework
pnpm install
pnpm validate:contracts
pnpm test
```

All three must end without errors. If not, post the output in Teams.

## 3. Where your work goes

| Member | Folder | Language |
|---|---|---|
| Jathusan (C1) | `packages/c1-requirement-quality/` | Python |
| Shanchika (C2) | `packages/c2-gherkin-generation/` | TypeScript |
| Tharsiga (C3 + orchestrator) | `packages/c3-test-generation/`, `packages/orchestrator/` | TypeScript |
| Shajana (C4) | `packages/c4-mutation-adequacy/` | TypeScript |

- **Only edit your own folder.** This is what keeps merge conflicts away.
- Your golden fixture files go in `fixtures/golden/<SUB-ID>/cN/` (only your `cN` sub-folder).
- `packages/contracts/` is **frozen (v1.0.0)**. Change it only through a `contract-change` PR that all four approve.
- Need something changed in someone else's folder? Open a GitHub issue and assign them.

## 4. Daily git routine

```
git checkout main
git pull
git checkout -b c3/feat/input-reader          # <c1|c2|c3|c4|shared>/<feat|fix|docs>/<short-name>
# ... work ...
git add .
git commit -m "feat(c3): read feature files [C3-03]"   # always end with the Planner task ID
git push -u origin c3/feat/input-reader
```

Then open a Pull Request on GitHub. The PR template asks for the task ID and evidence.
CI must be green and one teammate must approve before merging. Nobody pushes to `main` directly.

## 5. Adding a dependency

- TypeScript packages: `pnpm --filter @j26/<your-package> add <dep>` (never `npm install`).
- C1: add it to `pyproject.toml`, then `pip install -e ".[dev]"`.
- If `pnpm-lock.yaml` conflicts when you merge `main`: **never edit it by hand.**
  Take `main`'s version (`git checkout --theirs pnpm-lock.yaml` during a merge), run `pnpm install`, and commit.

## 6. Run your component

```
pnpm c2 run --in packages/contracts/fixtures/golden/example-registration --out runs/RUN-DEV
pnpm c3 run --in packages/contracts/fixtures/golden/example-registration --subject-root <path> --out runs/RUN-DEV
pnpm c4 run --in packages/contracts/fixtures/golden/example-registration --subject-root <path> --out runs/RUN-DEV
```

`runs/` is git-ignored. Check your output with:

```
node packages/contracts/scripts/validate.mjs runs/RUN-DEV
```

**Tip:** `packages/contracts/fixtures/golden/example-registration/` is a complete, valid example of every hand-off file.
Build and test your input reader on it **now**. You do not need to wait for the previous member's real output.

## 7. Models

Copy `.env.example` to `.env` in your package (never commit `.env`).
All components use the same local OpenAI-compatible endpoint (`LLM_BASE_URL`). See `docs/model-setup.md` (added in task SH-07).

## 8. End of each day (10 min)

1. RP diary entry + AI-use log rows.
2. Move your Planner card and attach the evidence.
3. One-line status in Teams, including anything that blocks you.
