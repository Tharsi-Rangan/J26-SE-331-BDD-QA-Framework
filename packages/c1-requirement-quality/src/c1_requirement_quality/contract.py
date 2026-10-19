"""Contract artifact validation against externally provided shared schemas.

Source checkouts discover packages/contracts/schemas. Standalone installations
must set C1_CONTRACT_SCHEMA_DIR to the unchanged shared schema directory containing
c1-validated-requirements.schema.json and common.schema.json. Schemas are not
copied into this package; an explicit configuration never silently falls back.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def get_schema_dir() -> Path:
    """Locate the shared contracts/schemas directory."""
    env_dir = os.environ.get("C1_CONTRACT_SCHEMA_DIR")
    if env_dir:
        candidate = Path(env_dir)
        if not candidate.is_dir():
            raise FileNotFoundError(f"C1_CONTRACT_SCHEMA_DIR is not a directory: {candidate}")
        return candidate

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts" / "schemas"
        if candidate.is_dir():
            return candidate
        candidate_repo = parent / "packages" / "contracts" / "schemas"
        if candidate_repo.is_dir():
            return candidate_repo

    return Path(__file__).resolve().parents[3] / "contracts" / "schemas"


def validate_contract_artifact(artifact: dict[str, object], *, schema_dir: Path | None = None) -> None:
    """Validate a C1 artifact against the unchanged local v1.0.0 schemas."""
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    target_dir = schema_dir or get_schema_dir()
    schema_file = target_dir / "c1-validated-requirements.schema.json"
    common_file = target_dir / "common.schema.json"

    if not schema_file.is_file() or not common_file.is_file():
        raise FileNotFoundError(
            f"Contract schemas not found in {target_dir}. Set C1_CONTRACT_SCHEMA_DIR "
            "to the shared directory containing c1-validated-requirements.schema.json "
            "and common.schema.json; standalone installations require these external schemas."
        )

    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    common = json.loads(common_file.read_text(encoding="utf-8"))
    registry = Registry().with_resource(common["$id"], Resource.from_contents(common))
    validator = Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(artifact), key=lambda error: list(map(str, error.absolute_path)))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise ValueError(f"C1 contract validation failed at {location}: {first.message}")


# Backward-compatibility alias
_validate_contract_artifact = validate_contract_artifact
