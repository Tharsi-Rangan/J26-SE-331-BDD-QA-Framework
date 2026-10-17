# Human-reviewed consistency policy (Stage 4D.2)

Policy: `human-consistency-gates-v2`. Shared schemas are unchanged.

The published requirement-level `consistent` status means every comparison
obligation was resolved through deterministic consistency, complete-scope human
consistency review or complete-pair human non-applicability review. It does not
mean an automated proof of document consistency. Raw deterministic results stay
unchanged in refinement diagnostics. Effective resolutions and reviewer evidence
are separate internal records.

An all-not-applicable result is described as **reviewed coverage complete — no
applicable interactions established**. Every pair must have a current, explicitly
confirmed complete non-applicability review for that description to apply.

Unresolved, stale and partial reviews cannot clear an otherwise unassessed pair.
Deterministically established consistency remains sufficient independently of a
partial review, unless a confirmed human conflict remains open. Confirmed
deterministic conflicts and any open human-confirmed conflict take precedence.
Staleness or a later non-applicability click never erases a human conflict.
This stage intentionally provides no conflict-adjudication/closure operation;
such conflicts remain blocking pending a separately designed resolution process.

## Record and adopt

In `c1 demo`, `review-pair` remains the Stage 4D.1 audit-only operation.
`resolve-pair` records a fresh explicitly confirmed review in a new immutable,
source-verified refinement snapshot. It asks for both requirement IDs, verified
evidence references for both requirements, decision, scope, conditions, rationale,
reviewer and `complete`/`partial` coverage. Complete means the reviewer examined
the entire pair obligation, including shared conditions and cross-cutting rules.
The software validates attribution and references; it cannot prove the human
reasoning is correct. Independent adjudication remains advisable for research.

Earlier audit-only reviews are displayed as history but never adopted implicitly.
Reaffirmation requires the reviewer to enter the new policy fields and confirm
again. MiniLM scores only prioritise review; they are not source evidence.

Standalone use goes through the same `c1 refine` implementation:

```powershell
c1 refine --in <verified-run/c1/validated_requirements.json> --srs <SRS-path> `
  --actions <review-actions.json> --out <fresh-run-directory>
```

The actions file has this structure (placeholders are not real approvals):

```json
{
  "requirements": [],
  "consistency_reviews": [{
    "requirement_ids": ["REQ-EX-001", "REQ-EX-002"],
    "decision": "unresolved",
    "coverage": "partial",
    "evidence_refs": ["SRS:REQ-EX-001:original", "SRS:REQ-EX-002:original"],
    "scope": "<scope actually examined>",
    "conditions": "<conditions actually examined>",
    "rationale": "<reviewer's evidence-based rationale>",
    "reviewer": "<actual reviewer ID>",
    "confirmed": true
  }]
}
```

Review transactions cannot include requirement edits or approval actions.
No default, bulk approval or automatic non-applicability operation exists.
Existing output paths are refused. Guided pause/recovery uses the same verified
snapshot adoption mechanism as other refinement operations; it never replays a
request automatically.

## Binding and approval

Reviews bind original/current texts, source identity and complete source hashes,
source locations, clarification question/answer state, evidence and policy.
Changes invalidate affected reviews; invalidation is retained in immutable
workflow history even if text later returns to an old value. Reviews for original
text do not validate different candidate text. Unassessed rewritten candidates
remain blocked until they have an applicable current-text assessment.

Adopted reviews live in the existing workflow event ledger, sealed by the source
manifest and verified through ancestry. Guided-session receipts point to these
snapshots; there is no second gate-authoritative session ledger. Standalone
refinement and candidate generation inherit the same verified workflow basis.
Supplying external clarification overrides to candidate generation intentionally
disables inherited review clearance because the evidence context differs.

Review policy and basis enter validation signatures. Changed bases invalidate
dependent acceptance and require a separate fresh human decision. Clearing
consistency does not override quality, grounding, unanswered questions, escalation,
semantic-change review or explicit acceptance. Tier is recomputed from all gates;
a consistency pass alone cannot grant BDD readiness or human approval.

Keep the complete run ancestry with exported artifacts. A standalone shared JSON
contains the aggregate result, while audit provenance requires its internal
workflow snapshot and refinement diagnostics. Hashes provide integrity checks,
not authenticated reviewer identity or validated research performance.
