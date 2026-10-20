# Real Qwen CLI refinement test — 20 October 2026

**Real API generation succeeded. Candidate verification rejected the proposal. No approval or publication occurred.**

## Execution and transport fix

Provider: **Groq**. Configured and returned model: **`qwen/qwen3.8-27b`**. The existing backend reads the updated C1 `.env`; there was no process-level API-key override. Credentials were not printed, logged or modified.

The test invoked the existing CLI entry point with the actual parsed command `generate-candidates ... --backend groq`, not a deterministic generation replacement. The requirement was imported through the existing `run` CLI first. A thin diagnostic wrapper observed HTTP status without replacing the transport, request, model, response or backend.

The initial real CLI request received HTTP 403 with Python's default client headers. Added `User-Agent: c1-requirement-quality/0.1` and `Accept: application/json` to the existing Groq transport. A bounded retry, with the same provider, model and configured credentials, returned **HTTP 200**, CLI exit **0**, one structured Qwen proposal, and completed in **0.69 seconds**. This resolved the observed client-specific failure; it does not establish a universal explanation for all Groq 403 responses. There were two live attempts in this task: one 403, then one 200; no automatic retry loop or additional request after success.

The backend verified the response model, completion status and structured proposal fields. No model download, local LLM switch or deterministic-generation substitution occurred.

## Synthetic input and actual candidate

The source file explicitly labels itself **Synthetic Qwen API integration fixture**. It contains one numbered requirement and a separate explicit supporting-evidence paragraph.

Original `REQ-API-001`:

> The system shall record audit events

Supporting evidence:

> The system shall record audit events.

Actual Qwen candidate:

> The system shall record [PLACEHOLDER] audit events, including [PLACEHOLDER] data fields, and store them in [PLACEHOLDER] for [PLACEHOLDER] duration.

The source supports the original obligation and a punctuation-only refinement. It does not establish the added fields, storage obligation or duration. The model unnecessarily expanded the requirement instead of limiting its rewrite to supported meaning.

## Independent verification and review eligibility

| Check | Actual result |
| --- | --- |
| CLI quality check | Rejected as `quality_regression`; introduced `incomplete` placeholders |
| Independent grounding | `unsupported`; the expanded candidate is not supported by the source |
| Independent meaning comparison | `changed_or_unproven`; changed the target and added or changed obligations |
| Ranked/eligible candidates | **0** |
| Eligible for selection/approval | **No**; retained as a rejected diagnostic proposal |
| Human decision/publication | None; no previous fixture approval was reused |

The existing CLI rejected the proposal early on quality regression. The harness additionally called the existing `analyse_grounding` and `compare_meaning` services on the actual returned candidate, so both independent outcomes were measured rather than inferred from the API's wording. Grounding verification here is the CLI's deterministic lexical source check, and meaning verification is the existing conservative obligation comparison; no neural-RAG execution is claimed for this test. Deterministic verification is distinct from deterministic generation.

The sidecar's heuristic `fabrication_rate` or grounding-failure counter must not be read as evaluation accuracy. Early quality rejection can prevent later counters from incrementing. The explicit independent checks above are authoritative for this report.

## Additional reporting defect fixed

The successful API sidecar exposed an existing metadata bug: `generator.baseline_type` was hard-coded to `rule-based baseline generator` even when the actual backend was `GroqGeneratorBackend`. Added an `api_llm` generation-kind tag, propagated it through the registered review backend, and corrected future sidecars to say `API LLM proposal generator`. The original live sidecar was preserved unchanged as evidence; its backend, strategy, source/model fields and observed HTTP 200 establish real API generation. The legacy baseline-type label in that artifact is not evidence of deterministic substitution.

Changed C1 implementation files in this task: `groq_generator.py` (application headers and generation-kind tag), `rewrite_generator.py` (accurate generator metadata), `demo_workflow.py` (propagate generation kind), and `tests/test_groq_generator.py` (mocked transport/header/CLI metadata assertions). Existing unrelated uncommitted C1 work was preserved.

## Tests and artifacts

**63 focused offline tests passed in 2.16 seconds**, zero failures/skips: Groq backend and rewrite-generator suites. Mocked tests verify application headers, the requested model, explicit CLI routing, accurate API-generator metadata, sanitized errors, candidate validation and no input-artifact mutation. These are offline regression tests, separate from the actual HTTP 200 generation result. The full C1 suite was not repeated for this narrow transport/reporting fix.

Artifacts relative to C1:

- Successful result and independent checks: `local-inference/final-c1-20261020/real-cli-groq-agent/result.json`.
- Original real API sidecar: `local-inference/final-c1-20261020/real-cli-groq-agent/groq-candidates.json`.
- Explicit synthetic input: `local-inference/final-c1-20261020/real-cli-groq-agent/synthetic-requirement.md`.
- Original analysis and source archive: the same directory's `run/c1/`.
- Offline test logs: the same directory's `tests.log` and `tests.xml`.
- First 403 attempt: `local-inference/final-c1-20261020/real-cli-groq/result.json`.
- Reproducible harness: `local-inference/final-c1-20261020/real_cli_groq.py`.

The actual CLI command was equivalent to:

```powershell
$base='packages/c1-requirement-quality/local-inference/final-c1-20261020/real-cli-groq-agent'
& packages/c1-requirement-quality/.venv/Scripts/c1.exe generate-candidates --in "$base/run/c1/validated_requirements.json" --srs "$base/synthetic-requirement.md" --out "$base/groq-candidates.json" --backend groq
```

Choose a fresh output filename before repeating; the existing sidecar is not overwritten. Repetition would make another live API request and was not performed after success.

Remaining blocker: the generated candidate fails independent checks. A future proposal must remain within the original supported obligation, or explicitly authorized additional source requirements must be supplied and verified. No safeguard was weakened to make this candidate pass. C2, frozen contracts and model weights were not changed. Nothing was staged, committed or pushed.
