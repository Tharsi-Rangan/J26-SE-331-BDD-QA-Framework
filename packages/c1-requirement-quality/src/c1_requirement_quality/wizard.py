"""Plain-terminal presentation over the authoritative Stage 4C/4D services."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
from typing import Any
import uuid

from .demo_workflow import DemoSession, _session_lock
from .refinement import stable_candidate_id
from .validation_lifecycle import clarification_resolution
from .effective_consistency import assess, context_from_state
from .bdd_readiness import is_single_requirement_no_peers
from .lexical_patterns import PLACEHOLDER_PATTERN

SUPPORTED = {".txt", ".md", ".markdown", ".docx", ".pdf", ".json"}
TIERS = {"TIER_1_AUTO_REFINE": "Tier 1 (structural refinement)",
         "TIER_2_CLARIFY": "Tier 2 (needs clarification)",
         "TIER_3_ESCALATE": "Tier 3 (manual escalation)"}
TIER_DESCRIPTIONS = {
    "TIER_1_AUTO_REFINE": "Tier 1: Minor wording or structural improvement.",
    "TIER_2_CLARIFY": "Tier 2: Missing or unclear information requiring clarification.",
    "TIER_3_ESCALATE": "Tier 3: Severe issue, conflict or manual review required.",
}
HELP = ("Enter the number beside an option, then press Enter. Back returns without saving. "
        "Type pause at a menu or use Ctrl+C to pause safely. Answers and selected rewrites need separate approval; "
        "approval cannot bypass quality, grounding or consistency checks.\n\n"
        "What is an SRS?\n"
        "  SRS (Software Requirements Specification): The source document describing system obligations.\n\n"
        "What is BDD?\n"
        "  BDD (Behaviour-Driven Development): An automated testing approach converting requirements into testable Given/When/Then scenarios. Requirements must be clear, complete and conflict-free to be BDD-ready.\n\n"
        "Understanding Quality Tiers:\n"
        "  Tier 1: Minor wording or structural improvement.\n"
        "  Tier 2: Missing or unclear information requiring clarification.\n"
        "  Tier 3: Severe issue, conflict or manual review required.")

STAGES = {"read": "Read SRS document", "extract": "Extract and identify requirements",
          "quality": "Rule-based quality checks", "grounding": "RAG grounding and consistency checks",
          "tier": "Tier classification", "ml": "Fine-tuned ML classification", "review": "Prepare human review"}


class AnalysisProgress:
    """Presentation of real service events; no timing estimates or decision state."""

    def __init__(self, tell=print):
        self.tell = tell
        self.states = dict.fromkeys(STAGES, "pending")
        self.details = dict.fromkeys(STAGES, "")
        self.live = None
        self.stream = sys.stdout

    def __enter__(self):
        if self.tell is print and self.stream.isatty() and os.environ.get("TERM") != "dumb":
            try:
                from rich.console import Console
                from rich.live import Live
                from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
                self.bar = Progress(SpinnerColumn(), TextColumn("Analysis stages"), BarColumn(),
                                    TextColumn("{task.completed:.0f} / {task.total:.0f}"))
                self.task = self.bar.add_task("Analysis", total=len(STAGES))
                self.live = Live(self.render(), console=Console(file=self.stream), refresh_per_second=8)
                self.live.start()
            except (ImportError, OSError, ValueError):
                if self.live: self.live.stop()
                self.live = None
        if self.live is None:
            self.tell(f"\nStep 2 - Analyse SRS | 0 / {len(STAGES)} stages completed")
            for key, label in STAGES.items(): self.tell("[PENDING] " + label)
        self.tell("[SKIPPED] Optional AI diagnostics: Groq disabled. Local RAG grounding and DistilBERT are mandatory.")
        return self

    def render(self):
        from rich.console import Group
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
        table = Table.grid(padding=(0, 2))
        for key, label in STAGES.items():
            status = self.states[key]
            color = {"completed": "green", "running": "cyan", "failed": "red", "skipped": "yellow"}.get(status, "dim")
            marker = "OK"
            try:
                "\u2713".encode(self.stream.encoding or "utf-8")
                marker = "\u2713"
            except UnicodeEncodeError:
                pass
            table.add_row(Text((marker + " " if status == "completed" else "") + status.title(), style=color),
                          Text(label), Text(self.details[key]))
        return Panel(Group(table, self.bar), title="Step 2 - Analyse SRS", border_style="blue")

    def update(self, stage, status, detail=""):
        if stage not in STAGES or status not in {"pending", "running", "completed", "skipped", "failed"}:
            raise ValueError("Unknown analysis progress event")
        self.states[stage], self.details[stage] = status, detail
        completed = sum(s == "completed" for s in self.states.values())
        if self.live:
            self.bar.update(self.task, completed=completed)
            if status == "failed" or completed == len(STAGES): self.bar.stop_task(self.task)
            self.live.update(self.render(), refresh=True)
        else:
            indicator = " ..." if status == "running" else ""
            self.tell(f"[{status.upper()}] {STAGES[stage]}{indicator}" + (" - " + detail if detail else ""))
            self.tell(f"Analysis progress [{('#' * completed).ljust(len(STAGES), '-')}]: {completed} / {len(STAGES)} stages completed")

    def __exit__(self, kind, error, traceback):
        if error is not None:
            active = next((k for k, s in self.states.items() if s == "running"), None)
            if active is None: active = next((k for k, s in self.states.items() if s == "pending"), "review")
            detail = ("No requirements recognised; try explicit requirement IDs with their statement text."
                      if "SRS contains no requirements" in str(error) else "Stage stopped; see error Details.")
            self.update(active, "failed", detail)
        if self.live: self.live.stop()


def validate_source(value: str) -> Path:
    path = Path(value.strip().strip('"')).expanduser().resolve()
    if not path.is_file():
        raise ValueError("File not found. Paste the full path to an existing SRS file.")
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError("Supported files: TXT, MD, MARKDOWN, DOCX, PDF and structured JSON.")
    with path.open("rb") as stream:
        if not stream.read(1):
            raise ValueError("The selected document is empty.")
    return path


def browse_file() -> str:
    """Optional Windows dialog; importing Tk is never required for text menus."""
    if os.name != "nt":
        raise RuntimeError("Native browsing is available on Windows. Choose Paste path instead.")
    import tkinter as tk
    from tkinter.filedialog import askopenfilename
    root = tk.Tk()
    try:
        root.withdraw()
        return askopenfilename(title="Select an SRS document", filetypes=[
            ("SRS documents", "*.txt *.md *.markdown *.docx *.pdf *.json")])
    finally:
        root.destroy()


def safe_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Safely and atomically write content to path; clean up temp files on error."""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with tmp_path.open("w", encoding=encoding, newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        tmp_path.replace(path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def _format_markdown_quote(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return "> *(Empty statement)*"
    return "\n".join(f"> {line}" if line.strip() else ">" for line in lines)


def _indent_text(text: str, prefix: str = "    ") -> str:
    lines = text.splitlines()
    if not lines:
        return f"{prefix}(Empty)"
    return "\n".join(f"{prefix}{line}" for line in lines)


def _extract_requirement_blockers(row: dict[str, Any], record: dict[str, Any] | None,
                                  rows: list[dict[str, Any]], state: dict[str, Any]) -> list[str]:
    """Derive all active blockers strictly from authoritative persisted session data."""
    if row.get("bdd_ready"):
        return []

    rid = row["requirement_id"]
    rec = record or {}
    orig_text = row.get("original_text", "")
    unresolved = clarification_resolution(rec, orig_text, [])["unresolved_questions"] if rec else []
    blockers = []

    if row.get("tier") != "TIER_1_AUTO_REFINE" and row.get("human_decision") not in {"approved", "edited"}:
        blockers.append(f"Assigned to {TIERS.get(row.get('tier'), row.get('tier'))} (requires clarification or manual review)")
    if rec.get("escalation_active"):
        blockers.append("Active escalation is unresolved")
    if unresolved:
        blockers.append(f"{len(unresolved)} unresolved clarification question(s)")
    if row.get("defects"):
        blockers.append(f"{len(row['defects'])} detected quality defect(s)")

    context = context_from_state(state)
    c = assess(rid, rows, state["requirements"], context)
    if c.get("check") != "pass" and not is_single_requirement_no_peers(c):
        if c.get("status") == "conflict":
            blockers.append("Deterministic consistency conflict with peer requirement")
        else:
            blockers.append("Unresolved consistency comparison obligations remain blocking")

    if row.get("human_decision") == "pending":
        blockers.append("Pending explicit human review and approval")
    elif row.get("human_decision") == "rejected":
        blockers.append("Selected rewrite candidate was rejected; new rewrite or reconsideration required")

    grounding_status = row.get("grounding", {}).get("status")
    if grounding_status not in {"supported", "not_analyzed", None}:
        blockers.append(f"Grounding status is {grounding_status} (unsupported by source evidence)")

    if not blockers:
        blockers.append("All gates must pass before BDD readiness is certified")

    return blockers


def _categorize_consistency_pairs(session: DemoSession, rows: list[dict[str, Any]], state: dict[str, Any]):
    """Distinguish confirmed deterministic conflicts from unresolved/unassessed comparisons."""
    pairs = session.consistency_pairs(gate_policy=True)
    resolutions = {}
    context = context_from_state(state)
    records = state.get("requirements", {})
    for r in rows:
        c_res = assess(r["requirement_id"], rows, records, context)
        resolutions.update({p["pair_id"]: p["resolution"] for p in c_res.get("effective_review", {}).get("pairs", [])})

    confirmed_conflicts = []
    unresolved_comparisons = []
    resolved_comparisons = []

    for pair in pairs:
        det = pair.get("current_deterministic", {})
        det_class = det.get("classification", "unassessed")
        decision = pair.get("decision", "unresolved")
        pair_id = pair.get("pair_id", "")
        effective_res = resolutions.get(pair_id, "deterministic_consistent" if det_class == "consistent" else "unresolved")

        is_conflict = (det_class == "conflict" or decision == "conflict_confirmed" or effective_res == "conflict")

        info = {
            "pair_id": pair_id,
            "requirement_ids": pair.get("requirement_ids", []),
            "current_deterministic": det,
            "decision": decision,
            "effective_resolution": effective_res,
            "evidence": pair.get("evidence", {}),
            "invalidation": pair.get("invalidation"),
        }

        if is_conflict:
            confirmed_conflicts.append(info)
        elif effective_res in {"consistent_within_scope", "not_applicable", "deterministic_consistent"}:
            resolved_comparisons.append(info)
        else:
            unresolved_comparisons.append(info)

    return confirmed_conflicts, unresolved_comparisons, resolved_comparisons


def generate_markdown_report(session: DemoSession) -> str:
    """Generate offline human-readable Markdown report from authoritative persisted session data."""
    data, text, manifest, state = session.read()
    rows = data["requirements"]
    records = state["requirements"]
    context = context_from_state(state)

    source_name = session.source.name
    session_id = session.workspace.name
    total = len(rows)
    approved = sum(r.get("human_decision") in {"approved", "edited"} for r in rows)
    accepted_orig = sum(r.get("human_decision") == "not_required" for r in rows)
    pending = sum(r.get("human_decision") == "pending" for r in rows)
    rejected = sum(r.get("human_decision") == "rejected" for r in rows)
    bdd_ready = sum(bool(r.get("bdd_ready")) for r in rows)
    blocked = sum(not bool(r.get("bdd_ready")) for r in rows)

    if bdd_ready == total and total > 0:
        review_status = "Complete (All Requirements BDD-Ready)"
    elif pending == 0:
        review_status = f"Human Review Finished ({blocked} requirement(s) blocked by gates)"
    else:
        review_status = f"In Progress ({pending} requirement(s) pending human review)"

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def pct(count: int) -> str:
        return f"{(count / total * 100):.1f}%" if total > 0 else "0.0%"

    confirmed_conflicts, unresolved_comparisons, _ = _categorize_consistency_pairs(session, rows, state)

    lines = [
        "# C1 Requirement Quality and Refinement Report",
        "",
        "| Document Metadata | Value |",
        "| :--- | :--- |",
        f"| **Source Document** | `{source_name}` |",
        f"| **Session Identifier** | `{session_id}` |",
        f"| **Artifact Path** | `{session.current}` |",
        "| **Analysis Status** | Verified Contract Artifact |",
        f"| **Human Review Status** | {review_status} |",
        f"| **Report Generated** | `{now_iso}` |",
        "",
        "## 1. Executive Summary",
        "",
        "| Requirement Category | Count | Percentage |",
        "| :--- | :---: | :---: |",
        f"| **Total Extracted Requirements** | {total} | 100.0% |",
        f"| **Approved (Refined / Edited)** | {approved} | {pct(approved)} |",
        f"| **Accepted Original (No Rewrite Needed)** | {accepted_orig} | {pct(accepted_orig)} |",
        f"| **Pending Human Review** | {pending} | {pct(pending)} |",
        f"| **Rejected Candidates** | {rejected} | {pct(rejected)} |",
        f"| **BDD-Ready Requirements** | {bdd_ready} | {pct(bdd_ready)} |",
        f"| **Blocked Requirements** | {blocked} | {pct(blocked)} |",
        "",
        "## 2. Requirement Details",
        "",
    ]

    for row in rows:
        rid = row["requirement_id"]
        record = records.get(rid, {})
        blockers = _extract_requirement_blockers(row, record, rows, state)
        decision = row.get("human_decision", "pending")
        is_ready = bool(row.get("bdd_ready"))
        tier_label = TIERS.get(row.get("tier"), row.get("tier", "Unknown Tier"))

        decision_labels = {
            "approved": "Approved (Refined)",
            "edited": "Edited & Approved",
            "not_required": "Accepted Original (No Rewrite Needed)",
            "pending": "Pending Human Review",
            "rejected": "Rejected",
        }
        human_decision_display = decision_labels.get(decision, decision.title())
        readiness_display = "READY" if is_ready else "BLOCKED"

        if decision in {"approved", "edited"} and row.get("selected_candidate_text"):
            refined_block = _format_markdown_quote(row["selected_candidate_text"])
        elif decision == "not_required":
            refined_block = "*(Original requirement accepted without modification)*"
        elif decision == "pending":
            refined_block = "*(Pending human review — no candidate approved yet)*"
        elif decision == "rejected":
            refined_block = "*(Candidate was rejected — awaiting revised candidate or manual rewrite)*"
        else:
            refined_block = "*(No refined text accepted)*"

        defects = row.get("defects", [])
        if defects:
            defect_lines = []
            for d in defects:
                dtype = d.get("defect_type", "QUALITY_DEFECT")
                dexp = d.get("explanation", "Quality defect detected.")
                defect_lines.append(f"- **[{dtype}]**: {dexp}")
            quality_block = "\n".join(defect_lines)
        else:
            quality_block = "- None detected."

        resolution = clarification_resolution(record, row.get("original_text", ""), [])
        unresolved_qs = resolution.get("unresolved_questions", [])
        recorded_questions = record.get("questions", {})
        if recorded_questions:
            q_lines = []
            for q in recorded_questions.values():
                q_status = q.get("status", "OPEN")
                q_text = q.get("text", "")
                q_lines.append(f"- **[{q_status}]** {q_text}")
            clarification_block = "\n".join(q_lines)
        elif unresolved_qs:
            clarification_block = "\n".join(f"- **[OPEN]** {q}" for q in unresolved_qs)
        else:
            clarification_block = "- None recorded."

        c = assess(rid, rows, records, context)
        if is_single_requirement_no_peers(c):
            consistency_block = "- Single requirement in document (no peer comparisons applicable)."
        elif c.get("check") == "pass":
            consistency_block = "- Consistent across evaluated scope (Passed all consistency checks)."
        elif c.get("status") == "conflict":
            conf_details = "; ".join(item.get("explanation", "Contradiction detected") for item in c.get("conflicts", []))
            consistency_block = f"- **[CONFLICT]** {conf_details}"
        else:
            consistency_block = "- Unresolved comparison obligations remain blocking (requires human review or modification)."

        if is_ready:
            blocker_block = "- None. Requirement meets all quality, grounding, consistency, and approval gates for BDD handover."
        else:
            blocker_block = "\n".join(f"- **[BLOCKER]** {b}" for b in blockers)

        lines.extend([
            f"### Requirement {rid}",
            "",
            f"- **Classification Tier**: {tier_label}",
            f"- **Human Decision**: {human_decision_display}",
            f"- **BDD Readiness**: **{readiness_display}**",
            "",
            "#### Original Statement",
            _format_markdown_quote(row.get("original_text", "")),
            "",
            "#### Accepted Refined Statement",
            refined_block,
            "",
            "#### Quality Findings",
            quality_block,
            "",
            "#### Clarification Questions",
            clarification_block,
            "",
            "#### Consistency Findings",
            consistency_block,
            "",
            "#### Active Blockers",
            blocker_block,
            "",
            "---",
            "",
        ])

    return "\n".join(lines).rstrip() + "\n"


def generate_quality_summary(session: DemoSession) -> str:
    """Generate offline human-readable plain-text quality summary from authoritative persisted session data."""
    data, text, manifest, state = session.read()
    rows = data["requirements"]
    records = state["requirements"]
    context = context_from_state(state)

    source_name = session.source.name
    session_id = session.workspace.name
    total = len(rows)

    tier_counts = {t: sum(r.get("tier") == t for r in rows) for t in TIERS}
    approved = sum(r.get("human_decision") in {"approved", "edited"} for r in rows)
    accepted_orig = sum(r.get("human_decision") == "not_required" for r in rows)
    pending = sum(r.get("human_decision") == "pending" for r in rows)
    rejected = sum(r.get("human_decision") == "rejected" for r in rows)
    bdd_ready = sum(bool(r.get("bdd_ready")) for r in rows)
    blocked = sum(not bool(r.get("bdd_ready")) for r in rows)

    total_defects = sum(len(r.get("defects", [])) for r in rows)

    unanswered_questions = 0
    total_unresolved_questions = 0
    requirements_with_open_questions = []

    for r in rows:
        rid = r["requirement_id"]
        rec = records.get(rid, {})
        resolution = clarification_resolution(rec, r.get("original_text", ""), [])
        unanswered = sum(q.get("status") in {"OPEN", "REOPENED"} for q in rec.get("questions", {}).values())
        unresolved = len(resolution.get("unresolved_questions", []))
        unanswered_questions += unanswered
        total_unresolved_questions += unresolved
        if unanswered or unresolved:
            open_qs = [q.get("text") for q in rec.get("questions", {}).values() if q.get("status") in {"OPEN", "REOPENED"}]
            if not open_qs and unresolved:
                open_qs = resolution.get("unresolved_questions", [])
            requirements_with_open_questions.append((rid, open_qs))

    confirmed_conflicts, unresolved_comparisons, _ = _categorize_consistency_pairs(session, rows, state)

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if bdd_ready == total and total > 0:
        review_status = "Complete (All Requirements BDD-Ready)"
    elif pending == 0:
        review_status = f"Human Review Finished ({blocked} requirement(s) blocked)"
    else:
        review_status = f"In Progress ({pending} requirement(s) pending human review)"

    def pct(count: int) -> str:
        return f"{(count / total * 100):.1f}%" if total > 0 else "0.0%"

    lines = [
        "=" * 80,
        "C1 REQUIREMENT QUALITY & REFINEMENT SUMMARY",
        "=" * 80,
        "",
        f"Source Document:      {source_name}",
        f"Session Identifier:   {session_id}",
        f"Artifact Path:        {session.current}",
        f"Generated At:         {now_iso}",
        "Analysis Status:      Verified Contract Artifact",
        f"Human Review Status:  {review_status}",
        "",
        "-" * 80,
        "1. REQUIREMENT COUNTS & TIER DISTRIBUTION",
        "-" * 80,
        f"Total Extracted Requirements: {total}",
        "",
        "Tier Distribution:",
        f"  - Tier 1 (structural refinement): {tier_counts.get('TIER_1_AUTO_REFINE', 0)} ({pct(tier_counts.get('TIER_1_AUTO_REFINE', 0))})",
        f"  - Tier 2 (needs clarification):   {tier_counts.get('TIER_2_CLARIFY', 0)} ({pct(tier_counts.get('TIER_2_CLARIFY', 0))})",
        f"  - Tier 3 (manual escalation):     {tier_counts.get('TIER_3_ESCALATE', 0)} ({pct(tier_counts.get('TIER_3_ESCALATE', 0))})",
        "",
        "Tier Definitions:",
        f"  - {TIER_DESCRIPTIONS.get('TIER_1_AUTO_REFINE', 'Tier 1')}",
        f"  - {TIER_DESCRIPTIONS.get('TIER_2_CLARIFY', 'Tier 2')}",
        f"  - {TIER_DESCRIPTIONS.get('TIER_3_ESCALATE', 'Tier 3')}",
        "",
        "Human Decision Summary:",
        f"  - Approved (Refined / Edited):    {approved}",
        f"  - Accepted Original:              {accepted_orig}",
        f"  - Pending Review:                 {pending}",
        f"  - Rejected Candidates:            {rejected}",
        "",
        "-" * 80,
        "2. QUALITY ISSUES DETECTED",
        "-" * 80,
        f"Total Quality Defects: {total_defects}",
        "",
    ]

    if total_defects == 0:
        lines.append("  No quality defects detected across extracted requirements.")
        lines.append("")
    else:
        for r in rows:
            defects = r.get("defects", [])
            if defects:
                lines.append(f"  Requirement {r['requirement_id']}: {len(defects)} defect(s)")
                for d in defects:
                    lines.append(f"    * [{d.get('defect_type', 'DEFECT')}] {d.get('explanation', '')}")
                lines.append("")

    lines.extend([
        "-" * 80,
        "3. OUTSTANDING CLARIFICATION QUESTIONS",
        "-" * 80,
        f"Unanswered Questions:       {unanswered_questions}",
        f"Total Unresolved Questions: {total_unresolved_questions}",
        "",
    ])

    if not requirements_with_open_questions:
        lines.append("  No outstanding clarification questions.")
        lines.append("")
    else:
        for rid, qs in requirements_with_open_questions:
            lines.append(f"  Requirement {rid}:")
            for q in qs:
                lines.append(f"    * [OPEN] {q}")
            lines.append("")

    lines.extend([
        "-" * 80,
        "4. CONSISTENCY ANALYSIS (CONFLICTS VS UNASSESSED COMPARISONS)",
        "-" * 80,
        f"Confirmed Deterministic Conflicts: {len(confirmed_conflicts)}",
    ])

    if confirmed_conflicts:
        for c in confirmed_conflicts:
            req_str = " / ".join(c["requirement_ids"])
            det_expl = c["current_deterministic"].get("explanation", "Contradiction detected")
            lines.append(f"  - Confirmed Conflict: {req_str}")
            lines.append(f"      Pair ID:       {c['pair_id']}")
            lines.append(f"      Explanation:   {det_expl}")
            lines.append("      Action Needed: Contradictory statements must be edited or rewritten.")
    else:
        lines.append("  (None detected)")

    lines.append("")
    lines.append(f"Unresolved / Unassessed Consistency Comparisons: {len(unresolved_comparisons)}")

    if unresolved_comparisons:
        for u in unresolved_comparisons:
            req_str = " / ".join(u["requirement_ids"])
            det_class = u["current_deterministic"].get("classification", "unassessed")
            det_expl = u["current_deterministic"].get("explanation", "No explicit numeric conflict")
            lines.append(f"  - Comparison: {req_str}")
            lines.append(f"      Pair ID:               {u['pair_id']}")
            lines.append(f"      Deterministic Finding: {det_class} ({det_expl})")
            lines.append(f"      Human Review Status:   {u['decision']}")
            lines.append("      Note: This comparison has not yet undergone explicit human consistency review")
            lines.append("            or text modification. It is NOT a confirmed deterministic conflict.")
    else:
        lines.append("  (None. All comparison obligations resolved or single requirement scope)")

    lines.append("")
    lines.extend([
        "-" * 80,
        "5. BDD READINESS SUMMARY",
        "-" * 80,
        f"BDD-Ready Requirements: {bdd_ready} / {total} ({pct(bdd_ready)})",
        f"Blocked Requirements:   {blocked} / {total} ({pct(blocked)})",
        "",
        "Status by Requirement:",
    ])

    for r in rows:
        rid = r["requirement_id"]
        rec = records.get(rid, {})
        is_ready = bool(r.get("bdd_ready"))
        blockers = _extract_requirement_blockers(r, rec, rows, state)
        orig_text = r.get("original_text", "")
        if is_ready:
            dec = r.get("human_decision", "")
            label = "Approved Refinement" if dec in {"approved", "edited"} else "Accepted Original"
            lines.append(f"  - {rid}: READY ({label})")
            if orig_text:
                lines.append("      Statement:")
                lines.append(_indent_text(orig_text, prefix="        "))
        else:
            lines.append(f"  - {rid}: BLOCKED")
            if orig_text:
                lines.append("      Statement:")
                lines.append(_indent_text(orig_text, prefix="        "))
            lines.append("      Active Blockers:")
            for b in blockers:
                lines.append(f"        * {b}")
    lines.append("")

    lines.extend([
        "-" * 80,
        "6. HUMAN ACTIONS STILL REQUIRED",
        "-" * 80,
    ])

    actions_needed = []
    if total_unresolved_questions > 0:
        actions_needed.append(f"Answer outstanding clarification questions ({total_unresolved_questions} question(s) open).")
    if confirmed_conflicts:
        actions_needed.append(f"Resolve confirmed deterministic consistency conflicts ({len(confirmed_conflicts)} conflict(s) active).")
    if unresolved_comparisons:
        actions_needed.append(f"Review unresolved consistency comparisons ({len(unresolved_comparisons)} comparison(s) pending review).")
    if pending > 0:
        actions_needed.append(f"Review and explicitly approve or accept pending requirements ({pending} requirement(s) pending).")
    reqs_with_defects = sum(bool(r.get("defects")) and not r.get("bdd_ready") for r in rows)
    if reqs_with_defects > 0:
        actions_needed.append(f"Address quality defects on blocked requirements ({reqs_with_defects} requirement(s) affected).")
    escalated = sum(records.get(r["requirement_id"], {}).get("escalation_active", False) for r in rows)
    if escalated > 0:
        actions_needed.append(f"Resolve active escalations ({escalated} requirement(s) escalated).")

    if actions_needed:
        for a in actions_needed:
            lines.append(f"  - {a}")
    else:
        lines.append("  - None. All requirements are approved and verified BDD-ready.")

    lines.append("")
    lines.extend([
        "-" * 80,
        "7. BDD HANDOVER POLICY & BLOCKER EXPLANATION",
        "-" * 80,
        "Requirements cannot be handed over to BDD automation while marked as BLOCKED.",
        "BDD (Behaviour-Driven Development) frameworks generate executable test specifications",
        "and automated test step definitions directly from requirement obligations. Handing over",
        "requirements with unresolved defects, unanswered ambiguities, unreviewed consistency",
        "comparisons, or pending approvals leads to invalid test criteria, false positive test suites,",
        "and untested system edge cases. Every requirement must be clear, complete, consistent,",
        "and explicitly approved by a human reviewer before it is certified BDD-ready.",
        "=" * 80,
    ])

    return "\n".join(lines).rstrip() + "\n"


def export_reports(session: DemoSession, out_dir: Path | None = None) -> tuple[Path, Path]:
    """Export human-readable Markdown report and Plain-text quality summary."""
    target_dir = (session.workspace / "reports") if out_dir is None else Path(out_dir).resolve()
    md_content = generate_markdown_report(session)
    txt_content = generate_quality_summary(session)

    md_path = target_dir / "refined_requirements.md"
    txt_path = target_dir / "quality_summary.txt"

    safe_write_text(md_path, md_content)
    safe_write_text(txt_path, txt_content)

    return md_path, txt_path


class Wizard:
    def __init__(self, root: Path, ask=input, tell=print, *, classifier=None, embedder=None, nli=None, verifier=None, groq_backend=None):
        self.root, self.ask, self.tell = root.resolve(), ask, tell
        self.classifier = classifier
        self.embedder = embedder
        self.nli = nli
        self.verifier = verifier
        self.groq_backend = groq_backend
        self.analysis_error_details = None

    def display(self, message, style=None):
        """Style terminal output without interpreting document text as markup."""
        if self.tell is print and sys.stdout.isatty() and os.environ.get("TERM") != "dumb":
            try:
                from rich.console import Console
                from rich.text import Text
                Console().print(Text(message, style=style or ""))
                return
            except (ImportError, OSError, ValueError):
                pass
        self.tell(message)

    def menu(self, title, options):
        while True:
            self.display("\n" + title, "bold cyan")
            for i, option in enumerate(options, 1):
                self.display(f"  {i}. {option}")
            value = self.ask("Choose a number (or help): ").strip().lower()
            if value in {"pause", "p"}:
                raise KeyboardInterrupt
            if value in {"help", "h"}:
                self.tell(HELP)
            elif value.isdigit() and 1 <= int(value) <= len(options):
                return int(value)
            else:
                self.display(f"Please enter one of the displayed numbers (between 1 and {len(options)}). Type 'help' for guidance or 'pause' to pause safely.", "yellow")

    def publish(self, session, action):
        rag = bool(session.read()[2].get("rag_policy"))
        self.tell("Review this change for " + action["requirement_id"])
        for answer in action.get("clarification_answers", []):
            self.tell("Answer: " + answer["answer"])
            if answer.get("replaces_span"): self.tell("Replaces: " + answer["replaces_span"])
        for question in action.get("clarification_questions", []):
            self.tell("Clarification question: " + question)
        if "selected_candidate_text" in action:
            self.tell("Candidate: " + action["selected_candidate_text"])
        if "human_decision" in action:
            self.tell("Human decision: " + action["human_decision"])
            if action["human_decision"] == "approved":
                rows = session.review_read()[0]["requirements"]
                row = next(r for r in rows if r["requirement_id"] == action["requirement_id"])
                candidate = next((c for c in row.get("candidates", [])
                                  if c["candidate_id"] == row.get("selected_candidate_id")), None)
                if candidate is None:
                    self.tell("Select a candidate before approving it.")
                    return False
                self.tell("Exact text to approve: " + candidate["text"])
                # Bind this confirmation to the displayed selection as well as the snapshot.
                action = {**action, "selected_candidate_id": candidate["candidate_id"]}
            elif action["human_decision"] == "not_required":
                row = next(r for r in session.read()[0]["requirements"]
                           if r["requirement_id"] == action["requirement_id"])
                self.tell("Exact original text to accept: " + row["original_text"])
        reviewer = self.ask("Your name or reviewer label (blank cancels): ").strip()
        if reviewer and self.ask("Record this change? Type yes to confirm: ").strip().lower() == "yes":
            with redirect_stdout(io.StringIO()):
                if rag:
                    session.review_action(action, reviewer, True)
                else:
                    session.apply(action, reviewer, True)
            self.tell("Approval intent recorded; publication and BDD readiness remain blocked."
                      if rag and action.get("human_decision") == "approved" else
                      "Saved and rechecked. Answering or selecting does not approve a requirement.")
            return True
        self.tell("Cancelled. No change recorded.")
        return False

    def source(self):
        while True:
            choice = self.menu("Import SRS Document", ["Browse Files", "Paste File Path", "Back"])
            if choice == 3:
                return None
            try:
                if choice == 1:
                    self.display("Opening Windows file picker...", "cyan")
                    value = browse_file()
                else:
                    value = self.ask("SRS file path (blank cancels): ")
                if value.strip():
                    source = validate_source(value)
                    size_bytes = source.stat().st_size
                    size_kb = size_bytes / 1024
                    self.display("\nSelected file: " + source.name, "bold cyan")
                    self.display("File type: " + source.suffix.lower().lstrip(".").upper())
                    self.display(f"File size: {size_kb:.1f} KB ({size_bytes} bytes)")
                    self.display("Source path: " + str(source))
                    self.display("Supported format: yes. Contents will be checked during extraction.", "green")
                    if self.menu("Confirm document before analysis", ["Analyse this document", "Back to import"]) == 1:
                        return source
                    continue
                self.display("Selection cancelled.", "yellow")
            except Exception as error:
                self.display(f"Unable to open document: {error}. You can paste a path instead.", "red")

    def create(self, source):
        self.root.mkdir(parents=True, exist_ok=True)
        # Full UUID paths plus exclusive mkdir in DemoSession prevent reuse/overwrite.
        workspace = self.root / ("session-" + uuid.uuid4().hex)
        run_id = datetime.now(timezone.utc).strftime("RUN-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.analysis_error_details = None
        output = sys.stdout
        try:
            with AnalysisProgress(self.tell) as display:
                def progress(stage, status, detail):
                    with redirect_stdout(output): display.update(stage, status, detail)
                with redirect_stdout(io.StringIO()):
                    session = DemoSession.create(workspace, source=source, run_id=run_id,
                        registry=workspace / "registry.json", stage_progress=progress,
                        mandatory_ml=True, classifier=self.classifier, mandatory_rag=True)
                # Completion requires publication and DemoSession's source/state checks.
                display.update("review", "completed", "Verified session ready for human review")
        except Exception as error:
            self.analysis_error_details = str(error)
            if "Mandatory ML classification incomplete" in str(error) or "Mandatory RAG grounding incomplete" in str(error):
                raise ValueError(str(error) + ". Analysis is incomplete; retained files are not a completed analysis.") from error
            if "SRS contains no requirements" in str(error):
                raise ValueError("The document was read, but no supported requirement statements were recognised. "
                    "Try numbered/ID-labelled statements or supported DOCX requirement heading/body blocks. "
                    "Retained diagnostic files have not been deleted.") from error
            raise ValueError("Analysis could not finish. Check that the file is readable and matches its format. "
                             "Existing sessions are preserved; technical information is available in Details.") from error
        self.display("Analysis complete. Verified session ready for human review.", "green")
        if session.meta.get("mandatory_rag"):
            self.display("Initial RAG analysis is available for grounded candidate review, clarification and approval intent. Final publication and BDD readiness remain blocked.", "yellow")
        return session

    def choose_session(self):
        paths = sorted(self.root.glob("session-*/session.json"), reverse=True)
        if not paths:
            self.display("No previous sessions found here. Import an SRS document first.", "yellow")
            return None
        labels = []
        for path in paths:
            # Listing cannot mutate or recover sessions, including interrupted sessions.
            import json
            try:
                sess = DemoSession(path.parent)
                data, _, _, state = sess.read()
                rows = data.get("requirements", [])
                total = len(rows)
                approved = sum(r.get("human_decision") in {"approved", "edited", "not_required"} for r in rows)
                pending = sum(r.get("human_decision") not in {"approved", "edited", "not_required"} for r in rows)
                bdd_ready = sum(bool(r.get("bdd_ready")) for r in rows)
                meta = sess.meta
                date = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                source_name = Path(meta["source"]).name
                labels.append(f"{source_name} (started {date}) | Extracted: {total} | Approved: {approved} | Pending: {pending} | BDD-ready: {bdd_ready}")
            except (ValueError, KeyError, OSError):
                try:
                    meta = json.loads(path.read_text(encoding="utf-8"))
                    date = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                    labels.append(f"{Path(meta['source']).name} (started {date}) [Unverified progress]")
                except Exception:
                    labels.append("Unavailable session (preserved for inspection)")
        index = self.menu("Previous sessions", labels + ["Back"])
        if index > len(paths):
            return None
        try:
            return DemoSession(paths[index - 1].parent)
        except (ValueError, KeyError, OSError) as error:
            self.display(f"Unable to open session: {error}", "red")
            return None

    def requirement(self, row, session=None):
        self.tell(f"\n{row['requirement_id']}: {row['original_text']}")
        tier_label = TIERS.get(row['tier'], row['tier'])
        tier_desc = TIER_DESCRIPTIONS.get(row['tier'], '')
        self.tell(f"Current tier: {tier_label} | Human review: {row['human_decision']}")
        if tier_desc:
            self.tell(f"Tier explanation: {tier_desc}")
        if not row["defects"]:
            self.tell("No deterministic quality issues detected; other checks still apply.")
        for defect in row["defects"]:
            desc = defect.get("message") or defect.get("description") or " - ".join(str(v) for v in defect.values())
            issue_type = (defect.get("issue_type") or defect.get("defect_type") or "").replace("_", " ")
            type_label = f" ({issue_type})" if issue_type else ""
            self.tell(f"Quality issue{type_label}: {desc}")
        blockers = [k.replace("_", " ") for k, v in row["validation"]["checks"].items() if v != "pass"]
        if session is not None:
            data, _, _, state = session.read()
            consistency = assess(row["requirement_id"], data["requirements"], state["requirements"], context_from_state(state))
            if is_single_requirement_no_peers(consistency) and "consistency" in blockers:
                blockers.remove("consistency")
        if row["human_decision"] not in {"approved", "edited", "not_required"}:
            blockers.append("explicit human approval pending")
        self.tell("Readiness blockers: " + (", ".join(blockers) or "See final readiness assessment"))

    def overview(self, session):
        data, _, _, state = session.read()
        rows = data["requirements"]
        total = len(rows)
        approved = sum(r["human_decision"] in {"approved", "edited"} for r in rows)
        accepted_original = sum(r["human_decision"] == "not_required" for r in rows)
        pending = sum(r["human_decision"] not in {"approved", "edited", "not_required"} for r in rows)
        bdd_ready = sum(bool(r.get("bdd_ready")) for r in rows)

        self.tell("\n" + "=" * 70)
        self.tell("Requirements Analysis Overview")
        self.tell("=" * 70)
        self.tell(f"Extracted requirements: {total} | Approved: {approved} | Accepted original: {accepted_original} | Pending review: {pending} | BDD-ready: {bdd_ready}")
        self.tell("-" * 70)

        rendered_rich = False
        if self.tell is print and sys.stdout.isatty() and os.environ.get("TERM") != "dumb":
            try:
                from rich.console import Console
                from rich.table import Table
                table = Table(title="Extracted Requirements Status", show_header=True, header_style="bold blue")
                table.add_column("ID", style="bold cyan", width=10)
                table.add_column("Tier", width=16)
                table.add_column("Quality Issues", width=24)
                table.add_column("Review Status", width=15)
                table.add_column("BDD Ready", width=10)
                table.add_column("Next Action", width=25)

                for row in rows:
                    rid = row["requirement_id"]
                    tier_str = {"TIER_1_AUTO_REFINE": "Tier 1 (Minor)",
                                "TIER_2_CLARIFY": "Tier 2 (Clarify)",
                                "TIER_3_ESCALATE": "Tier 3 (Severe)"}.get(row["tier"], row["tier"])
                    if not row["defects"]:
                        defect_str = "None detected"
                    else:
                        defect_str = ", ".join((d.get("issue_type") or d.get("defect_type") or "defect").replace("_", " ") for d in row["defects"])
                    status_str = row["human_decision"].replace("_", " ").title()
                    ready_str = "[green]Ready[/green]" if row.get("bdd_ready") else "[yellow]Blocked[/yellow]"
                    action_code = self.next_action(session, row, state)
                    action_labels = {
                        "questions": "Clarify missing facts",
                        "consistency": "Resolve conflict",
                        "manual": "Manual rewrite / fix",
                        "candidates": "Review suggestions",
                        "approval": "Approve candidate",
                        "complete": "Ready for BDD",
                    }
                    action_str = action_labels.get(action_code, action_code)
                    table.add_row(rid, tier_str, defect_str, status_str, ready_str, action_str)
                Console().print(table)
                rendered_rich = True
            except Exception:
                rendered_rich = False

        if not rendered_rich:
            for row in rows:
                rid = row["requirement_id"]
                tier_short = {"TIER_1_AUTO_REFINE": "Tier 1 (Minor)",
                              "TIER_2_CLARIFY": "Tier 2 (Clarify)",
                              "TIER_3_ESCALATE": "Tier 3 (Severe)"}.get(row["tier"], row["tier"])
                if not row["defects"]:
                    issues = "None detected"
                else:
                    issues = ", ".join((d.get("issue_type") or d.get("defect_type") or "defect").replace("_", " ") for d in row["defects"])
                status = row["human_decision"].replace("_", " ").title()
                ready = "Ready" if row.get("bdd_ready") else "Blocked"
                action_code = self.next_action(session, row, state)
                action_labels = {
                    "questions": "Clarify missing facts",
                    "consistency": "Resolve conflict",
                    "manual": "Manual rewrite / fix",
                    "candidates": "Review suggestions",
                    "approval": "Approve candidate",
                    "complete": "Ready for BDD",
                }
                action = action_labels.get(action_code, action_code)
                self.tell(f"[{rid}] {tier_short} | Issues: {issues} | Status: {status} | BDD: {ready} | Next: {action}")
        self.tell("-" * 70)

    def findings(self, value, prefix=""):
        """Readable labels for service findings without requiring JSON literacy."""
        if isinstance(value, dict):
            for key, item in value.items():
                self.findings(item, prefix + key.replace("_", " ").capitalize() + ": ")
        elif isinstance(value, list):
            if not value: self.tell(prefix + "None")
            for item in value: self.findings(item, prefix)
        else:
            self.tell(prefix + str(value))

    def quality(self, session):
        index = 0
        while True:
            rows = session.read()[0]["requirements"]
            row = rows[index]
            self.requirement(row, session)
            choice = self.menu(f"Requirement {index + 1} of {len(rows)}", [
                "Next / Finish review" if index == len(rows) - 1 else "Next",
                "Previous",
                "Details",
                "Help",
                "View optional AI quality diagnostics (local DistilBERT)",
                "Back",
            ])
            if choice == 1:
                if index == len(rows) - 1:
                    self.tell("Quality review complete.")
                    return
                index += 1
            elif choice == 2: index = max(0, index - 1)
            elif choice == 3:
                for name in ("grounding", "consistency", "validation"):
                    self.findings(row[name], name.title() + " - ")
            elif choice == 4: self.tell(HELP + " Tier 1: structural fix; Tier 2: missing facts; Tier 3: manual escalation.")
            elif choice == 5: self.ai_diagnostics(session, requirement_id=row["requirement_id"])
            else: return

    def questions(self, session, requirement_id=None):
        data, _, _, state = session.review_read()
        questions = []
        for row in data["requirements"]:
            if requirement_id and row["requirement_id"] != requirement_id: continue
            record = state["requirements"][row["requirement_id"]]
            resolution = clarification_resolution(record, row["original_text"], [])
            unresolved = {q["question_id"] for q in resolution["assessments"] if not q["resolved"]}
            questions.extend((row, q) for q in record["questions"].values() if q["question_id"] in unresolved)
        if not questions:
            self.tell("No pending clarification questions.")
            choice = self.menu("Clarification options", [
                "Suggest clarification questions using Groq/Qwen (external API)",
                "Back",
            ])
            if choice == 1:
                self.suggest_clarifications_groq(session, requirement_id=requirement_id)
            return
        for row, question in questions:
            self.tell(row["requirement_id"] + ": " + row["original_text"])
            self.tell("Question: " + question["text"])
            self.tell("Guidance: Supply the missing fact so this requirement can be verified for BDD testing.")
            while True:
                _, _, _, latest_state = session.review_read()
                record = latest_state["requirements"][row["requirement_id"]]
                current = record["questions"][question["question_id"]]
                previous = next((a for a in record["answers"] if a["answer_id"] == current["current_answer_id"]), None)
                if previous:
                    self.tell("Previous answer (still unresolved): " + previous["answer"])
                choice = self.menu("Clarification", [
                    "Enter answer",
                    "Skip for now",
                    "Back",
                    "Help",
                    "Suggest clarification questions using Groq/Qwen (external API)",
                ])
                if choice == 3: return
                if choice == 2: break
                if choice == 4:
                    self.tell("Supply the missing fact. Saving records human evidence, not approval. "
                              "Use the exact original placeholder as the replaced span when applicable.")
                    continue
                if choice == 5:
                    self.suggest_clarifications_groq(session, requirement_id=row["requirement_id"])
                    continue
                answer = self.ask("Your answer (blank cancels): ").strip()
                if not answer: continue
                placeholders = [m.group(0) for m in PLACEHOLDER_PATTERN.finditer(row["original_text"]) if m.group(0).startswith("[")]
                suggested = placeholders[0] if placeholders else None
                if suggested:
                    self.tell(f"Detected placeholder needing replacement: {suggested}")
                    span_prompt = f"Exact placeholder or span replaced [press Enter for {suggested}]: "
                else:
                    span_prompt = "Exact original placeholder or span replaced (optional, Enter for none): "
                span = self.ask(span_prompt).strip()
                if not span and suggested:
                    span = suggested
                value = {"question_id": question["question_id"], "answer": answer}
                if span: value["replaces_span"] = span
                if self.menu("Answer preview: " + answer, ["Save answer", "Back"]) == 1:
                    if self.publish(session, {"requirement_id": row["requirement_id"], "clarification_answers": [value]}):
                        latest = session.review_read()[3]["requirements"][row["requirement_id"]]
                        resolved = clarification_resolution(latest, row["original_text"], [])
                        if next(q for q in resolved["assessments"] if q["question_id"] == question["question_id"])["resolved"]:
                            break
                        self.tell("This answer remains unresolved under the existing validation rules. Correct it or skip for now.")

    def suggest_clarifications_groq(self, session, requirement_id=None):
        self.tell("\n" + "=" * 70)
        self.tell("Optional Cloud Clarification Suggestions (Groq / Qwen)")
        self.tell("=" * 70)
        self.tell("Notice:")
        self.tell("  - This feature is optional, disabled by default, and accesses an external API.")
        self.tell("  - Transmits selected requirement text and existing clarification context to Groq Cloud.")
        self.tell("  - The full SRS document is NOT transmitted; only relevant excerpts are sent.")
        self.tell("  - Cloud usage is subject to Groq rate limits, provider terms, and potential charges.")
        self.tell("  - Model output is untrusted proposal text, NOT verified facts or approval.")
        self.tell("-" * 70)

        data, _, _, state = session.read()
        rows = data["requirements"]
        if not rows:
            self.tell("No requirements available in session.")
            return

        if requirement_id is None:
            opts = [f"{r['requirement_id']}: {r['original_text'][:60]}..." for r in rows] + ["Back"]
            sel = self.menu("Choose requirement for clarification suggestion", opts)
            if sel == len(opts):
                return
            target_row = rows[sel - 1]
        else:
            target_row = next((r for r in rows if r["requirement_id"] == requirement_id), None)
            if target_row is None:
                self.tell(f"Requirement {requirement_id} not found in session.")
                return

        rid = target_row["requirement_id"]
        self.tell(f"Selected requirement to transmit: [{rid}] {target_row['original_text']}")

        choice = self.menu(
            "Send clarification request to Groq Cloud API?",
            ["Confirm: Send request to Groq Cloud", "Cancel (Back)"],
        )
        if choice != 1:
            self.tell("Clarification request cancelled. No data transmitted.")
            return

        backend = self.groq_backend
        if backend is None:
            try:
                from c1_requirement_quality.groq_generator import GroqGeneratorBackend
                backend = GroqGeneratorBackend.from_environment()
            except Exception as err:
                self.tell(f"Groq configuration unavailable: {err}")
                return

        from c1_requirement_quality.clarification_proposals import _context, validate_proposal
        from c1_requirement_quality.source_integrity import verify_source, VerifiedWorkflowContext

        model_name = getattr(backend, "model", "qwen/qwen3.8-27b")
        try:
            source_text, _ = verify_source(session.current, session.source)
            context = _context(target_row, source_text, state, {}, max_evidence_chars=6000)
            self.tell(f"Requesting clarification proposals from Groq ({model_name})...")
            response = backend.propose_clarification(context)
            validated = validate_proposal(
                response["proposal"], context, source_text,
                rows, state["requirements"][rid],
                "docx" if session.source.suffix.lower() == ".docx" else None,
                workflow_context=VerifiedWorkflowContext(session.current, session.source),
            )
        except Exception as err:
            self.tell(f"Groq clarification request failed: {err}")
            return

        proposed_questions = validated.get("clarification_questions", [])
        if not proposed_questions:
            self.tell("No clarification questions proposed by the model.")
            return

        record = session.read()[3]["requirements"][rid]
        existing_texts = {q["text"].strip().casefold() for q in record["questions"].values()}

        self.tell(f"\nReceived {len(proposed_questions)} clarification proposal(s) from Groq:")
        for idx, q_item in enumerate(proposed_questions, 1):
            q_text = q_item["question"].strip()
            q_reason = q_item.get("reason", "").strip()
            self.tell(f"\nSuggestion {idx} of {len(proposed_questions)}:")
            self.tell(f"  Question: {q_text}")
            if q_reason:
                self.tell(f"  Rationale: {q_reason}")

            if q_text.casefold() in existing_texts:
                self.tell("  (This question is already recorded for this requirement.)")
                continue

            action_choice = self.menu(
                f"Action for suggestion {idx}",
                ["Accept question into session", "Edit question before adding", "Discard / Skip", "Back"],
            )
            if action_choice == 4:
                return
            if action_choice == 3:
                self.tell("Question discarded.")
                continue

            chosen_text = q_text
            if action_choice == 2:
                edited = self.ask("Edited question (blank cancels): ").strip()
                if not edited:
                    self.tell("Edit cancelled. Question discarded.")
                    continue
                chosen_text = edited

            if chosen_text.casefold() in existing_texts:
                self.tell("This question is already recorded for this requirement.")
                continue

            action = {
                "requirement_id": rid,
                "clarification_questions": [chosen_text],
            }
            if self.publish(session, action):
                existing_texts.add(chosen_text.casefold())
                self.tell(f"Added pending question to {rid}. It must now be answered by a human.")

    def candidates(self, session, requirement_id=None):
        if session.read()[2].get("rag_policy"):
            return self.rag_candidates(session, requirement_id)
        from .rewrite_generator import generate_candidates_run
        data, _, _, state = session.read()
        items = [(r["requirement_id"], c) for r in data["requirements"]
                 if requirement_id is None or r["requirement_id"] == requirement_id
                 for c in r.get("candidates", [])]
        if items:
            self.tell("Previously registered candidates (no automatic regeneration).")
        else:
            choice = self.menu("No registered candidates", [
                "Generate offline suggestions",
                "Write a manual rewrite",
                "Back",
                "Suggest rewrite candidates using Groq/Qwen (external API)",
            ])
            if choice == 3: return
            if choice == 2: return self.manual(session, requirement_id)
            if choice == 4:
                new_items = self.generate_candidates_groq(session, requirement_id)
                items = new_items or [(r["requirement_id"], c) for r in session.read()[0]["requirements"]
                                      if requirement_id is None or r["requirement_id"] == requirement_id
                                      for c in r.get("candidates", [])]
            else:
                path = session.workspace / "sidecars" / ("wizard-" + uuid.uuid4().hex + ".json")
                self.tell("Generating deterministic suggestions; AI models are not used...")
                with redirect_stdout(io.StringIO()):
                    generate_candidates_run(session.current, session.source, path)
                items = [(rid, c) for rid, c in session.candidates(path)
                         if requirement_id is None or rid == requirement_id]
        if not items: self.tell("No deterministic rewrite candidates available. Clarifications or manual rewriting may be needed.")
        for rid, candidate in items:
            # Each publication invalidates bound sidecars; return for fresh generation.
            row = next(r for r in session.read()[0]["requirements"] if r["requirement_id"] == rid)
            self.requirement(row, session)
            self.tell("Candidate rewrite: " + candidate["text"])
            self.tell("Grounding and validation findings:")
            assessment = self.candidate_assessment(session, rid, candidate)
            self.tell("Checks: " + ", ".join(k.replace("_", " ") + " " + v for k, v in assessment["validation"]["checks"].items()))
            self.tell("Missing information / blockers: " + assessment["validation"]["bdd_readiness"]["explanation"])
            status = state["requirements"][rid]["candidates"].get(candidate["candidate_id"], {}).get("status", "PROPOSED")
            self.tell("Candidate status: " + status)
            menu_options = [
                "Select candidate",
                "Edit candidate",
                "Reject candidate",
                "Skip",
                "Back",
                "Details",
                "Verify candidate against SRS evidence (local DeBERTa NLI)",
                "Suggest rewrite candidates using Groq/Qwen (external API)",
            ]
            choice = self.menu("Rewrite review", menu_options)
            while True:
                if choice == 6:
                    self.findings(assessment)
                elif choice == 7:
                    self.verify_candidate_evidence(session, rid, candidate, assessment=assessment)
                elif choice == 8:
                    new_items = self.generate_candidates_groq(session, rid)
                    if new_items:
                        items = new_items
                        break
                else:
                    break
                choice = self.menu("Rewrite review", menu_options)
            if choice == 8: continue
            if choice == 5: return
            if choice == 4: continue
            if status == "REJECTED" and choice == 1:
                self.tell("This candidate was rejected. Explicit reconsideration is required through the advanced workflow.")
                continue
            text = self.ask("Edited candidate (blank cancels): ").strip() if choice == 2 else candidate["text"]
            if not text: continue
            action = {"requirement_id": rid, "selected_candidate_text": text}
            if choice == 3: action["human_decision"] = "rejected"
            self.publish(session, action)
            return

    def rag_candidates(self, session, requirement_id=None):
        """Present journal-backed drafts using the existing review services."""
        data = session.review_read()[0]
        rows = [r for r in data["requirements"] if requirement_id is None or r["requirement_id"] == requirement_id]
        choice = self.menu("Grounded candidate review", ["Generate offline candidates", "Review saved candidates", "Write a manual rewrite", "Back"])
        if choice == 4:
            return
        if choice == 3:
            return self.manual(session, requirement_id)
        if choice == 1:
            self.tell("Generating deterministic proposals and verifying local RAG evidence. Missing facts are never invented.")
            result = session.generate_review_candidates([r["requirement_id"] for r in rows])
            for item in result["requirements"]:
                if not item["ranked_candidates"]:
                    self.tell(item["requirement_id"] + ": " + (item.get("zero_candidates_reason") or item.get("blocked_reason") or "Abstained; clarification needed."))
            rows = [r for r in session.review_read()[0]["requirements"] if requirement_id is None or r["requirement_id"] == requirement_id]
        for row in rows:
            for candidate in row["candidates"]:
                self.tell(row["requirement_id"] + ": " + candidate["text"])
                choice = self.menu("Candidate decision", ["Select candidate", "Verify evidence", "Reject candidate", "Back"])
                if choice == 4:
                    return
                if choice == 2:
                    self.verify_candidate_evidence(session, row["requirement_id"], candidate)
                    continue
                action = {"requirement_id": row["requirement_id"], "selected_candidate_text": candidate["text"]}
                if choice == 3:
                    action["human_decision"] = "rejected"
                self.publish(session, action)
                return

    def generate_candidates_groq(self, session, requirement_id=None):
        self.tell("\n" + "=" * 70)
        self.tell("Optional Cloud Candidate Rewrite Suggestions (Groq / Qwen)")
        self.tell("=" * 70)
        self.tell("Notice:")
        self.tell("  - This feature is optional, disabled by default, and accesses an external API.")
        self.tell("  - Transmits requirement text, defects, and clarification answers to Groq Cloud.")
        self.tell("  - The full SRS document is NOT transmitted; only relevant excerpts are sent.")
        self.tell("  - Cloud usage is subject to Groq rate limits, provider terms, and potential charges.")
        self.tell("  - Model proposals are strictly untrusted candidate rewrites.")
        self.tell("  - Every proposal is validated through deterministic quality, grounding,")
        self.tell("    consistency, and BDD readiness checks. Candidates remain PROPOSED until explicit human review.")
        self.tell("-" * 70)

        choice = self.menu(
            "Generate rewrite proposals using Groq Cloud API?",
            ["Confirm: Send request to Groq Cloud", "Cancel (Back)"],
        )
        if choice != 1:
            self.tell("Rewrite suggestion request cancelled. No data transmitted.")
            return []

        backend = self.groq_backend
        if backend is None:
            try:
                from c1_requirement_quality.groq_generator import GroqGeneratorBackend
                backend = GroqGeneratorBackend.from_environment()
            except Exception as err:
                self.tell(f"Groq configuration unavailable: {err}")
                return []

        from .rewrite_generator import generate_candidates_run

        path = session.workspace / "sidecars" / ("wizard-groq-" + uuid.uuid4().hex + ".json")
        model_name = getattr(backend, "model", "qwen/qwen3.8-27b")
        self.tell(f"Generating candidate rewrites with Groq ({model_name})...")
        try:
            with redirect_stdout(io.StringIO()):
                generate_candidates_run(session.current, session.source, path, backend=backend,
                                        requirement_ids=[requirement_id] if requirement_id else None)
        except Exception as err:
            self.tell(f"Groq candidate generation failed: {err}")
            return []

        if not path.is_file():
            self.tell("Candidate generation did not produce an output sidecar.")
            return []

        try:
            sidecar_data = json.loads(path.read_text(encoding="utf-8"))
            for req in sidecar_data.get("requirements", []):
                if requirement_id and req.get("requirement_id") != requirement_id:
                    continue
                req_rid = req.get("requirement_id", "")
                rejected = req.get("rejected_candidates", [])
                if rejected:
                    self.tell(f"Validation excluded {len(rejected)} proposal(s) for {req_rid}:")
                    for rej in rejected:
                        reason = rej.get("rejected_reason", "unknown")
                        txt = rej.get("text", "")
                        self.tell(f"  - [{reason}]: {txt}")
        except Exception as err:
            self.tell(f"Error parsing candidate diagnostics: {err}")

        try:
            new_items = [(r_id, c) for r_id, c in session.candidates(path)
                         if requirement_id is None or r_id == requirement_id]
            if new_items:
                self.tell(f"Loaded {len(new_items)} candidate suggestion(s) into review.")
            else:
                self.tell("No viable candidates were produced by Groq for this selection.")
            return new_items
        except Exception as err:
            self.tell(f"Unable to load candidate sidecar: {err}")
            return []

    def candidate_assessment(self, session, rid, candidate, *, grounding_context=None):
        from .refinement import _evaluate_candidate, _consistency_with_candidate, _candidate_validation
        from .tier_classifier import classify_tier
        data, text, manifest, state = session.read()
        from .source_integrity import VerifiedWorkflowContext
        policy_context = VerifiedWorkflowContext(session.current, session.source)
        if manifest.get("rag_policy") or grounding_context is not None:
            from .rag.candidate_validation import context_for_snapshot
            if manifest.get("rag_policy") and grounding_context is None and isinstance(session, DemoSession):
                grounding_context = session.candidate_grounding_context()
            grounding_context = context_for_snapshot(session.current, session.source, grounding_context)
        row = next(r for r in data["requirements"] if r["requirement_id"] == rid)
        record = state["requirements"][rid]
        evaluation = _evaluate_candidate(candidate["text"], text, row["original_text"], record,
            source_format="docx" if session.source.suffix.lower() == ".docx" else None,
            grounding_context=grounding_context, requirement_id=rid, workflow_context=policy_context)
        if manifest.get("rag_policy") and isinstance(session, DemoSession):
            data, _, _, state = session.review_read()
            record = state["requirements"][rid]
            for peer in data["requirements"]:
                draft = state["requirements"][peer["requirement_id"]]
                selected = draft["candidates"].get(draft["selected_candidate_id"])
                if selected is not None:
                    peer["final_text"] = selected["text"]
        consistency = _consistency_with_candidate(rid, candidate["text"], data["requirements"],
            state["requirements"], context_from_state(state))
        unresolved = clarification_resolution(record, row["original_text"], [])["unresolved_questions"]
        tier = classify_tier(evaluation["quality_findings"], evaluation["grounding"], consistency,
            original_text=row["original_text"], candidate_text=candidate["text"],
            unresolved_clarification=bool(unresolved))
        validation = _candidate_validation(evaluation, consistency, text=candidate["text"], tier=tier["tier"],
            clarification_questions=unresolved, escalation_active=record["escalation_active"])
        return {"evaluation": evaluation, "consistency": consistency, "tier": tier, "validation": validation}

    def verify_candidate_evidence(self, session, rid, candidate, assessment=None):
        """Register authoritative RAG evidence, or show legacy advisory verification."""
        if session.read()[2].get("rag_policy"):
            context = session.candidate_grounding_context()
            if stable_candidate_id(rid, candidate["text"]) not in context.receipts:
                self.tell("Verifying and registering local candidate evidence; the existing 3 GiB guard applies.")
                session.validate_candidate_evidence(rid, candidate["text"])
            result = self.candidate_assessment(session, rid, candidate)
            self.tell("Registered RAG evidence: " + str(result["evaluation"]["grounding"].get("verdict")))
            self.tell("Eligibility: " + str(result["evaluation"]["candidate_eligible"]) + "; no approval or publication implied.")
            self.tell("Candidate checks: " + str(result["validation"]["checks"]))
            self.tell("Tier assessment: " + result["tier"]["tier"])
            return
        self.tell("\n" + "=" * 70)
        self.tell("Verify Candidate against SRS Evidence (Local DeBERTa NLI)")
        self.tell("=" * 70)
        self.tell("Notice:")
        self.tell("  - This evidence verification feature is OPTIONAL, OFFLINE, and ADVISORY-ONLY.")
        self.tell("  - Execution uses local CPU and RAM to index source SRS chunks and run local DeBERTa NLI inference.")
        self.tell("  - Advisory predictions do NOT replace deterministic grounding analysis,")
        self.tell("    alter requirement tiers, or auto-approve/reject candidates.")
        self.tell("  - Dense similarity scores indicate topical relevance only, NOT proof of grounding.")
        self.tell("  - DeBERTa NLI predictions (entailment, neutral, contradiction) are uncalibrated")
        self.tell("    model outputs, NOT validated statistical probabilities.")
        self.tell("  - Source SRS chunks are evaluated as premises; candidate claims are hypotheses.")
        self.tell("-" * 70)

        choice = self.menu(
            "Load local models and verify candidate against source SRS evidence?",
            ["Confirm: Run local evidence verification", "Cancel (Back)"],
        )
        if choice != 1:
            self.tell("Evidence verification cancelled. Returning safely to candidate review.")
            return

        try:
            from c1_requirement_quality.ml.ml_diagnostics import available_memory_bytes
            avail = available_memory_bytes()
            if avail < 1.5 * 1024 ** 3:
                self.tell(
                    f"Insufficient available RAM ({avail / (1024 ** 3):.2f} GiB available; "
                    f"at least 1.50 GiB required). DeBERTa loading cancelled for safety."
                )
                self.tell("Returning safely to candidate review.")
                return
        except Exception:
            pass

        try:
            if self.verifier is not None:
                verifier = self.verifier
            elif self.nli is not None:
                from c1_requirement_quality.rag.verifier import FactVerifier
                verifier = FactVerifier(self.nli)
            else:
                from c1_requirement_quality.model_paths import get_deberta_nli_cache_dir
                from c1_requirement_quality.rag.verifier import FactVerifier, LocalNLI
                cache_dir = get_deberta_nli_cache_dir()
                if cache_dir is None or not cache_dir.is_dir():
                    raise FileNotFoundError(f"DeBERTa cached model directory does not exist: {cache_dir}")
                nli = LocalNLI(model_name=str(cache_dir.resolve()))
                verifier = FactVerifier(nli)

            if self.embedder is not None:
                embedder = self.embedder
            else:
                from c1_requirement_quality.model_paths import get_minilm_cache_dir
                from c1_requirement_quality.rag.retriever import SentenceTransformersEmbedder
                minilm_cache = get_minilm_cache_dir()
                if not minilm_cache.is_dir():
                    raise FileNotFoundError(f"MiniLM cached model directory does not exist: {minilm_cache}")
                embedder = SentenceTransformersEmbedder(model_name=str(minilm_cache.resolve()))
        except Exception as error:
            self.tell(f"Unable to load local verification models: {error}")
            self.tell("Returning safely to candidate review.")
            return

        try:
            from c1_requirement_quality.rag.rag_grounding_analyser import RAGGroundingAnalyser
            _, text, _, _ = session.read()
            analyser = RAGGroundingAnalyser(text, embedder=embedder, verifier=verifier, top_k=3)
            results = analyser.analyse(candidate["text"])
        except Exception as error:
            self.tell(f"Evidence verification failed: {error}")
            self.tell("Returning safely to candidate review.")
            return

        self.tell("\n" + "-" * 70)
        self.tell("Candidate Rewrite Text:")
        self.tell(f"  \"{candidate['text']}\"")
        self.tell(f"\nRAG Evidence Verification Status (Advisory): {results['status'].upper()}")
        if assessment and "evaluation" in assessment and "grounding" in assessment["evaluation"]:
            det_status = assessment["evaluation"]["grounding"].get("status", "unknown")
            self.tell(f"Deterministic Grounding Status (Authoritative): {det_status.upper()}")
        self.tell("  (Deterministic grounding is authoritative; RAG/DeBERTa findings are advisory)")

        self.tell("\nExtracted Claims & Evidence Analysis:")
        diagnostics = results.get("diagnostics", [])
        if not diagnostics:
            self.tell("  (No verifiable atomic claims were extracted from candidate text)")
        for idx, diag in enumerate(diagnostics, 1):
            fact_text = diag["fact"]["text"]
            outcome = diag["outcome"]
            method = diag["method"]
            model = diag.get("model")
            diagnostic = diag.get("diagnostic")

            if method in {"symbolic", "symbolic_numeric"}:
                method_desc = f"Deterministic symbolic verification ({method})"
            elif method == "nli":
                method_desc = f"Local DeBERTa NLI advisory prediction ({model or 'nli-deberta-v3-small'})"
            else:
                method_desc = f"{method}"

            self.tell(f"\n  Claim {idx}: \"{fact_text}\"")
            self.tell(f"    Outcome: {outcome}")
            self.tell(f"    Verification Method: {method_desc}")
            if diagnostic:
                self.tell(f"    Diagnostic: {diagnostic}")

            retrieved = diag.get("retrieved_evidence", [])
            self.tell("    Retrieved Candidate SRS Evidence (Premise):")
            if not retrieved:
                self.tell("      (No candidate evidence chunks retrieved)")
            for ev in retrieved:
                chunk_id = ev.get("chunk_id", "Unknown")
                section = ev.get("section") or "General"
                sim = ev.get("similarity", 0.0)
                ev_text = ev.get("text", "").strip()
                self.tell(f"      • Chunk [{chunk_id}] (Section: {section})")
                self.tell(f"        Dense Similarity (uncalibrated topical relevance): {sim:.4f}")
                self.tell(f"        Evidence Text: \"{ev_text}\"")

        if results.get("errors"):
            self.tell("\nWarnings / Incomplete checks:")
            for err in results["errors"]:
                self.tell(f"  - {err}")

        self.tell("\n" + "-" * 70)
        self.tell("Advisory Summary:")
        self.tell("  - DeBERTa NLI predictions do not alter deterministic consistency, quality,")
        self.tell("    grounding decisions, requirement tiers, or BDD readiness.")
        self.tell("  - All candidate selection and modification remains under human control.")
        self.tell("=" * 70 + "\n")


    def prioritise_consistency(self, session, requirement_id=None):
        """Opt-in advisory pair prioritisation using local MiniLM sentence embeddings."""
        return self.consistency(session, requirement_id=requirement_id, prioritised=True)

    def _run_minilm_prioritisation(self, session, pairs, data):
        """Opt-in advisory prioritisation of consistency pairs using local MiniLM embeddings."""
        self.tell("\n" + "=" * 70)
        self.tell("Prioritise Consistency Reviews (Local MiniLM)")
        self.tell("=" * 70)
        self.tell("Notice:")
        self.tell("  - This feature is optional, offline, and disabled by default.")
        self.tell("  - Loading the sentence transformer reads local cached model weights and uses CPU/RAM.")
        self.tell("  - Pairwise cosine similarity scores are purely ADVISORY.")
        self.tell("  - Similarity identifies topical relevance only; it does NOT prove contradiction,")
        self.tell("    duplication, or logical consistency.")
        self.tell("  - Confirmed deterministic conflicts retain top priority regardless of similarity.")
        self.tell("  - All comparisons remain accessible; no pair is omitted by score thresholds.")
        self.tell("-" * 70)

        choice = self.menu(
            "Load local MiniLM model and prioritise unassessed comparisons?",
            ["Confirm: Load local model and prioritise comparisons", "Cancel (Back)"],
        )
        if choice != 1:
            self.tell("Prioritisation cancelled. Default comparison ordering retained.")
            return False

        try:
            from c1_requirement_quality.ml.ml_diagnostics import available_memory_bytes
            avail = available_memory_bytes()
            if avail < 1 * 1024 ** 3:
                self.tell(
                    f"Insufficient available RAM ({avail / (1024 ** 3):.2f} GiB available; "
                    f"at least 1.0 GiB required). MiniLM loading cancelled for safety."
                )
                self.tell("Returning safely to ordinary consistency review.")
                return False
        except Exception:
            pass

        try:
            if self.embedder is not None:
                embedder = self.embedder
            else:
                from c1_requirement_quality.model_paths import get_minilm_cache_dir
                from c1_requirement_quality.ml.similarity_diagnostics import checkpoint_provenance
                from c1_requirement_quality.rag.retriever import SentenceTransformersEmbedder

                cache_dir = get_minilm_cache_dir()
                if not cache_dir.is_dir():
                    raise FileNotFoundError(f"MiniLM cached model directory does not exist: {cache_dir}")
                checkpoint_provenance(cache_dir)
                embedder = SentenceTransformersEmbedder(model_name=str(cache_dir.resolve()))
        except Exception as error:
            self.tell(f"Unable to load local MiniLM model: {error}")
            self.tell("Returning safely to ordinary consistency review. Default pair ordering retained.")
            return False

        try:
            from c1_requirement_quality.ml.requirement_similarity import requirement_pair_diagnostics

            req_items = [
                {"requirement_id": r["requirement_id"], "original_text": r.get("final_text") or r["original_text"]}
                for r in data["requirements"]
            ]
            diag = requirement_pair_diagnostics(req_items, embedder=embedder)
            sim_map = {
                tuple(sorted(p["requirement_ids"])): p["similarity"]
                for p in diag.get("pairs", [])
            }
            for p in pairs:
                key = tuple(sorted(p["requirement_ids"]))
                if key in sim_map:
                    p["similarity"] = sim_map[key]

            def sort_key(p):
                is_conflict = (p["current_deterministic"]["classification"] == "conflict")
                sim = p.get("similarity", 0.0)
                return (0 if is_conflict else 1, -sim, p["requirement_ids"])

            pairs.sort(key=sort_key)
            self.tell(f"\nSuccessfully prioritised {len(pairs)} comparisons using local MiniLM.")
            self.tell("Confirmed deterministic conflicts retain highest priority. All comparisons remain accessible.")
            return True
        except Exception as error:
            self.tell(f"Error during MiniLM pair prioritisation: {error}")
            self.tell("Returning safely to ordinary consistency review. Default pair ordering retained.")
            return False

    def consistency(self, session, requirement_id=None, *, prioritised=False):
        pairs = session.consistency_pairs(gate_policy=True)
        data, _, _, state = session.read()
        resolutions = {}
        for row in data["requirements"]:
            result = assess(row["requirement_id"], data["requirements"], state["requirements"], context_from_state(state))
            resolutions.update({p["pair_id"]: p["resolution"] for p in result.get("effective_review", {}).get("pairs", [])})
        pairs = [p for p in pairs if (requirement_id is None or requirement_id in p["requirement_ids"])
                 and resolutions.get(p["pair_id"], "deterministic_consistent" if p["current_deterministic"]["classification"] == "consistent" else "unresolved")
                 in {"unresolved", "conflict"}]
        pairs.sort(key=lambda p: p["current_deterministic"]["classification"] == "conflict")
        if not pairs:
            self.tell("No unresolved consistency comparisons in this scope.")
            return

        if prioritised:
            self._run_minilm_prioritisation(session, pairs, data)

        index = 0
        while index < len(pairs):
            pair = pairs[index]
            self.tell("\nComparison: " + " / ".join(pair["requirement_ids"]))
            for row in pair["requirements"]:
                self.tell(row["requirement_id"] + ": " + row["final_text"])
            finding = pair["current_deterministic"]
            self.tell(f"{finding['classification']}: {finding['explanation']}")
            if "similarity" in pair:
                self.tell(f"Semantic similarity: {pair['similarity']:.4f} (advisory MiniLM cosine similarity; not proof of conflict or equivalence)")
            self.tell("Human review: " + pair["decision"] + " | " + str(pair.get("invalidation") or "current binding"))
            if finding["classification"] == "conflict":
                self.tell("Conflict Guidance:")
                self.tell("  A deterministic conflict exists between " + " and ".join(pair["requirement_ids"]) + ".")
                self.tell("  Explanation: " + finding["explanation"])
                self.tell("  A human applicability review alone cannot remove a deterministic conflict while the contradictory requirement text remains.")
                self.tell("  To resolve this conflict, at least one of these requirements must be edited or rewritten so they no longer contradict each other.")
            choice = self.menu("Consistency review", ["Review this comparison", "Skip", "Back", "Prioritise consistency reviews using local MiniLM"])
            if choice == 3:
                return
            if choice == 2:
                index += 1
                continue
            if choice == 4:
                success = self._run_minilm_prioritisation(session, pairs, data)
                if success:
                    index = 0
                continue
            decisions = ["unresolved", "conflict_confirmed", "consistent_within_scope", "not_applicable"]
            selected = self.menu("Explicit decision (no default)", decisions + ["Back"])
            if selected == 5:
                continue
            for ref, evidence in pair["evidence"].items():
                self.tell(ref + ": " + str(evidence.get("text") or "Recorded clarification"))
            review = dict(decision=decisions[selected - 1],
                evidence_refs=[s.strip() for s in self.ask("Evidence references covering both requirements (comma separated): ").split(",")],
                scope=self.ask("Scope reviewed: "), conditions=self.ask("Conditions reviewed (describe absence explicitly): "),
                rationale=self.ask("Reason for your decision: "), reviewer=self.ask("Your reviewer name or label: "),
                coverage=["partial", "complete"][self.menu("Coverage of the entire comparison", ["Partial", "Complete"]) - 1])
            self.tell("Review preview:")
            self.findings(review)
            if self.ask("Apply this gate-affecting review and revalidate? Type yes: ").strip().lower() == "yes":
                with redirect_stdout(io.StringIO()):
                    session.adopt_consistency(pair["requirement_ids"], confirmed=True, **review)
                self.tell("Review saved through the effective consistency policy. Remaining gates still apply.")
                if finding["classification"] == "conflict":
                    self.tell("Note: The deterministic conflict remains active because the requirement text still contains the contradiction.")
                    self.tell("To achieve BDD readiness, use 'Write manual rewrite' or 'Review rewrite candidates' to resolve the conflicting statements.")
                if self.menu("Consistency review saved", ["Continue to next unresolved comparison", "Back"]) == 2:
                    return
            index += 1

    def summary(self, session):
        data, _, _, state = session.read()
        rows = data["requirements"]
        self.tell("\nFinal review")
        self.tell(f"Total requirements: {len(rows)}")
        for tier, label in TIERS.items():
            self.tell(f"{label}: {sum(r['tier'] == tier for r in rows)}")
        self.tell("Tier descriptions:")
        for desc in TIER_DESCRIPTIONS.values():
            self.tell("  " + desc)
        self.tell(f"Quality issues: {sum(len(r['defects']) for r in rows)}")
        unanswered = unresolved = 0
        for row in rows:
            record = state["requirements"][row["requirement_id"]]
            resolution = clarification_resolution(record, row["original_text"], [])
            unanswered += sum(q["status"] in {"OPEN", "REOPENED"} for q in record["questions"].values())
            unresolved += len(resolution["unresolved_questions"])
        self.tell(f"Unanswered questions: {unanswered}")
        self.tell(f"Invalid or otherwise unresolved answers/closures: {unresolved - unanswered}")
        self.tell(f"Pending clarifications: {unresolved}")
        consistency_results = [assess(r["requirement_id"], rows, state["requirements"], context_from_state(state)) for r in rows]
        self.tell(f"Requirements with consistency blockers: {sum(c['check'] != 'pass' and not is_single_requirement_no_peers(c) for c in consistency_results)}")
        self.tell(f"Approved requirements: {sum(r['human_decision'] in {'approved', 'edited'} for r in rows)}")
        self.tell(f"Originals explicitly accepted without rewrite: {sum(r['human_decision'] == 'not_required' for r in rows)}")
        self.tell(f"BDD-ready requirements: {sum(r['bdd_ready'] for r in rows)}")
        for row in rows:
            if not row["bdd_ready"]: self.requirement(row, session)
        self.tell("Blocked requirements cannot proceed until all required checks and explicit review pass.")

    def approval(self, session, requirement_id=None, *, original_only=False):
        rows = session.review_read()[0]["requirements"]
        choice = next((i + 1 for i, r in enumerate(rows) if r["requirement_id"] == requirement_id), None) if requirement_id else None
        if choice is None:
            choice = self.menu("Choose a requirement for explicit approval", [r["requirement_id"] for r in rows] + ["Back"])
        if choice <= len(rows):
            row = rows[choice - 1]
            self.requirement(row, session)
            candidate = next((c for c in row.get("candidates", []) if c["candidate_id"] == row.get("selected_candidate_id")), None)
            if original_only: candidate = None
            if session.read()[2].get("rag_policy"):
                if candidate:
                    self.verify_candidate_evidence(session, row["requirement_id"], candidate)
                    self.tell("Exact selected candidate for approval intent: " + candidate["text"])
                self.tell("This records review intent only. Final publication and BDD readiness remain blocked.")
                options = (["Approve selected candidate", "Reject selected candidate"] if candidate else []) + ["Request clarification", "Back"]
                selected = options[self.menu("Human decision", options) - 1]
                if selected == "Back":
                    return
                if selected == "Request clarification":
                    question = self.ask("Clarification question (blank cancels): ").strip()
                    if question:
                        self.publish(session, {"requirement_id": row["requirement_id"],
                            "workflow_action": "request_clarification", "clarification_questions": [question]})
                    return
                self.publish(session, {"requirement_id": row["requirement_id"],
                    "human_decision": "approved" if selected == "Approve selected candidate" else "rejected"})
                return
            if candidate:
                self.tell("Exact selected candidate text: " + candidate["text"])
                assessment = self.candidate_assessment(session, row["requirement_id"], candidate)
                self.tell("Candidate checks: " + str(assessment["validation"]["checks"]))
            else:
                self.tell("No candidate is selected. Original text: " + row["original_text"])
            self.tell("Approval is a separate human decision. Validation may still block BDD readiness.")
            options = (["Approve selected candidate"] if candidate else []) + ["No rewrite needed - accept original", "Back"]
            decision = self.menu("Human decision", options)
            if candidate and decision == 1:
                action = {"requirement_id": row["requirement_id"], "human_decision": "approved"}
                record = session.review_read()[3]["requirements"][row["requirement_id"]]
                if record["escalation_active"]:
                    self.tell("An escalation is active. Acceptance requires an explicit resolution statement and revalidation.")
                    resolution = self.ask("How was the escalation resolved? (blank cancels): ").strip()
                    if not resolution: return
                    action.update(workflow_action="resolve_escalation", resolution=resolution)
                    self.tell("Escalation resolution to record: " + resolution)
                self.publish(session, action)
            elif options[decision - 1] == "No rewrite needed - accept original":
                record = session.review_read()[3]["requirements"][row["requirement_id"]]
                unresolved = clarification_resolution(record, row["original_text"], [])["unresolved_questions"]
                blockers = []
                if row["tier"] != "TIER_1_AUTO_REFINE":
                    blockers.append(f"assigned to {TIERS.get(row['tier'], row['tier'])}")
                if record["escalation_active"]:
                    blockers.append("has an active escalation")
                if unresolved:
                    blockers.append(f"has {len(unresolved)} unresolved clarification question(s)")
                if row["defects"]:
                    blockers.append(f"has {len(row['defects'])} detected quality defect(s)")
                if blockers:
                    reasons = "; ".join(blockers)
                    self.tell(f"The original is still blocked. Resolve its quality, clarification, escalation and consistency findings first. Details: {reasons}.")
                    return
                self.publish(session, {"requirement_id": row["requirement_id"], "human_decision": "not_required"})

    def manual(self, session, requirement_id=None):
        rows = session.review_read()[0]["requirements"]
        if requirement_id is None:
            choice = self.menu("Choose a requirement to rewrite", [r["requirement_id"] for r in rows] + ["Back"])
            if choice > len(rows): return
            requirement_id = rows[choice - 1]["requirement_id"]
        row = next(r for r in rows if r["requirement_id"] == requirement_id)
        self.requirement(row, session)
        self.tell("Manual rewrite: supply the complete intended obligation. It is recorded as human evidence, not original SRS evidence or approval.")
        text = self.ask("Your complete replacement requirement (blank cancels): ").strip()
        if not text: return
        if text == row["original_text"]:
            self.tell("The text is unchanged. Use 'No rewrite needed - accept original' when eligible.")
            return
        question = "What requirement should replace the original obligation?"
        self.publish(session, {"requirement_id": requirement_id, "selected_candidate_text": text,
            "clarification_questions": [question],
            "clarification_answers": [{"question": question, "answer": text}]})

    def ai_diagnostics(self, session, requirement_id=None):
        self.tell("\n" + "=" * 70)
        self.tell("Optional AI Quality Diagnostics (Local DistilBERT)")
        self.tell("=" * 70)
        self.tell("Notice:")
        self.tell("  - This feature is optional, offline, and disabled by default.")
        self.tell("  - Loading the model reads local checkpoint weights and may use additional RAM/CPU.")
        self.tell("  - Model predictions are independent uncalibrated sigmoid scores (0.0 to 1.0),")
        self.tell("    NOT calibrated probabilities or validated accuracy measurements.")
        self.tell("  - These diagnostics are purely ADVISORY. They do NOT alter rule-based findings,")
        self.tell("    tier assignments, human reviews, or BDD readiness.")
        self.tell("-" * 70)

        choice = self.menu(
            "Load local model and run advisory diagnostics?",
            ["Confirm: Load local model and view advisory diagnostics", "Cancel (Back)"],
        )
        if choice != 1:
            self.tell("AI diagnostics cancelled. No model loaded.")
            return

        data, _, _, state = session.read()
        rows = data["requirements"]
        if not rows:
            self.tell("No requirements available to diagnose.")
            return

        if requirement_id is None:
            opts = [r["requirement_id"] for r in rows] + ["All requirements", "Back"]
            sel = self.menu("Choose requirement to diagnose", opts)
            if sel == len(opts):
                return
            if sel == len(opts) - 1:
                target_rows = rows
            else:
                target_rows = [rows[sel - 1]]
        else:
            target_rows = [r for r in rows if r["requirement_id"] == requirement_id]
            if not target_rows:
                self.tell(f"Requirement {requirement_id} not found in current session.")
                return

        try:
            from c1_requirement_quality.ml.ml_diagnostics import available_memory_bytes
            avail = available_memory_bytes()
            if avail < 1 * 1024 ** 3:
                self.tell(
                    f"Insufficient available RAM ({avail / (1024 ** 3):.2f} GiB available; "
                    f"at least 1.0 GiB required). Model loading cancelled for safety."
                )
                return
        except Exception:
            pass

        try:
            if self.classifier is not None:
                classifier = self.classifier
            else:
                from c1_requirement_quality.ml_defect_classifier import (
                    DistilBertDefectClassifier,
                    EXPERIMENT2_LABELS,
                    EXPERIMENT2_PROVENANCE,
                )
                from c1_requirement_quality.model_paths import get_distilbert_model_dir

                model_dir = get_distilbert_model_dir()
                classifier = DistilBertDefectClassifier(
                    model_dir=model_dir,
                    semantic_labels=EXPERIMENT2_LABELS,
                    mapping_provenance=EXPERIMENT2_PROVENANCE,
                )
                classifier.validate_checkpoint()
        except Exception as error:
            self.tell(f"Unable to load local DistilBERT model: {error}")
            self.tell("Returning safely to wizard. Deterministic analysis and all saved work are unaffected.")
            return

        try:
            from c1_requirement_quality.ml_defect_classifier import EXPERIMENT2_LABELS

            for row in target_rows:
                rid = row["requirement_id"]
                orig_text = row.get("original_text", "")
                self.tell("\n" + "-" * 70)
                self.tell(f"Advisory Diagnostic: Requirement {rid}")
                self.tell(f"Statement: {orig_text}")
                self.tell("-" * 70)

                self.tell("1. Rule-Based Confirmed Quality Findings (Deterministic):")
                defects = row.get("defects", [])
                if defects:
                    for d in defects:
                        dtype = d.get("issue_type") or d.get("defect_type") or "DEFECT"
                        dmsg = d.get("explanation") or d.get("message") or d.get("description") or "Detected defect"
                        self.tell(f"   - [{dtype}]: {dmsg}")
                else:
                    self.tell("   - None detected by deterministic rules.")

                self.tell("\n2. DistilBERT Advisory Defect Scores (Local ML - Advisory Only):")
                self.tell("   Interpretation: Uncalibrated sigmoid scores (0.0 to 1.0); NOT calibrated probabilities.")
                self.tell("   Trained on Experiment 2 Colab dataset (36 provisional requirements). Zero decision effect.")
                result = classifier.classify(orig_text, requirement_id=rid)
                scores = result.scores if hasattr(result, "scores") else (result.get("scores", {}) if isinstance(result, dict) else getattr(result, "scores", {}))
                for label in EXPERIMENT2_LABELS:
                    score_val = scores.get(label, 0.0)
                    self.tell(f"   - {label:<16}: {score_val:.4f} (uncalibrated sigmoid score)")

                self.tell("\n3. Human Review Status & BDD Readiness:")
                h_decision = row.get("human_decision", "pending")
                bdd_status = "READY" if row.get("bdd_ready") else "BLOCKED"
                tier_disp = TIERS.get(row.get("tier"), row.get("tier", "Unknown"))
                self.tell(f"   - Current Tier:         {tier_disp}")
                self.tell(f"   - Human Decision:       {h_decision}")
                self.tell(f"   - BDD Readiness Gate:   {bdd_status}")
                self.tell("   - Advisory Effect:      None. ML scores do not modify requirements, defects, or gates.")

            self.tell("\n" + "=" * 70)
            self.tell("Advisory diagnostics complete. Returning to review.")
        except Exception as error:
            self.tell(f"Error during advisory inference: {error}")
            self.tell("Returning safely to wizard. Deterministic analysis and all saved work are unaffected.")

    def next_action(self, session, row, state):
        """Choose presentation only; existing services retain all decision policy."""
        record = state["requirements"][row["requirement_id"]]
        if row["bdd_ready"]: return "complete"
        if session.read()[2].get("rag_policy") and any(
                intent["active"] and intent["action"]["requirement_id"] == row["requirement_id"]
                for intent in session.approval_intents()):
            return "intent_recorded"
        if clarification_resolution(record, row["original_text"], [])["unresolved_questions"]:
            return "questions"
        if row.get("selected_candidate_id") and row["human_decision"] == "pending":
            return "approval"
        if record["escalation_active"] or row["tier"] == "TIER_3_ESCALATE":
            return "manual"
        consistency = assess(row["requirement_id"], session.read()[0]["requirements"],
                             state["requirements"], context_from_state(state))
        consistency_blocked = consistency["check"] != "pass" and not is_single_requirement_no_peers(consistency)
        if not row["defects"] and row["grounding"]["status"] == "supported" and consistency_blocked:
            return "consistency"
        if row["tier"] == "TIER_1_AUTO_REFINE" or record["answers"] or row.get("candidates"):
            return "candidates"
        return "manual"

    def guided(self, session):
        self.tell("Step 1 - Analysis overview and summary")
        self.overview(session)
        self.summary(session)
        rows = session.review_read()[0]["requirements"]
        # Cursor and skipped items are navigation only, never persisted decisions.
        index = next((i for i, row in enumerate(rows) if not row["bdd_ready"]), len(rows))
        while index < len(rows):
            data, _, _, state = session.review_read()
            rows = data["requirements"]
            row = rows[index]
            rid = row["requirement_id"]
            self.tell(f"Step 2 - Tier-based review: requirement {index + 1} of {len(rows)}")
            self.requirement(row, session)
            action = self.next_action(session, row, state)
            labels = {"questions": "Answer unresolved clarification questions", "consistency": "Review unresolved consistency comparisons",
                      "manual": "Write a manual rewrite", "candidates": "Review safe suggestions / registered candidates",
                      "intent_recorded": "Continue (approval intent recorded; publication blocked)",
                      "approval": "Review selected candidate and explicitly approve", "complete": "Continue (already BDD-ready)"}
            if action == "manual" and state["requirements"][rid]["escalation_active"]:
                self.tell("Escalation reasons: " + "; ".join(c["explanation"] for c in row["consistency"].get("conflicts", [])))
                self.tell("Manual escalation remains active until explicitly resolved and revalidated.")
            choice = self.menu("Recommended next step: " + labels[action], [labels[action], "Next / Skip for now", "Previous", "Details",
                "No rewrite needed - accept original", "Individual sections", "Back to session", "Pause"])
            if choice == 8: raise KeyboardInterrupt
            if choice == 7: return
            if choice == 6:
                self.sections(session)
                continue
            if choice == 5:
                self.approval(session, rid, original_only=True)
            elif choice == 4:
                self.findings(state["requirements"][rid])
                continue
            elif choice == 3:
                index = max(0, index - 1)
                continue
            elif choice == 2 or action in {"complete", "intent_recorded"}:
                index += 1
                continue
            else:
                {"questions": self.questions, "consistency": self.consistency, "manual": self.manual,
                 "candidates": self.candidates, "approval": self.approval}[action](session, rid)
            if session.pending: return  # Resolve interruptions in the session recovery screen.
            self.tell("Step 3 - Reclassification from the current verified snapshot")
            latest = next(r for r in session.review_read()[0]["requirements"] if r["requirement_id"] == rid)
            self.requirement(latest, session)
            if latest["bdd_ready"]: index += 1
        self.tell("Step 4 - Final summary (skipped requirements remain blocked)")
        self.summary(session)
        if self.menu("Step 5 - Existing JSON export", ["Show verified JSON output", "Back to session"]) == 1:
            self.export(session)

    def export_reports(self, session, out_dir: Path | None = None) -> tuple[Path, Path]:
        return export_reports(session, out_dir=out_dir)

    def export(self, session, out_dir: Path | None = None):
        session.read()  # Verify authoritative output before exposing it.
        self.tell("Validated JSON output (ready to copy): " + str(session.current))
        self.tell("HTML report: unavailable. Stage 4F must integrate a renderer with the verified "
                  "validated_requirements.json and workflow/consistency diagnostics.")
        try:
            md_path, txt_path = self.export_reports(session, out_dir=out_dir)
            self.tell(f"Exported Markdown report: {md_path}")
            self.tell(f"Exported Quality summary: {txt_path}")
        except (OSError, RuntimeError) as error:
            self.tell(f"Unable to export reports: {error}. JSON output and session data are safely retained.")

    def review(self, session, *, start_guided=False):
        with _session_lock(session.workspace):
            while True:
                try:
                    if session.pending:
                        choice = self.menu("An interrupted change is retained; nothing will replay automatically.",
                            ["Verify and adopt already published output", "Cancel pending operation (retain files)", "Back"])
                        if choice == 3: return
                        session.recover(choice == 1)
                    if start_guided:
                        start_guided = False
                        self.guided(session)
                        continue
                    choice = self.menu("Your analysis", ["Continue guided workflow", "Individual sections", "Save and return to welcome"])
                    if choice == 3: return
                    if choice == 1: self.guided(session)
                    else: self.sections(session)
                except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
                    self.tell(f"Action stopped; saved work retained: {error}")

    def sections(self, session):
        choice = self.menu("Individual sections", [
            "Show requirements overview",
            "Review requirement quality",
            "Answer clarification questions",
            "Review rewrite candidates",
            "Review consistency comparisons",
            "Final review",
            "Export results",
            "Explicit requirement approval",
            "Write manual rewrite",
            "View optional AI quality diagnostics (local DistilBERT)",
            "Back",
        ])
        if choice != 11:
            [self.overview, self.quality, self.questions, self.candidates, self.consistency, self.summary,
             self.export, self.approval, self.manual, self.ai_diagnostics][choice - 1](session)

    def run(self):
        while True:
            try:
                choice = self.menu("Requirement Quality & Refinement Agent\n"
                    "Automated SRS Quality Analysis",
                    ["Import SRS Document", "Resume Previous Analysis", "Exit"])
                if choice == 3: return 0
                if choice == 1:
                    source = self.source()
                    if source: self.review(self.create(source), start_guided=True)
                else:
                    session = self.choose_session()
                    if session:
                        self.review(session, start_guided=True)
            except (EOFError, KeyboardInterrupt):
                self.display("Paused safely. Saved work and pending records retained. Launch c1 to resume.", "yellow")
                return 0
            except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
                self.display(f"Unable to continue: {error}. Existing sessions are preserved.", "red")
                if self.analysis_error_details:
                    try:
                        while self.menu("Analysis stopped", ["Back to welcome", "Details"]) == 2:
                            self.tell(self.analysis_error_details)
                    except (EOFError, KeyboardInterrupt):
                        self.display("Paused safely. Saved work and pending records retained. Launch c1 to resume.", "yellow")
                        return 0
                    self.analysis_error_details = None


def launch(*, root=None, ask=None, tell=print, classifier=None):
    if not sys.stdin.isatty():
        tell("Text-menu mode: enter option numbers on separate lines. End of input pauses safely.")
    return Wizard(Path(root) if root else Path.cwd() / ".c1-sessions",
                  input if ask is None else ask, tell, classifier=classifier).run()
