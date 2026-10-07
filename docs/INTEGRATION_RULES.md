# Integration rules (J26-SE-331)

Goal: build each component alone for PP1, then plug them together for PP2 with **no surprises**.
These rules stop the four of us from breaking each other's work or fighting over the same files.

## 1. Who owns what

| Path | Owner | Others may |
|---|---|---|
| `packages/c1-requirement-quality/` | Jathusan (C1) | read only |
| `packages/c2-gherkin-generation/` | Shanchika (C2) | read only |
| `packages/c3-test-generation/` | Tharsiga (C3) | read only |
| `packages/c4-mutation-adequacy/` | Shajana (C4) | read only |
| `packages/orchestrator/`, root configs, CI, `pnpm-lock.yaml` | Tharsiga | PR only |
| `packages/contracts/` | **all four** | PR + all 4 approvals |
| `fixtures/subjects/subject-manifest.json` | Tharsiga + Shajana | PR only |
| `fixtures/golden/<SUB-ID>/c1/` … `/c4/` | the producer of that stage | read only |

`CODEOWNERS` enforces this on GitHub. Never edit another member's folder. If you need a change there, open a GitHub issue and assign them.

## 2. The only shared code is `@j26/contracts`

- Components never import each other. The only shared package is `packages/contracts`.
- Components talk **only through files** in a run folder (below). No shared database, no shared in-memory objects.
- C4's SQLite trace store is private to C4. Other components read `adequacy_report.json` only.

## 3. Run folder layout (each stage writes only its own folder)

```
runs/<RUN-ID>/
  subject-manifest.json          (copied in by the orchestrator)
  c1/validated_requirements.json
  c2/features/*.feature
  c2/scenario_metadata.json
  c3/runnable_tests/*.test.js
  c3/test_stubs/*.stub.js
  c3/test_manifest.json
  c3/mock_decisions.json
  c3/generation_confidence_report.json
  c4/adequacy_report.json
  c4/adequacy_report.html
  c4/raw/mutation.json
```

- `runs/` is git-ignored. Only `fixtures/golden/` is committed.
- Paths inside JSON are **relative to the run folder**, use `/`, never absolute.
- The same `run_id` is copied into every file of one run.

## 4. Same CLI shape for every component

```
c1 run --srs <file>                      --out runs/<RUN-ID>
c2 run --in runs/<RUN-ID>                --out runs/<RUN-ID>
c3 run --in runs/<RUN-ID> --subject-root <path>  --out runs/<RUN-ID>
c4 run --in runs/<RUN-ID> --subject-root <path>  --out runs/<RUN-ID>
```
Exit code 0 = success. Every component must also accept a **golden fixture folder** as `--in`, which is how we each work alone before PP1.

## 5. IDs (see `schemas/common.schema.json`)

| ID | Made by | Format | Example |
|---|---|---|---|
| Requirement | C1 | `REQ-<CODE>-<nnn>` | `REQ-EX-001` |
| Scenario | C2 | `SCN-<CODE>-<nnn>-<nn>` | `SCN-EX-001-02` |
| Test | C3 | `TST-<CODE>-<nnn>-<nn>-<nn>` | `TST-EX-001-02-03` |
| Stub | C3 | `STB-<CODE>-<nnn>-<nn>` | `STB-EX-001-04` |
| Subject | C3+C4 | `SUB-<...>` | `SUB-EX-1` |
| Mutant | StrykerJS | Stryker's own id, unchanged | `12` |

- IDs are never reused or renumbered. If a requirement is deleted, its number stays retired.
- Each child ID repeats its parent's number, so a human can trace by eye.
- `.feature` tags and Jest test names carry these IDs (see `packages/contracts/conventions/`).

## 6. Changing a contract

1. Open a PR labelled `contract-change` that edits `packages/contracts/schemas/` **and** updates the golden fixtures.
2. Bump `version` in `packages/contracts/package.json`:
   - patch (1.0.x): wording/description only
   - minor (1.x.0): new **optional** field
   - major (x.0.0): rename, remove, or make a field required, or change an enum
3. Producer + every consumer approve. CI must pass.
4. **Freeze:** v1.0.0 is frozen on **Mon 5 Oct 2026**. No major change before PP1 (22 Oct).

## 7. Dependencies and the lockfile

- Add packages only with `pnpm --filter <your-package> add <dep>`.
- Never hand-merge `pnpm-lock.yaml`. On conflict: take `main`'s version, run `pnpm install`, commit.
- Python components (if any) keep their own `pyproject.toml` inside their package and validate JSON with the same schemas (`jsonschema` library, Draft 2020-12).

## 8. Models and secrets

- All components call models through one OpenAI-compatible local endpoint, set by env vars:
  `LLM_BASE_URL`, `LLM_MODEL`, `EMBEDDING_MODEL`. Never hard-code a provider.
- Record the exact model tag in `producer.model` of your output file.
- Each package has its own `.env` (git-ignored) and a committed `.env.example`.

## 9. Git habits (also PP1 evidence)

- Branch: `<c1|c2|c3|c4|shared>/<feat|fix|docs>/<short-name>` e.g. `c3/feat/mock-rules`.
- Commit: Conventional Commits + Planner task ID, e.g. `feat(c3): rule-based mock decisions [C3-05]`.
- Small, frequent commits. PR into `main`, 1 review, CI green. No direct pushes to `main`.

## 10. CI gate

Every PR runs `node packages/contracts/scripts/validate.mjs` on all folders in `fixtures/golden/`.
It checks the schemas **and** cross-file links (unknown IDs, wrong Jest names, `.feature` tags that do not match metadata, scenarios built from non-ready requirements). A red check blocks the merge.
