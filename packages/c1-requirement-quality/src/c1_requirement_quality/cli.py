
"""C1 requirement quality command line interface."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from c1_requirement_quality.grounding_analyser import analyse_grounding
from c1_requirement_quality.quality_analyser import analyse_requirements

from c1_requirement_quality.consistency_analyser import analyse_consistency, consistency_for_requirement
from c1_requirement_quality.requirement_registry import RequirementRegistry
from c1_requirement_quality.source_integrity import (
    document_identity, snapshot_source, seal_source, verify_source, copy_source_bundle,
)
from c1_requirement_quality.workflow_persistence import (
    initial_state, write_state, load_state, refine_with_history,
)
from c1_requirement_quality.severity_priority import assess_defects
from c1_requirement_quality.tier_classifier import classify_tier
from c1_requirement_quality.rag.rag_grounding_analyser import RAGGroundingAnalyser
from c1_requirement_quality.rag.verifier import FactVerifier, LocalNLI

RUN_ID_PATTERN = re.compile(
    r"(?:^RUN-[0-9]{8}-[0-9]{6}-[a-z0-9]{4}$)"
    r"|(?:^RUN-FIXTURE-[A-Z0-9-]+$)"
)
TOOL_VERSION = "0.1.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="c1")
    sub = parser.add_subparsers(dest="command")

    tui_parser = sub.add_parser("tui", help="selectable terminal wizard over the existing verified workflow")
    tui_parser.add_argument("--root", help="session discovery directory")
    tui_parser.add_argument("--session", help="resume an existing verified session")
    demo_parser = sub.add_parser("demo", help="guided resumable review; saved sidecars, no model/API execution")
    mode = demo_parser.add_mutually_exclusive_group()
    mode.add_argument("--workspace", help="fresh session directory")
    mode.add_argument("--resume", help="existing session directory")
    demo_parser.add_argument("--in", dest="input_path", help="verified existing run artifact")
    demo_parser.add_argument("--srs", help="SRS for new analysis; defaults to archived source for existing run")
    demo_parser.add_argument("--run-id")
    demo_parser.add_argument("--registry")
    demo_parser.add_argument("--project-code", default="EX")
    demo_parser.add_argument("--document-id")
    demo_parser.add_argument("--wizard", action="store_true", help="resume the complete numbered wizard")
    publish_parser = sub.add_parser("publish-approved", help="publish current journal-backed approval intents")
    questions_parser = sub.add_parser("generate-review-questions", help="record neutral rule-based questions without answers or approval")
    questions_parser.add_argument("--session", required=True)
    questions_parser.add_argument("--requirement-id", action="append")
    publish_parser.add_argument("--session", required=True)
    publish_parser.add_argument("--reviewer", required=True)
    publish_parser.add_argument("--confirm", required=True, choices=("yes",))
    publish_parser.add_argument("--requirement-id", action="append")
    export_parser = sub.add_parser("export-refined", help="export authenticated Refined SRS DOCX and quality reports")
    export_parser.add_argument("--session", required=True)
    export_parser.add_argument("--out", required=True, help="fresh export directory")
    run_parser = sub.add_parser(
        "run",
        help="parse an SRS into C1 requirements",
    )
    run_parser.add_argument("--srs", required=True, help="path to the SRS file")
    run_parser.add_argument("--out", required=True, help="run folder")
    run_parser.add_argument(
        "--run-id",
        required=True,
        help="contract run ID, e.g. RUN-20261009-181600-ab12",
    )
    run_parser.add_argument(
        "--grounding-mode", choices=("lexical", "rag"), default="lexical",
        help="grounding implementation (default: lexical baseline)",
    )
    run_parser.add_argument("--project-code", default="EX", help="requirement ID prefix")
    run_parser.add_argument("--document-id", help="logical document identity; use consistently across source renames/moves")
    run_parser.add_argument(
        "--registry",
        help="explicit document-scoped registry file; historical defaults are never selected implicitly",
    )

    refine_parser = sub.add_parser(
        "refine",
        help="evaluate user-authored candidates and apply explicit human decisions",
    )
    refine_parser.add_argument("--in", dest="input_path", required=True, help="validated_requirements.json")
    refine_parser.add_argument("--srs", required=True, help="source SRS used for lexical grounding")
    refine_parser.add_argument("--actions", required=True, help="JSON file with candidate and decision actions")
    refine_parser.add_argument("--out", required=True, help="new output folder; must not already exist")

    gen_parser = sub.add_parser(
        "generate-candidates",
        help="generate evidence-grounded candidate rewrites into a sidecar",
    )
    gen_parser.add_argument("--in", dest="input_path", required=True, help="validated_requirements.json")
    gen_parser.add_argument("--srs", required=True, help="source SRS file")
    gen_parser.add_argument("--out", required=True, help="path for candidate_suggestions.json output sidecar")
    gen_parser.add_argument("--backend", choices=("deterministic", "groq"), default="deterministic",
                            help="groq explicitly sends requirement/evidence context to the configured cloud model")
    gen_parser.add_argument(
        "--clarification-answers",
        dest="clarification_answers",
        help="JSON file containing user-supplied clarification answers",
    )
    gen_parser.add_argument(
        "--grounding-mode",
        choices=("lexical",),
        default="lexical",
        help="candidate validation supports lexical only; use run for RAG analysis",
    )
    proposal_parser = sub.add_parser("propose-clarifications", help="opt-in Groq clarification sidecar; explicit human handoff")
    proposal_parser.add_argument("--in", dest="input_path", required=True)
    proposal_parser.add_argument("--srs", required=True)
    proposal_parser.add_argument("--out", required=True)
    proposal_parser.add_argument("--requirement-id", action="append", required=True)
    proposal_parser.add_argument("--backend", choices=("groq",), required=True)
    proposal_parser.add_argument("--defect-diagnostics")
    proposal_parser.add_argument("--similarity-diagnostics")
    proposal_parser.add_argument("--max-requests", type=int, default=2)
    proposal_parser.add_argument("--max-evidence-chars", type=int, default=6000)
    proposal_parser.add_argument("--max-context-chars", type=int, default=12000)
    similarity_parser = sub.add_parser("diagnose-similarity", help="opt-in local MiniLM pair diagnostics; no decision effect")
    similarity_parser.add_argument("--in", dest="input_path", required=True)
    similarity_parser.add_argument("--out", required=True, help="new diagnostic JSON file")
    similarity_parser.add_argument("--model-dir", help="local all-MiniLM-L6-v2 checkpoint directory")
    similarity_parser.add_argument("--threshold", type=float, help="experimental similarity cutoff [0,1]; unset selects nothing")
    similarity_parser.add_argument("--batch-size", type=int, default=4)
    similarity_parser.add_argument("--max-pairs", type=int, default=10_000)
    ml_parser = sub.add_parser("diagnose-defects", help="opt-in local experimental DistilBERT sidecar; no decision effect")
    ml_parser.add_argument("--in", dest="input_path", required=True)
    ml_parser.add_argument("--out", required=True, help="new diagnostic JSON file")
    ml_parser.add_argument("--model-dir", help="local verified Experiment 2 checkpoint directory")
    ml_parser.add_argument("--threshold", type=float, help="experimental sigmoid cutoff in [0,1]; unset returns scores only")
    for command in ("list-pairs", "review-pairs"):
        pair_parser = sub.add_parser(command, help="export internal pair applicability; no decision-gate effect")
        pair_parser.add_argument("--in", dest="input_path", required=True)
        pair_parser.add_argument("--srs", required=True)
        pair_parser.add_argument("--out", required=True, help="new internal review snapshot JSON")
        pair_parser.add_argument("--previous", help="previous immutable review snapshot to carry forward")
        if command == "review-pairs":
            pair_parser.add_argument("--actions", required=True, help="JSON containing explicit human decisions")
    return parser


from c1_requirement_quality.contract import validate_contract_artifact, _validate_contract_artifact


def refine_run(input_path: Path, srs: Path, actions_path: Path, out: Path, *,
               evidence_registry: Path | None = None, evidence_candidate_ids: list[str] | None = None,
               analyser_factory=None, _operation=None, _prepared=None) -> None:
    """Evaluate alternatives; optional parent evidence remains historical only.

    Evidence selection is an explicit internal API, not a new wizard route.
    Session publication requires a separately journal-retained prepared commitment.
    """
    if (evidence_registry is None) != (evidence_candidate_ids is None):
        raise ValueError("Parent evidence requires both registry and candidate selection")
    if (_operation is None) != (_prepared is None):
        raise ValueError("Operation publication requires a prepared receipt writer")
    for path, label in ((input_path, "validated requirements"), (srs, "SRS"), (actions_path, "actions")):
        if not path.is_file():
            raise FileNotFoundError(f"{label} file not found: {path}")
    if out.exists():
        raise FileExistsError(f"output run folder already exists: {out}")

    from c1_requirement_quality.source_integrity import sha256, VerifiedWorkflowContext, resolve_workflow_policy
    artifact_raw = input_path.read_bytes()
    actions_raw = actions_path.read_bytes()
    artifact = json.loads(artifact_raw)
    actions = json.loads(actions_raw)
    _validate_contract_artifact(artifact)
    srs_text, manifest = verify_source(input_path, srs)
    if sha256(artifact_raw) != manifest["artifact_sha256"]:
        raise ValueError("Refinement parent artifact digest mismatch")
    from c1_requirement_quality.source_integrity import require_refinement_grounding
    rag_publication = bool(manifest.get("rag_policy") and _operation is not None
                           and _operation.get("approval_intent_sha256s"))
    if not rag_publication:
        require_refinement_grounding(manifest)
    parent_state, _ = load_state(input_path, srs)
    registry_anchor = None
    if _operation is not None:
        from c1_requirement_quality.demo_workflow import DemoSession
        from c1_requirement_quality.workflow_persistence import _candidate_snapshot_identity
        from c1_requirement_quality.rag.candidate_validation import _canonical
        operation = _operation
        prefix = DemoSession(Path(operation["workspace"]), _registry_anchor={
            "sequence": operation["sequence"], "sha256": operation["sha256"]},
            analyser_factory=analyser_factory)
        if (operation.get("operation_version") != 2 or prefix.pending != operation
                or prefix.current.resolve() != input_path.resolve() or prefix.source.resolve() != srs.resolve()
                or Path(operation["actions"]).resolve() != actions_path.resolve()
                or Path(operation["out"]).resolve() != out.resolve()
                or operation["parent_identity"] != _candidate_snapshot_identity(manifest, parent_state)
                or operation["actions_sha256"] != sha256(actions_raw)
                or operation["actions_parsed_sha256"] != sha256(_canonical(actions))
                or operation["evidence_candidate_ids"] != (evidence_candidate_ids or [])
                or (evidence_registry is not None and evidence_registry.resolve() != prefix.workspace)):
            raise ValueError("Refinement operation provenance mismatch")
        registry_anchor = operation["registry_anchor"]
        if registry_anchor != {"sequence": operation["sequence"] - 1, "sha256": operation["previous"]}:
            raise ValueError("Refinement registry cutoff must precede the pending operation")
    if rag_publication:
        from c1_requirement_quality.rag.publication import materialize
        refined, diagnostics, workflow_state, _ = materialize(_operation, srs, analyser_factory=analyser_factory)
    else:
        refined, diagnostics, workflow_state = refine_with_history(
            artifact, actions, srs_text, parent_state, input_path, out / "c1", manifest,
            snapshot_id=_operation["child_snapshot_id"] if _operation is not None else None,
        )
    if _operation is not None:
        from c1_requirement_quality.workflow_persistence import refinement_operation_binding
        workflow_state["operation_binding"] = refinement_operation_binding(_operation)
    _validate_contract_artifact(refined)
    if evidence_registry is not None:
        selected = {row["selected_candidate_id"] for row in refined["requirements"]
                    if row.get("selected_candidate_id") is not None
                    and (not rag_publication or row["human_decision"] == "approved")}
        if not isinstance(evidence_candidate_ids, list) or not selected <= set(evidence_candidate_ids):
            raise ValueError("Selected candidate lacks selected parent evidence")

    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".c1-refine-pending-", dir=out.parent))
    c1_dir = staging / "c1"
    c1_dir.mkdir()
    child_raw = (json.dumps(refined, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    (c1_dir / "validated_requirements.json").write_bytes(child_raw)
    diagnostics_raw = (json.dumps(diagnostics, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    (c1_dir / "refinement_diagnostics.json").write_bytes(diagnostics_raw)
    if evidence_registry is not None:
        from c1_requirement_quality.workflow_persistence import archive_parent_evidence_links
        workflow_state["parent_evidence_links"] = archive_parent_evidence_links(
            VerifiedWorkflowContext(input_path, srs), evidence_registry, c1_dir,
            evidence_candidate_ids, analyser_factory=analyser_factory, registry_anchor=registry_anchor)
    if _operation is not None and sha256(_canonical(workflow_state.get("parent_evidence_links"))) != _operation["evidence_links_sha256"]:
        raise ValueError("Refinement operation evidence selection changed")
    copy_source_bundle(input_path, c1_dir, manifest, workflow_state)
    expected_state = dict(workflow_state, artifact_sha256=sha256(child_raw))
    expected_workflow = (json.dumps(expected_state, indent=2, ensure_ascii=False) + "\n").replace("\n", os.linesep).encode("utf-8")
    expected_manifest = dict(manifest, artifact_sha256=sha256(child_raw),
                             workflow_sha256=sha256(expected_workflow))
    prepared_event = None
    if rag_publication:
        expected_manifest["rag_ancestry_version"] = 1
        commitment = {"version": 1, "snapshot_id": expected_state["snapshot_id"],
            "artifact_sha256": sha256(child_raw), "workflow_sha256": sha256(expected_workflow),
            "manifest_sha256": sha256(_canonical(expected_manifest)), "diagnostics_sha256": sha256(diagnostics_raw)}
        prepared_event = _prepared(commitment)
        from c1_requirement_quality.source_integrity import _verify_source_local
        from c1_requirement_quality.rag.publication import verify_publication
        _, staged_manifest, staged_artifact = _verify_source_local(c1_dir / "validated_requirements.json", srs)
        verified_workflow = (c1_dir / "internal/workflow_snapshot.json").read_bytes()
        if sha256(verified_workflow) != staged_manifest["workflow_sha256"]:
            raise ValueError("Staged workflow digest mismatch")
        staged_state = json.loads(verified_workflow)
        verify_publication(c1_dir / "validated_requirements.json", srs, staged_manifest,
                           staged_artifact, staged_state, staging=True)
    else:
        _, _, staged_manifest, staged_state = resolve_workflow_policy(
            VerifiedWorkflowContext(c1_dir / "validated_requirements.json", srs))
    if staged_manifest != expected_manifest or staged_state != expected_state:
        raise ValueError("Staged child differs from the prepared refinement")
    if evidence_registry is not None and not rag_publication:
        from c1_requirement_quality.workflow_persistence import verify_child_evidence_links
        verify_child_evidence_links(c1_dir / "validated_requirements.json", srs,
            registry_workspace=evidence_registry, analyser_factory=analyser_factory, registry_anchor=registry_anchor)
    if (sha256((c1_dir / "validated_requirements.json").read_bytes()) != sha256(child_raw)
            or (c1_dir / "internal/workflow_snapshot.json").read_bytes() != expected_workflow
            or actions_path.read_bytes() != actions_raw):
        raise ValueError("Refinement staging or actions changed before publication")
    # Parent integrity is checked again before publication; it remains immutable.
    load_state(input_path, srs)
    if _operation is not None:
        commitment = {"version": 1, "snapshot_id": expected_state["snapshot_id"],
            "artifact_sha256": sha256(child_raw), "workflow_sha256": sha256(expected_workflow),
            "manifest_sha256": sha256(_canonical(expected_manifest)),
            "diagnostics_sha256": sha256(diagnostics_raw)}
        if prepared_event is None:
            prepared_event = _prepared(commitment)
        proof = DemoSession(Path(_operation["workspace"]), _registry_anchor={
            "sequence": prepared_event["sequence"], "sha256": prepared_event["sha256"]},
            analyser_factory=analyser_factory)
        if (proof.pending != _operation or proof.prepared != prepared_event
                or proof.prepared["commitment"] != commitment):
            raise ValueError("Prepared child commitment is not journal-bound")
        if rag_publication:
            _, final_manifest, staged_artifact = _verify_source_local(c1_dir / "validated_requirements.json", srs)
            verified_workflow = (c1_dir / "internal/workflow_snapshot.json").read_bytes()
            if sha256(verified_workflow) != final_manifest["workflow_sha256"]:
                raise ValueError("Prepared workflow digest mismatch")
            final_state = json.loads(verified_workflow)
            verify_publication(c1_dir / "validated_requirements.json", srs, final_manifest,
                               staged_artifact, final_state, staging=True)
        else:
            _, _, final_manifest, final_state = resolve_workflow_policy(
                VerifiedWorkflowContext(c1_dir / "validated_requirements.json", srs))
        if (final_manifest != expected_manifest or final_state != expected_state
                or sha256((c1_dir / "validated_requirements.json").read_bytes()) != commitment["artifact_sha256"]
                or sha256((c1_dir / "internal/workflow_snapshot.json").read_bytes()) != commitment["workflow_sha256"]
                or sha256((c1_dir / "refinement_diagnostics.json").read_bytes()) != commitment["diagnostics_sha256"]
                or actions_path.read_bytes() != actions_raw):
            raise ValueError("Prepared staging changed before publication")
        if evidence_registry is not None and not rag_publication:
            verify_child_evidence_links(c1_dir / "validated_requirements.json", srs,
                registry_workspace=evidence_registry, analyser_factory=analyser_factory,
                registry_anchor=registry_anchor)
    if out.exists():
        raise FileExistsError(f"output run folder already exists: {out}")
    staging.rename(out)
    c1_dir = out / "c1"
    print(f"[c1] wrote refined requirements to {c1_dir / 'validated_requirements.json'}")
    print(f"[c1] wrote refinement diagnostics to {c1_dir / 'refinement_diagnostics.json'}")
    for rid, record in workflow_state["requirements"].items():
        print(f"[c1] {rid}: {record['workflow_status']} ({len(record['unanswered_question_ids'])} unanswered questions)")


def _run_staged(
    srs: Path,
    out: Path,
    run_id: str,
    project_code: str = "EX",
    registry: RequirementRegistry | None = None,
    grounding_mode: str = "lexical",
    document_id: str | None = None,
    progress=None,
    stage_progress=None,
    mandatory_rag: bool = False,
) -> None:
    """Parse an SRS, run quality and grounding analysis, and write contract-compliant artifacts.

    Stage A: extract requirements with stable REQ-IDs.
    Stage B: populate defects and validation.checks.quality using quality_analyser.
    Stage C: populate grounding and validation.checks.grounding using grounding_analyser.

    All output and registry assignments remain staged until validated.
    """
    if not srs.is_file():
        raise FileNotFoundError(f"SRS file not found: {srs}")
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(f"Invalid run_id: {run_id}")
    if grounding_mode not in {"lexical", "rag"}:
        raise ValueError("grounding_mode must be 'lexical' or 'rag'")
    if mandatory_rag and grounding_mode != "rag":
        raise ValueError("Mandatory RAG analysis cannot use lexical grounding")

    # Extract normalized full text and requirements from any supported SRS format
    c1_dir = out / "c1"
    c1_dir.mkdir()
    if progress: progress("Document reading and requirement extraction...")
    doc, manifest = snapshot_source(c1_dir, srs, document_identity(srs, document_id), stage_progress=stage_progress)
    srs_text = doc.raw_text
    extracted = [req.to_legacy_item() for req in doc.requirements]
    if not extracted:
        raise ValueError("SRS contains no requirements; no C1 artifact was generated")

    assert registry is not None
    texts = [str(item["original_text"]) for item in extracted]
    # Use logical section breadcrumbs, not page/line coordinates that shift on insertion.
    contexts = [json.dumps(req.section_hierarchy, ensure_ascii=False) for req in doc.requirements]
    requirement_ids = registry.assign_ids(texts, contexts=contexts,
                                         document_id=manifest["document_id"], persist=False)

    requirements: list[dict[str, object]] = []
    for item, requirement_id in zip(extracted, requirement_ids, strict=True):
        req_entry: dict[str, object] = {
            "requirement_id": requirement_id,
            "source": item["source"],
            "original_text": item["original_text"],
        }
        for extra_key in ("doc_item_number", "section_hierarchy", "page", "table_id"):
            if extra_key in item and item[extra_key] is not None:
                req_entry[extra_key] = item[extra_key]
        requirements.append(req_entry)

    if stage_progress:
        stage_progress("extract", "completed", f"{len(requirements)} requirements identified")
        stage_progress("quality", "running", "")

    # Stage B: run deterministic lexical quality analysis.
    # analyse_requirements preserves input order and is independent per requirement.
    if progress: progress("Quality checks...")
    quality_findings: list[list[dict[str, str]]] = analyse_requirements(
        [str(r["original_text"]) for r in requirements]
    )
    if stage_progress:
        stage_progress("quality", "completed", "Rule-based checks")
        stage_progress("grounding", "running", "Deterministic grounding and consistency")

    if progress: progress("Consistency analysis...")
    consistency_analysis = analyse_consistency([
        {"requirement_id": row["requirement_id"], "text": row["original_text"]}
        for row in requirements
    ])
    consistency_results = {
        str(row["requirement_id"]): consistency_for_requirement(
            str(row["requirement_id"]), consistency_analysis
        )
        for row in requirements
    }

    # Stage C: use the selected grounding service against the archived full text.
    if progress: progress("Grounding...")
    rag_analyser = None
    rag_provenance = None
    rag_loaded_models = []
    rag_memory = {}
    try:
        rag_analyser = (
            RAGGroundingAnalyser(srs_text, use_spacy=False) if mandatory_rag else
            RAGGroundingAnalyser(srs_text, verifier=FactVerifier(LocalNLI()))
            if grounding_mode == "rag" else None
        )
        if mandatory_rag:
            from c1_requirement_quality.ml.ml_diagnostics import _require_memory, available_memory_bytes
            rag_memory["before_bytes"] = _require_memory()
            rag_provenance = rag_analyser.model_provenance()
        grounding_results: list[dict[str, object]] = [
            (rag_analyser.analyse(str(r["original_text"])) if rag_analyser else
             analyse_grounding(str(r["original_text"]), srs_text, source_format="docx")
              if doc.format == "docx" else analyse_grounding(str(r["original_text"]), srs_text))
            for r in requirements
        ]
        if rag_analyser:
            (c1_dir / "rag_diagnostics.json").write_text(json.dumps([
                {"requirement_id": req["requirement_id"], "text": req["original_text"],
                 **result} for req, result in zip(requirements, grounding_results, strict=True)
            ], indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        if mandatory_rag:
            errors = [message for result in grounding_results for message in result.get("errors", [])]
            if not errors and any(d.get("outcome") == "ERROR"
                    for result in grounding_results for d in result.get("diagnostics", [])):
                errors.append("RAG verification returned ERROR without diagnostic details")
            if errors:
                raise RuntimeError("; ".join(errors))
            if rag_analyser.model_provenance() != rag_provenance:
                raise RuntimeError("RAG model assets changed during analysis")
            rag_loaded_models = list(rag_analyser.loaded_model_names)
            rag_memory["after_inference_bytes"] = available_memory_bytes()
    except Exception as error:
        if mandatory_rag:
            if stage_progress: stage_progress("grounding", "failed", str(error))
            raise ValueError(f"Mandatory RAG grounding incomplete: {type(error).__name__}: {error}") from error
        raise
    finally:
        if mandatory_rag and rag_analyser is not None:
            rag_memory["collected_objects"] = rag_analyser.release()
            # Profiling must not mask an earlier model/verification failure.
            try:
                from c1_requirement_quality.ml.ml_diagnostics import available_memory_bytes
                rag_memory["after_release_bytes"] = available_memory_bytes()
            except Exception as memory_error:
                rag_memory["measurement_error"] = str(memory_error)
    if stage_progress:
        stage_progress("grounding", "completed", "Implemented checks finished; uncertainty remains reviewable")
        stage_progress("tier", "running", "")
    if progress: progress("Tier classification...")
    tier_results = {
        str(requirement["requirement_id"]): classify_tier(
            findings,
            grounding_res,
            consistency_results[str(requirement["requirement_id"])],
        )
        for requirement, findings, grounding_res in zip(
            requirements, quality_findings, grounding_results, strict=True
        )
    }
    if stage_progress:
        stage_progress("tier", "completed", "Tier 1 / Tier 2 / Tier 3 assessed")
        stage_progress("review", "running", "Validating and publishing review artifacts")

    if rag_analyser:
        for result in grounding_results:
            for message in result.get("errors", []):
                print(f"[c1] RAG grounding error: {message}", file=sys.stderr)

    c1_dir = out / "c1"
    c1_dir.mkdir(parents=True, exist_ok=True)
    (c1_dir / "consistency_diagnostics.json").write_text(
        json.dumps({
            **consistency_analysis,
            "requirements": consistency_results,
        }, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (c1_dir / "tier_diagnostics.json").write_text(
        json.dumps([
            {"requirement_id": requirement["requirement_id"],
             "assessment": tier_results[str(requirement["requirement_id"])]}
            for requirement in requirements
        ], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (c1_dir / "quality_assessments.json").write_text(
        json.dumps([
            {
                "requirement_id": requirement["requirement_id"],
                "assessment": assess_defects(findings),
            }
            for requirement, findings in zip(requirements, quality_findings, strict=True)
        ], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    output_path = c1_dir / "parsed_requirements.json"
    output_path.write_text(
        json.dumps(requirements, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    extraction_diag_path = c1_dir / "extraction_diagnostics.json"
    extraction_diag = {
        "source_document": srs.name,
        "format": doc.format,
        "requirements_count": len(doc.requirements),
        "context_items_count": len(doc.context_items),
        "uncertain_items_count": len(doc.uncertain_items),
        "tables_count": len(doc.tables),
        "warnings": [w.to_dict() for w in doc.warnings],
        "context_summary": {
            sub_cat: sum(1 for c in doc.context_items if c.sub_category == sub_cat)
            for sub_cat in sorted(set(c.sub_category for c in doc.context_items if c.sub_category))
        },
        "uncertain_items": [u.to_legacy_item() for u in doc.uncertain_items],
    }
    extraction_diag_path.write_text(
        json.dumps(extraction_diag, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    validated_req_items: list[dict[str, object]] = []
    for requirement, findings, grounding_res in zip(
        requirements, quality_findings, grounding_results, strict=True
    ):
        consistency = consistency_results[str(requirement["requirement_id"])]
        tier = tier_results[str(requirement["requirement_id"])]
        g_status = str(grounding_res["status"])
        if g_status == "supported":
            grounding_check = "pass"
        elif g_status in ("unsupported", "partially_supported"):
            grounding_check = "fail"
        elif g_status == "not_applicable":
            grounding_check = "skipped"
        else:
            grounding_check = "skipped"

        validated_req_items.append(
            {
                "requirement_id": str(requirement["requirement_id"]),
                "source": requirement["source"],
                "original_text": str(requirement["original_text"]),
                "defects": findings,
                "tier": tier["tier"],
                "grounding": {
                    "status": grounding_res["status"],
                    "evidence": grounding_res["evidence"],
                },
                # The frozen contract has no unchecked status. This
                # conservative value prevents downstream readiness.
                "consistency": {
                    "status": consistency["status"],
                    "related_requirement_ids": consistency["related_requirement_ids"],
                    "conflicts": consistency["conflicts"],
                },
                "validation": {
                    # validation.status remains "needs_review": consistency checks
                    # are still skipped, and human_decision is still pending.
                    # A requirement is never promoted to "passed" by automated checks alone.
                    "status": "needs_review",
                    "checks": {
                        "quality": "fail" if findings else "pass",
                        "grounding": grounding_check,
                        "consistency": consistency["check"],
                        "bdd_readiness": "skipped",
                    },
                },
                "human_decision": "pending",
                "final_text": requirement["original_text"],
                "bdd_ready": False,
            }
        )

    producer: dict[str, str] = {"component": "C1", "tool_version": TOOL_VERSION}
    if rag_analyser is not None:
        loaded_models = tuple(getattr(rag_analyser, "loaded_model_names", ()))
        if loaded_models:
            # This optional string is explicitly permitted by the frozen shared envelope.
            producer["model"] = ", ".join(loaded_models)

    validated_requirements = {
        "contract": "c1.validated-requirements",
        "schema_version": "1.0.0",
        "producer": producer,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_document": {
            "name": srs.name,
            "project_code": project_code,
            "path": f"c1/internal/source/{srs.name}",
            "redaction_applied": False,
        },
        "requirements": validated_req_items,
    }
    validated_output_path = c1_dir / "validated_requirements.json"
    _validate_contract_artifact(validated_requirements)
    validated_output_path.write_text(
        json.dumps(validated_requirements, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if mandatory_rag:
        from c1_requirement_quality.source_integrity import sha256
        metadata = {"policy": "c1-initial-rag-v1", "status": "completed",
            "input_sha256": sha256(validated_output_path.read_bytes()),
            "source_sha256": manifest["sha256"], "normalized_sha256": manifest["normalized_sha256"],
            "models": rag_provenance, "loaded_models": rag_loaded_models, "memory": rag_memory,
            "scope": "initial original requirements only; refinement publication blocked"}
        metadata_path = c1_dir / "internal/rag_provenance.json"
        metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        manifest.update(rag_policy="c1-initial-rag-v1",
            rag_provenance_sha256=sha256(metadata_path.read_bytes()),
            rag_diagnostics_sha256=sha256((c1_dir / "rag_diagnostics.json").read_bytes()))
    write_state(c1_dir, initial_state(validated_requirements, manifest))
    seal_source(c1_dir, manifest)


def run(srs: Path, out: Path, run_id: str, project_code: str = "EX",
        registry_path: Path | None = None, grounding_mode: str = "lexical",
        document_id: str | None = None, progress=None, stage_progress=None,
        mandatory_rag: bool = False) -> None:
    """Validate a staged run before publishing artifacts, then commit registry last.

    Failed staging directories are retained for inspection. No existing run is
    overwritten. A failed registry commit moves outputs back to staging.
    """
    if registry_path is None:
        raise ValueError("Pass --registry explicitly; historical default registry ownership is unresolved")
    registry = RequirementRegistry(registry_path, project_code)
    registry.assert_writable()
    target = out / "c1"
    if target.exists():
        raise FileExistsError(f"C1 output already exists: {target}")
    if registry.path.resolve().is_relative_to(target.resolve()):
        raise ValueError("Registry must be outside the published C1 artifact directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".c1-run-pending-", dir=out.parent))
    try:
        _run_staged(srs, staging, run_id, project_code, registry, grounding_mode, document_id, progress, stage_progress, mandatory_rag)
        staged = staging / "c1"
        _validate_contract_artifact(json.loads((staged / "validated_requirements.json").read_text(encoding="utf-8")))
        verify_source(staged / "validated_requirements.json", srs)
        with registry.publication_lock():
            if target.exists():
                raise FileExistsError(f"C1 output already exists: {target}")
            out.mkdir(parents=True, exist_ok=True)
            staged.rename(target)
            try:
                registry._commit_locked()
            except Exception:
                target.rename(staged)
                raise
    except Exception as err:
        raise RuntimeError(f"C1 run not published; staging retained at {staging}: {err}") from err
    try:
        staging.rmdir()  # newly created by this invocation, and only if empty
    except OSError:
        print(f"[c1] published run; staging retained at {staging}", file=sys.stderr)
    print(f"[c1] wrote validated requirements to {target / 'validated_requirements.json'}")
    print(f"[c1] registry: {registry.path}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "tui":
            from c1_requirement_quality.tui import launch
            from c1_requirement_quality.demo_workflow import DemoSession
            return launch(root=args.root, session=DemoSession(Path(args.session)) if args.session else None)
        if args.command is None or (args.command == "demo" and not args.workspace and not args.resume):
            if args.command == "demo" and any((args.input_path, args.srs, args.run_id, args.registry, args.document_id)):
                raise ValueError("Advanced demo inputs require --workspace or --resume")
            from c1_requirement_quality.wizard import launch
            return launch()
        if args.command == "demo":
            from c1_requirement_quality.demo_workflow import guided_demo
            if args.resume and any((args.input_path, args.srs, args.run_id, args.registry, args.document_id)):
                raise ValueError("Resume uses saved session inputs; do not supply new run arguments")
            if args.wizard:
                if not args.resume:
                    raise ValueError("--wizard requires --resume")
                from c1_requirement_quality.demo_workflow import DemoSession
                from c1_requirement_quality.wizard import Wizard
                Wizard(Path(args.resume).parent).review(DemoSession(Path(args.resume)), start_guided=True)
                return 0
            guided_demo(Path(args.resume or args.workspace), resume=bool(args.resume),
                        artifact=Path(args.input_path) if args.input_path else None,
                        source=Path(args.srs) if args.srs else None, run_id=args.run_id,
                        registry=Path(args.registry) if args.registry else None,
                        project_code=args.project_code, document_id=args.document_id)
            return 0
        if args.command == "generate-review-questions":
            from c1_requirement_quality.demo_workflow import DemoSession, _session_lock
            with _session_lock(Path(args.session)):
                generated = DemoSession(Path(args.session)).generate_review_questions(args.requirement_id)
                print(json.dumps(generated, indent=2, ensure_ascii=False))
            return 0
        if args.command in {"publish-approved", "export-refined"}:
            from c1_requirement_quality.demo_workflow import DemoSession, _session_lock
            workspace = Path(args.session)
            with _session_lock(workspace):
                session = DemoSession(workspace)
                if args.command == "publish-approved":
                    session.publish_approved(args.reviewer, args.confirm == "yes", requirement_ids=args.requirement_id)
                    print(f"[c1] authorized C1 output: {session.current}")
                else:
                    from c1_requirement_quality.refined_export import export_refined_srs
                    for name, path in export_refined_srs(session, Path(args.out)).items():
                        print(f"[c1] {name}: {path}")
            return 0
        if args.command == "propose-clarifications":
            from c1_requirement_quality.clarification_proposals import propose_clarifications_run
            propose_clarifications_run(Path(args.input_path), Path(args.srs), Path(args.out), args.requirement_id,
                defect_diagnostics=Path(args.defect_diagnostics) if args.defect_diagnostics else None,
                similarity_diagnostics=Path(args.similarity_diagnostics) if args.similarity_diagnostics else None,
                max_requests=args.max_requests, max_evidence_chars=args.max_evidence_chars,
                max_context_chars=args.max_context_chars)
            return 0
        if args.command == "diagnose-similarity":
            from c1_requirement_quality.ml.similarity_diagnostics import similarity_diagnostics_run
            similarity_diagnostics_run(Path(args.input_path), Path(args.out),
                                       model_dir=Path(args.model_dir) if args.model_dir else None,
                                       threshold=args.threshold, batch_size=args.batch_size,
                                       max_pairs=args.max_pairs)
            return 0
        if args.command == "diagnose-defects":
            from c1_requirement_quality.ml.ml_diagnostics import defect_diagnostics_run
            defect_diagnostics_run(Path(args.input_path), Path(args.out),
                                   model_dir=Path(args.model_dir) if args.model_dir else None,
                                   threshold=args.threshold)
            return 0
        if args.command in {"list-pairs", "review-pairs"}:
            from c1_requirement_quality.pair_applicability import pair_review_run
            pair_review_run(Path(args.input_path), Path(args.srs), Path(args.out),
                           previous_path=Path(args.previous) if args.previous else None,
                           actions_path=Path(args.actions) if args.command == "review-pairs" else None)
            return 0
        if args.command == "refine":
            refine_run(
                Path(args.input_path), Path(args.srs), Path(args.actions), Path(args.out)
            )
            return 0
        if args.command == "generate-candidates":
            from c1_requirement_quality.rewrite_generator import generate_candidates_run

            backend = None
            if args.backend == "groq":
                from c1_requirement_quality.groq_generator import GroqGeneratorBackend
                backend = GroqGeneratorBackend.from_environment()

            generate_candidates_run(
                Path(args.input_path),
                Path(args.srs),
                Path(args.out),
                clarification_answers_path=Path(args.clarification_answers) if args.clarification_answers else None,
                grounding_mode=args.grounding_mode,
                backend=backend,
            )
            return 0
        run(
            Path(args.srs),
            Path(args.out),
            args.run_id,
            args.project_code,
            Path(args.registry) if args.registry else None,
            args.grounding_mode,
            args.document_id,
        )
    except Exception as err:  # noqa: BLE001 - CLI boundary
        print(f"[c1] {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
