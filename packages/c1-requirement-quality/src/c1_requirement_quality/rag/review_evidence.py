"""Narrow Phase 1B.3 human evidence integration in the existing session journal.

Source-only candidate receipts retain their original semantics. Human support
is reconstructed separately from an exact verified journal prefix and never
written into the original SRS or a source-only receipt.
"""
from __future__ import annotations

from c1_requirement_quality.source_integrity import VerifiedWorkflowContext, sha256
from c1_requirement_quality.rag.candidate_validation import _canonical
from c1_requirement_quality.validation_lifecycle import clarification_grounding


HUMAN_POLICY = "phase1b3-exact-human-support-journal-v1"


class ReviewedGroundingContext(VerifiedWorkflowContext):
    def __init__(self, source_context, workspace, anchor):
        super().__init__(source_context.input_path, source_context.source)
        self.source_context = source_context
        self.workspace = workspace
        self.anchor = anchor
        self.receipts = source_context.receipts

    def check_parent(self, artifact):
        self.source_context.check_parent(artifact)

    def assess(self, requirement_id, candidate, srs_text, original, workflow_record):
        from c1_requirement_quality.demo_workflow import DemoSession
        try:
            # Source-only evidence does not depend on clarification state. The
            # existing context authenticates the complete source/workflow chain,
            # candidate receipt, model assets and unchanged meaning here. The
            # outer review service still checks current questions/escalations,
            # peer scope and explicit approval independently. Human facts require
            # the additional journal-bound path below; never use it as fallback
            # for a missing/failed/contradictory RAG receipt.
            result = self.source_context.assess(requirement_id, candidate, srs_text, original, None)
            if result.get("eligible_for_acceptance"):
                return result
            if (result.get("completion_status") != "completed"
                    or result.get("verdict") not in {"SUPPORTED", "INCONCLUSIVE"}
                    or result.get("conflicts")):
                return result
            # This read-only reconstruction returns evidence, never approval
            # intents. Normal approval/publication still verifies every intent.
            session = DemoSession(self.workspace, _registry_anchor=self.anchor,
                analyser_factory=self.source_context.analyser_factory, _evidence_only=True)
            data, text, manifest, parent = session.read()
            state = session.review_read()[3]
            record = state["requirements"][requirement_id]
            row = next(r for r in data["requirements"] if r["requirement_id"] == requirement_id)
            if (session.current.resolve() != self.input_path.resolve()
                    or session.source.resolve() != self.source.resolve()
                    or workflow_record != record or text != srs_text or row["original_text"] != original):
                raise ValueError("Human evidence workflow/source/requirement basis mismatch")
            human = clarification_grounding(candidate, text, original, record,
                source_format="docx" if session.source.suffix.lower() == ".docx" else None,
                require_human=True)
            if human.get("status") != "supported" or not human.get("human_clarification_evidence"):
                return result
            result.update(status="supported", eligible_for_acceptance=True,
                srs_evidence=human["srs_evidence"],
                human_clarification_evidence=human["human_clarification_evidence"],
                evidence=human["evidence"], support_method=human["support_method"],
                human_evidence_binding={"policy": HUMAN_POLICY, "journal": self.anchor,
                    "requirement_id": requirement_id, "source_sha256": manifest["sha256"],
                    "workflow_sha256": manifest["workflow_sha256"],
                    "record_sha256": sha256(_canonical(record))},
                meaning_preservation={"policy": HUMAN_POLICY,
                    "status": "traceable_to_explicit_human_clarification",
                    "source_only_comparison": result.get("meaning_preservation")})
            return result
        except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
            return {"authority": "rag", "status": "unsupported", "verdict": "ERROR",
                    "completion_status": "incomplete", "eligible_for_acceptance": False,
                    "evidence": [], "errors": [str(error)]}
