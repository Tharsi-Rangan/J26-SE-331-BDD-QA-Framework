
"""C1 requirement quality command line interface."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from c1_requirement_quality.quality_analyser import analyse_requirements
from c1_requirement_quality.requirement_registry import RequirementRegistry
from c1_requirement_quality.srs_parser import extract_requirements

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
    run_parser.add_argument("--project-code", default="EX", help="requirement ID prefix")
    run_parser.add_argument(
        "--registry",
        help="persistent registry file; defaults to .c1-state/requirement-registry.json",
    )
    return parser


def run(
    srs: Path,
    out: Path,
    run_id: str,
    project_code: str = "EX",
    registry_path: Path | None = None,
) -> None:
    """Parse an SRS, run quality analysis, and write contract-compliant artifacts.

    Stage A: extract requirements with stable REQ-IDs.
    Stage B (this commit): populate defects and validation.checks.quality using
    the deterministic lexical quality_analyser.

    Tier assignment and grounding analysis are not yet wired; those decisions
    are pending Planner confirmation and are implemented in a later task.
    """
    if not srs.is_file():
        raise FileNotFoundError(f"SRS file not found: {srs}")
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(f"Invalid run_id: {run_id}")

    extracted = extract_requirements(srs)
    if not extracted:
        raise ValueError("SRS contains no requirements; no C1 artifact was generated")

    if registry_path is None:
        registry_path = Path(".c1-state") / "requirement-registry.json"

    registry = RequirementRegistry(registry_path, project_code)
    texts = [str(item["original_text"]) for item in extracted]
    requirement_ids = registry.assign_ids(texts)

    requirements: list[dict[str, object]] = []
    for item, requirement_id in zip(extracted, requirement_ids, strict=True):
        requirements.append(
            {
                "requirement_id": requirement_id,
                "source": item["source"],
                "original_text": item["original_text"],
            }
        )

    # Stage B: run deterministic lexical quality analysis.
    # analyse_requirements preserves input order and is independent per requirement.
    quality_findings: list[list[dict[str, str]]] = analyse_requirements(
        [str(r["original_text"]) for r in requirements]
    )

    c1_dir = out / "c1"
    c1_dir.mkdir(parents=True, exist_ok=True)
    output_path = c1_dir / "parsed_requirements.json"
    output_path.write_text(
        json.dumps(requirements, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    validated_requirements = {
        "contract": "c1.validated-requirements",
        "schema_version": "1.0.0",
        "producer": {"component": "C1", "tool_version": TOOL_VERSION},
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_document": {
            "name": srs.name,
            "project_code": project_code,
            "path": srs.name,
            "redaction_applied": False,
        },
        "requirements": [
            {
                **requirement,
                "defects": findings,
                # Tier thresholds are not documented in this repository.
                # They must be confirmed on the Planner board before
                # implementation. Kept at the conservative sentinel until
                # that decision is recorded.
                "tier": "TIER_3_ESCALATE",
                "grounding": {"status": "not_applicable"},
                # The frozen contract has no unchecked status. This
                # conservative value prevents downstream readiness.
                "consistency": {
                    "status": "potential_conflict",
                    "related_requirement_ids": [],
                    "conflicts": [],
                },
                "validation": {
                    # validation.status remains "needs_review": grounding and
                    # consistency checks are still skipped, and human_decision
                    # is still pending. A requirement is never promoted to
                    # "passed" by quality analysis alone.
                    "status": "needs_review",
                    "checks": {
                        "quality": "fail" if findings else "pass",
                        "grounding": "skipped",
                        "consistency": "skipped",
                        "bdd_readiness": "skipped",
                    },
                },
                "human_decision": "pending",
                "final_text": requirement["original_text"],
                "bdd_ready": False,
            }
            for requirement, findings in zip(
                requirements, quality_findings, strict=True
            )
        ],
    }
    validated_output_path = c1_dir / "validated_requirements.json"
    validated_output_path.write_text(
        json.dumps(validated_requirements, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[c1] wrote {len(requirements)} requirements to {output_path}")
    print(f"[c1] wrote validated requirements to {validated_output_path}")
    print(f"[c1] registry: {registry_path}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run(
            Path(args.srs),
            Path(args.out),
            args.run_id,
            args.project_code,
            Path(args.registry) if args.registry else None,
        )
    except Exception as err:  # noqa: BLE001 - CLI boundary
        print(f"[c1] {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
