
"""Persistent requirement ID registry for C1."""

from __future__ import annotations

import json
from pathlib import Path


class RequirementRegistry:
    """Manage stable requirement IDs for a single project."""

    def __init__(self, path: Path, project_code: str) -> None:
        if not project_code.isascii() or not (
            2 <= len(project_code) <= 10
        ) or not project_code.isalnum() or project_code != project_code.upper():
            raise ValueError(
                "project_code must contain 2-10 uppercase letters or digits"
            )

        self.path = path
        self.project_code = project_code
        self.active: dict[str, str] = {}
        self.retired: set[str] = set()
        self.next_number = 1

        if self.path.exists():
            self._load()

    def _load(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))

        if data.get("project_code") != self.project_code:
            raise ValueError("Registry project code does not match")

        self.active = data.get("active", {})
        self.retired = set(data.get("retired", []))
        self.next_number = data.get("next_number", 1)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "project_code": self.project_code,
            "next_number": self.next_number,
            "active": self.active,
            "retired": sorted(self.retired),
        }

        temporary_path = self.path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(data, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(self.path)

    def assign_ids(self, texts: list[str]) -> list[str]:
        """Assign IDs to exact-text matches and retire removed requirements."""
        if any(not text.strip() for text in texts):
            raise ValueError("Requirement text must not be empty")

        if len(set(texts)) != len(texts):
            raise ValueError("Duplicate requirement text is ambiguous")

        previous = self.active.copy()
        updated: dict[str, str] = {}
        assigned: list[str] = []

        for text in texts:
            requirement_id = previous.get(text)

            if requirement_id is None:
                requirement_id = f"REQ-{self.project_code}-{self.next_number:03d}"
                self.next_number += 1

            updated[text] = requirement_id
            assigned.append(requirement_id)

        for text, requirement_id in previous.items():
            if text not in updated:
                self.retired.add(requirement_id)

        self.active = updated
        self._save()
        return assigned