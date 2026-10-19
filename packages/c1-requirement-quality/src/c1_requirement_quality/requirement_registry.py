"""Document-scoped requirement identity; explicit legacy migration only."""
from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping


class RequirementRegistry:
    """Exact (context,text) identity per document, project-wide non-reused IDs.

    Indistinguishable duplicates are rejected. Legacy histories are read-only.
    """

    def __init__(self, path: Path, project_code: str) -> None:
        if not re.fullmatch(r"[A-Z0-9]{2,10}", project_code):
            raise ValueError("project_code must contain 2-10 uppercase letters or digits")
        self.path = Path(path)
        self.project_code = project_code
        self.active: dict[str, str] = {}
        self.retired: set[str] = set()
        self.next_number = 1
        self.documents: dict[str, dict[str, dict[str, str]]] = {}
        self._original = self.path.read_bytes() if self.path.exists() else None
        self.legacy = False
        if self._original is not None:
            data = json.loads(self._original.decode("utf-8-sig"))
            if data.get("project_code") != project_code:
                raise ValueError("Registry project code does not match")
            version = data.get("registry_version")
            if version not in (None, 2):
                raise ValueError("Unsupported registry version")
            self.legacy = version is None
            self.next_number = data["next_number"]
            self.retired = set(data["retired"])
            if self.legacy:
                self.active = data["active"]
            else:
                self.documents = data["documents"]
            self._validate()

    def _validate(self) -> None:
        active = list(self.active.values()) if self.legacy else [
            value for doc in self.documents.values() for value in doc["active"].values()
        ]
        ids = active + list(self.retired)
        pattern = re.compile(rf"REQ-{self.project_code}-([0-9]{{3,}})")
        if len(ids) != len(set(ids)) or any(not isinstance(i, str) or not pattern.fullmatch(i) for i in ids):
            raise ValueError("Registry contains invalid, reused or active/retired IDs")
        if not isinstance(self.next_number, int) or self.next_number < 1 or any(
            int(pattern.fullmatch(i).group(1)) >= self.next_number for i in ids
        ):
            raise ValueError("Registry next_number would reuse an existing ID")

    def _data(self) -> dict[str, object]:
        self._validate()
        return {"registry_version": 2, "project_code": self.project_code,
                "next_number": self.next_number, "documents": self.documents,
                "retired": sorted(self.retired)}

    def assert_writable(self) -> None:
        if self.legacy:
            raise ValueError("Legacy registry is read-only: establish ownership and explicitly export a mapped migration to a new registry")

    @contextmanager
    def publication_lock(self) -> Iterator[None]:
        """Serialize publishers and reject stale snapshots without replacing history.

        Crash recovery is manual: stop publishers for this exact registry, verify
        through the owning OS account/process supervisor that no publisher remains,
        inspect the registry and retained staging artifacts, then explicitly remove
        only its .lock file. Age alone never proves ownership or inactivity. Start
        a fresh invocation to re-read and validate registry state; never replay or
        merge staged state blindly. Do not remove a lock with uncertain ownership.
        """
        self.assert_writable()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_name(self.path.name + ".lock")
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as err:
            raise RuntimeError(f"Registry publication lock already exists: {lock}; verify publisher ownership/inactivity before manual recovery; never remove based only on age") from err
        try:
            os.close(handle)
            current = self.path.read_bytes() if self.path.exists() else None
            if current != self._original:
                raise RuntimeError("Registry changed while processing; retry with the current registry")
            yield
        finally:
            lock.unlink()  # only the transient lock created by this invocation

    def _commit_locked(self) -> None:
        data = (json.dumps(self._data(), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        fd, name = tempfile.mkstemp(prefix=self.path.name + ".pending-", dir=self.path.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        Path(name).replace(self.path)
        self._original = data

    def commit(self) -> None:
        with self.publication_lock():
            self._commit_locked()

    def assign_ids(self, texts: list[str], contexts: list[str] | None = None,
                   *, document_id: str = "default", persist: bool = True) -> list[str]:
        self.assert_writable()
        if not isinstance(document_id, str) or not document_id.strip():
            raise ValueError("document_id must be non-empty")
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Requirement text must not be empty")
        if contexts is None:
            contexts = [""] * len(texts)
        if len(contexts) != len(texts) or any(not isinstance(c, str) for c in contexts):
            raise ValueError("contexts must contain one string per requirement")
        keys = [json.dumps([context, text], ensure_ascii=False) for context, text in zip(contexts, texts, strict=True)]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate requirement text is indistinguishable within the same section context; disambiguate source sections")
        previous = self.documents.get(document_id, {"active": {}})["active"]
        updated = {}
        for key in keys:
            if key in previous:
                updated[key] = previous[key]
            else:
                updated[key] = f"REQ-{self.project_code}-{self.next_number:03d}"
                self.next_number += 1
        self.retired.update(value for key, value in previous.items() if key not in updated)
        self.documents[document_id] = {"active": updated}
        self.active = updated
        if persist:
            self.commit()
        return [updated[key] for key in keys]

    def export_legacy(self, destination: Path, document_id: str,
                      bindings: Mapping[str, tuple[str, str]]) -> RequirementRegistry:
        """Export reviewed legacy key -> (context,text) bindings to a NEW file.

        Preserves all IDs/retirements/high-water mark; never merges histories.
        """
        if not self.legacy or set(bindings) != set(self.active) or not document_id.strip():
            raise ValueError("Migration needs a legacy registry, document identity and bindings for every active key")
        if destination.exists():
            raise FileExistsError("Migration destination must be a new file")
        keys = [json.dumps(list(binding), ensure_ascii=False) for binding in bindings.values()]
        if any(len(binding) != 2 or any(not isinstance(v, str) or not v.strip() for v in binding) for binding in bindings.values()) or len(keys) != len(set(keys)):
            raise ValueError("Migration bindings must be distinct non-empty (context, text) pairs")
        migrated = RequirementRegistry(destination, self.project_code)
        if migrated._original is not None:
            raise FileExistsError("Migration destination was created concurrently")
        migrated.next_number = self.next_number
        migrated.retired = self.retired.copy()
        migrated.documents[document_id] = {"active": dict(zip(keys, (self.active[k] for k in bindings), strict=True))}
        migrated.commit()
        return migrated
