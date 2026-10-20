# Qwen API verification — 20 October 2026

**Superseded status:** a later real CLI test with the updated credentials and application HTTP headers succeeded with HTTP 200 and produced a Qwen candidate. That candidate was independently rejected. See [Real Qwen CLI integration](qwen-real-cli-integration-20261020.md). The 403 result below remains the historical record of this earlier attempt.

**API generation BLOCKED: the single network-enabled generation request received HTTP 403 (Forbidden).** No candidate was returned, so independent grounding and meaning verification are **Not Evaluated** for this request. The status alone does not establish whether the cause is credentials, model availability, account policy or an intermediary.

## Intended provider and existing routing

C1 `.env` contains configured Groq credentials and `GROQ_MODEL=qwen/qwen3.8-27b`. Process-environment overrides were checked. The intended API endpoint used by `GroqGeneratorBackend` is `https://api.groq.com/openai/v1/chat/completions`. The configured request timeout is 30 seconds and output limit is 512 tokens.

Separate generic variables still name a local Ollama endpoint/model, but the existing Groq backend does not use them. The prior final-development report incorrectly focused on the local configuration as the intended Qwen path. That interpretation is superseded by this API check.

The CLI already invokes this API when explicitly selected:

```text
c1 generate-candidates --backend groq --in <validated_requirements.json> --srs <source> --out <new-sidecar.json>
```

`cli.py` constructs `GroqGeneratorBackend.from_environment()` for `--backend groq` and passes it to the refinement generator. The default remains explicitly deterministic. The wizard also has a Groq API generation option. No wrong-provider routing defect was found, and no provider/model/default was switched. Since the API did not work, the user's conditional integration-fix requirement did not trigger.

## Actual request and result

The minimal request used the existing Groq refinement backend's structured generation method with the synthetic sentence `The system shall record audit events` and explicit supporting text `The system shall record audit events.`. It was not a chat-only ping or a mocked inference result.

- Provider configuration: Groq.
- Requested model: `qwen/qwen3.8-27b` (unchanged).
- Received HTTP status: **403**.
- Real generation succeeded: **No**.
- Generated candidate: **None**.
- Independent grounding: **Not Evaluated — no returned candidate**.
- Independent meaning verification: **Not Evaluated — no returned candidate**.
- Approvals/publications: **None for this API test**.
- Live request elapsed time: approximately 0.23 seconds; no automatic retry.

The initial sandboxed workflow invocation reached the configured API transport but failed without an HTTP response. A network-enabled workflow attempt then encountered a filesystem PermissionError before issuing any request. The live check was therefore separated from local session writes and executed through the same existing backend; it received the single HTTP 403 response. No further live requests or model substitutions were attempted after that response. A successful live API-to-verified-candidate demonstration remains blocked; the prior approved deterministic fixture must not be relabelled as an API-generated result.

## Offline integration verification

Existing mocked-provider regression coverage was run: **40 passed in 0.74 seconds**, zero failures/skips. It checks CLI opt-in routing, dotenv/environment model resolution, exactly one transport call, sanitized 403 handling, candidate-sidecar flow, independent rejection of unsupported proposals, and preservation of input artifacts. These are offline mocked tests, not evidence of successful real inference. Existing coverage already exercises the requested routing path; no duplicate regression or speculative provider change was added.

Evidence under C1 `local-inference/final-c1-20261020/`:

- `api-qwen-result.json`: sanitized live outcome.
- `test_api_qwen.py`: credential-safe test harness; no embedded credentials.
- `api-provider-tests.log`, `api-provider-tests.xml`: offline regression results.

No API key or authorization header was printed or logged. The key and `.env` were not modified. No models were downloaded or switched to local inference. No source-code changes were needed for routing. Existing uncommitted C1 work was preserved; nothing was staged, committed or pushed.
