
"""C1 requirement quality command line interface."""

from __future__ import annotations

import argparse
import json
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
from c1_requirement_quality.refinement import process_refinement_actions
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
    sub = parser.add_subparsers(dest="command", required=True)

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

    return parser


def _validate_contract_artifact(artifact: dict[str, object]) -> None:
    """Validate a C1 artifact against the unchanged local v1.0.0 schemas."""
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    schema_dir = Path(__file__).resolve().parents[3] / "contracts" / "schemas"
    schema = json.loads((schema_dir / "c1-validated-requirements.schema.json").read_text(encoding="utf-8"))
    common = json.loads((schema_dir / "common.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource(common["$id"], Resource.from_contents(common))
    validator = Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(artifact), key=lambda error: list(map(str, error.absolute_path)))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise ValueError(f"C1 contract validation failed at {location}: {first.message}")


def refine_run(input_path: Path, srs: Path, actions_path: Path, out: Path) -> None:
    """Evaluate alternatives and human actions without modifying the input run."""
    for path, label in ((input_path, "validated requirements"), (srs, "SRS"), (actions_path, "actions")):
        if not path.is_file():
            raise FileNotFoundError(f"{label} file not found: {path}")
    if out.exists():
        raise FileExistsError(f"output run folder already exists: {out}")

    artifact = json.loads(input_path.read_text(encoding="utf-8-sig"))
    actions = json.loads(actions_path.read_text(encoding="utf-8-sig"))
    _validate_contract_artifact(artifact)
    srs_text, manifest = verify_source(input_path, srs)
    refined, diagnostics = process_refinement_actions(artifact, actions, srs_text)
    _validate_contract_artifact(refined)

    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".c1-refine-pending-", dir=out.parent))
    c1_dir = staging / "c1"
    c1_dir.mkdir()
    (c1_dir / "validated_requirements.json").write_text(
        json.dumps(refined, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (c1_dir / "refinement_diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    copy_source_bundle(input_path, c1_dir, manifest)
    _validate_contract_artifact(json.loads((c1_dir / "validated_requirements.json").read_text(encoding="utf-8")))
    verify_source(c1_dir / "validated_requirements.json", srs)
    staging.rename(out)
    c1_dir = out / "c1"
    print(f"[c1] wrote refined requirements to {c1_dir / 'validated_requirements.json'}")
    print(f"[c1] wrote refinement diagnostics to {c1_dir / 'refinement_diagnostics.json'}")


def _run_staged(
    srs: Path,
    out: Path,
    run_id: str,
    project_code: str = "EX",
    registry: RequirementRegistry | None = None,
    grounding_mode: str = "lexical",
    document_id: str | None = None,
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

    # Extract normalized full text and requirements from any supported SRS format
    c1_dir = out / "c1"
    c1_dir.mkdir()
    doc, manifest = snapshot_source(c1_dir, srs, document_identity(srs, document_id))
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

    # Stage B: run deterministic lexical quality analysis.
    # analyse_requirements preserves input order and is independent per requirement.
    quality_findings: list[list[dict[str, str]]] = analyse_requirements(
        [str(r["original_text"]) for r in requirements]
    )

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

    # Stage C: run deterministic grounding analysis against the raw SRS text.
    rag_analyser = (
        RAGGroundingAnalyser(srs_text, verifier=FactVerifier(LocalNLI()))
        if grounding_mode == "rag" else None
    )
    grounding_results: list[dict[str, object]] = [
        (rag_analyser.analyse(str(r["original_text"])) if rag_analyser else
         analyse_grounding(str(r["original_text"]), srs_text))
        for r in requirements
    ]
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

    if rag_analyser:
        diagnostics_path = out / "c1" / "rag_diagnostics.json"
        diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
        diagnostics_path.write_text(json.dumps([
            {"requirement_id": req["requirement_id"], "diagnostics": result.get("diagnostics", []),
             "errors": result.get("errors", [])}
            for req, result in zip(requirements, grounding_results, strict=True)
        ], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
    seal_source(c1_dir, manifest)


def run(srs: Path, out: Path, run_id: str, project_code: str = "EX",
        registry_path: Path | None = None, grounding_mode: str = "lexical",
        document_id: str | None = None) -> None:
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
        _run_staged(srs, staging, run_id, project_code, registry, grounding_mode, document_id)
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
    print(f"[c1] wrote validated requirements to {target / 'validated_requirements.json'}")
    print(f"[c1] registry: {registry.path}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "refine":
            refine_run(
                Path(args.input_path), Path(args.srs), Path(args.actions), Path(args.out)
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
