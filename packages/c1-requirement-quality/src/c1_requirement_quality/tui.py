"""Selectable terminal presentation over the existing C1 workflow services.

No decision policy lives here. Confirmed actions use DemoSession; immutable
artifacts, the existing journal and validators remain the authority.
"""
from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (Button, Checkbox, DataTable, Footer, Header, Input,
    Label, OptionList, ProgressBar, Select, SelectionList, Static, TextArea)

from .demo_workflow import DemoSession, _session_lock
from .source_integrity import sha256
from .validation_lifecycle import clarification_resolution
from .wizard import STAGES, TIERS, browse_file, validate_source


HELP = ("Arrow keys move through lists; Enter selects. Tab / Shift+Tab move between fields. "
    "Esc returns; Ctrl+S saves and returns to the dashboard. Confirmed decisions are saved immediately.\n\n"
    "Analysis uses the existing local DistilBERT, MiniLM and DeBERTa services. No models are downloaded. "
    "Classification scores are experimental and do not grant approval. Empty rule findings do not prove quality.\n\n"
    "Clarifications are human evidence, never original SRS facts. Selection, approval and publication are separate. "
    "Unresolved evidence, contradictions, questions and validation failures keep requirements blocked. "
    "Cloud actions require explicit consent; errors preserve the session. CampusCare stays local.")


def assessment_text(result):
    evaluation = result.get("evaluation", result)
    grounding = evaluation.get("grounding", {})
    validation = result.get("validation", {})
    text = "Rule checks: " + str(evaluation.get("quality_check", "unassessed"))
    text += "\nGrounding: " + str(grounding.get("status", "unassessed"))
    if grounding.get("verdict"):
        text += "\nSource-only RAG outcome: " + grounding["verdict"]
    if grounding.get("human_clarification_evidence"):
        text += "\nSupport includes separately attributed, confirmed human clarification."
    text += "\nMeaning: " + str(grounding.get("meaning_preservation", {}).get("status", "unassessed"))
    text += "\nConsistency: " + str(result.get("consistency", {}).get("status", "unassessed"))
    text += "\nBDD testability check: " + str(validation.get("checks", {}).get("bdd_readiness", "unassessed"))
    if "approval_eligible" in result:
        text += "\nEligible for explicit approval: " + ("yes" if result["approval_eligible"] else "no")
    reasons = validation.get("bdd_readiness", {}).get("reasons", [])
    if reasons:
        text += "\n\nRemaining blockers:\n" + "\n".join("• " + r["explanation"] for r in reasons)
    if grounding.get("errors"):
        text += "\n\nEvidence check: " + "; ".join(grounding["errors"])
    for evidence in grounding.get("evidence", []):
        text += "\n\nEvidence (" + str(evidence.get("section", "source")) + "):\n" + evidence["text"]
    return text


def generation_text(result):
    lines = ["Generation does not select or approve a candidate."]
    for row in result.get("requirements", []):
        lines.append(row["requirement_id"] + f": {len(row['ranked_candidates'])} viable, "
                     f"{len(row['diagnostic_suggestions'])} blocked for review, {len(row['rejected_candidates'])} rejected.")
        if row.get("zero_candidates_reason") or row.get("blocked_reason"):
            lines.append(str(row.get("zero_candidates_reason") or row["blocked_reason"]))
        for candidate in row["ranked_candidates"]:
            lines.append("\n" + candidate["text"] + "\n" + assessment_text({
                "evaluation": {"quality_check": "fail" if candidate["quality_findings"] else "pass", "grounding": candidate["grounding"]},
                "consistency": candidate["consistency"], "validation": candidate["validation"]}))
        for candidate in row["diagnostic_suggestions"] + row["rejected_candidates"]:
            lines.append("\nExcluded from selection: " + candidate["text"] + "\nReason: " +
                         str(candidate.get("rejected_reason") or candidate.get("diagnostic_reason")))
    return "\n".join(lines)


class BackScreen(Screen):
    BINDINGS = [("escape", "back", "Back"), ("ctrl+s", "pause", "Save / dashboard"), ("f1", "help", "Help")]

    def action_back(self):
        if getattr(self, "busy", False):
            self.notify("An operation is still running. Its result will be retained.")
        elif len(self.app.screen_stack) > 1:
            self.app.pop_screen()

    def action_pause(self):
        if getattr(self, "busy", False):
            self.notify("Wait for the current operation to finish before leaving.")
            return
        self.app.switch_screen(Dashboard())

    def action_help(self):
        self.app.push_screen(Details("C1 navigation and safeguards", HELP))


class Details(ModalScreen):
    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, title, content):
        super().__init__()
        self.heading, self.content = title, content

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.heading, classes="title")
            with VerticalScroll():
                yield Static(self.content, markup=False)
            yield Button("Back", id="close", variant="primary")

    def action_close(self):
        self.dismiss(None)

    def on_button_pressed(self, event):
        self.action_close()


class ReviewForm(ModalScreen):
    """Separate labelled text fields and an unchecked explicit confirmation."""
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title, fields, *, explanation="", evidence=None, require_confirmation=True,
                 details=None, allow_save=True, pair=None):
        super().__init__()
        self.heading, self.fields, self.explanation = title, fields, explanation
        self.evidence = evidence
        self.require_confirmation = require_confirmation
        self.details, self.allow_save = details, allow_save
        self.pair = pair

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.heading, classes="title")
            with VerticalScroll():
                if self.pair:
                    with Horizontal(classes="pair-comparison"):
                        for row in self.pair:
                            yield Static(row["requirement_id"] + "\n" + row["final_text"], markup=False)
                yield Static(self.explanation, markup=False)
                for field in self.fields:
                    yield Label(field["label"])
                    if "options" in field:
                        yield Select([(Text(label), value) for label, value in field["options"]],
                                     id=field["id"], allow_blank=True, prompt="Choose explicitly")
                    elif field.get("multiline"):
                        yield TextArea(field.get("value", ""), id=field["id"], soft_wrap=True)
                    else:
                        yield Input(field.get("value", ""), id=field["id"])
                if self.evidence is not None:
                    yield Label("Select supporting evidence (both source requirements are required)")
                    yield SelectionList(*[(Text(label), ref, False) for label, ref in self.evidence], id="evidence")
                if self.require_confirmation:
                    yield Checkbox("I reviewed the values and explicitly confirm this action", id="confirmed")
                yield Static("", id="form-error", markup=False)
            with Horizontal(classes="buttons"):
                yield Button("Confirm / save" if self.require_confirmation else "Continue", id="save", variant="primary", disabled=not self.allow_save)
                yield Button("Cancel", id="cancel")
                if self.details:
                    yield Button("Technical details", id="technical")

    def on_button_pressed(self, event):
        if event.button.id == "technical":
            return self.app.push_screen(Details("Technical validation details", self.details))
        if event.button.id == "cancel":
            return self.dismiss(None)
        if event.button.id != "save":
            return
        values = {}
        for field in self.fields:
            widget = self.query_one("#" + field["id"])
            value = widget.text if isinstance(widget, TextArea) else widget.value
            if value is Select.BLANK:
                value = ""
            if not str(value).strip() and not field.get("optional"):
                self.query_one("#form-error", Static).update("Complete: " + field["label"])
                return
            values[field["id"]] = str(value).strip()
        if self.require_confirmation and not self.query_one("#confirmed", Checkbox).value:
            self.query_one("#form-error", Static).update("Explicit confirmation is required. Nothing has been saved.")
            return
        if self.evidence is not None:
            values["evidence_refs"] = self.query_one("#evidence", SelectionList).selected
        self.dismiss(values)

    def action_cancel(self):
        self.dismiss(None)

    def on_resize(self, event):
        self.set_class(event.size.width < 100, "compact")


class Dashboard(BackScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="welcome"):
            yield Static("C1  REQUIREMENT QUALITY & REFINEMENT", classes="title")
            yield Static("BDD-QA Framework · local, traceable, human-reviewed", classes="subtitle")
            yield OptionList("Start new SRS analysis", "Resume previous session", "View previous results", "Help", "Exit", id="main-menu")
            yield Static("↑ ↓ Navigate   Enter Select   Tab Next field   F1 Help", classes="hint")
        yield Footer()

    def on_mount(self):
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event):
        if event.option_list.id != "main-menu":
            return
        index = event.option_index
        if index == 0:
            self.app.push_screen(ImportScreen())
        elif index in {1, 2}:
            self.app.push_screen(SessionsScreen(results_only=index == 2))
        elif index == 3:
            self.action_help()
        else:
            self.app.exit()


class SessionsScreen(BackScreen):
    def __init__(self, *, results_only=False):
        super().__init__()
        self.results_only = results_only
        self.paths = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Previous sessions · saved decisions are verified on open", classes="title")
        yield OptionList(id="sessions")
        yield Static("", id="session-error", markup=False)
        yield Footer()

    def on_mount(self):
        options = self.query_one(OptionList)
        for path in sorted(self.app.root.glob("session-*/session.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
                label = Path(meta["source"]).name + " · " + path.parent.name
            except (ValueError, OSError, KeyError):
                label = path.parent.name + " · retained, metadata unavailable"
            self.paths.append(path.parent)
            options.add_option(Text(label))
        if not self.paths:
            self.query_one("#session-error", Static).update("No sessions found in " + str(self.app.root))
        else:
            options.highlighted = 0
        options.focus()

    def on_option_list_option_selected(self, event):
        try:
            session = DemoSession(self.paths[event.option_index], analyser_factory=self.app.analyser_factory)
            self.app.push_screen(SessionScreen(session, results_only=self.results_only))
        except Exception as error:
            self.query_one("#session-error", Static).update("Unable to resume; files preserved: " + str(error))


class ImportScreen(BackScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Select and preview an SRS", classes="title")
        yield Static("DOCX, text PDF, TXT, Markdown and supported structured JSON. Scanned PDFs require external OCR.")
        yield Input(placeholder="Paste a file path", id="source-path")
        with Horizontal(classes="buttons"):
            yield Button("Browse files", id="browse")
            yield Button("Sample SRS", id="sample")
            yield Button("Recent documents", id="recent")
            yield Button("Preview", id="preview", variant="primary")
        with VerticalScroll():
            yield Static("Choose a document. The original file is never rewritten.", id="preview-text", markup=False)
        yield Button("Confirm document and analyse locally", id="analyse", variant="success", disabled=True)
        yield Footer()

    def on_input_changed(self, event):
        if event.input.id == "source-path":
            self.query_one("#analyse", Button).disabled = True

    def on_button_pressed(self, event):
        try:
            action = event.button.id
            if action == "browse":
                value = browse_file()
                if value:
                    self.query_one(Input).value = value
            elif action == "sample":
                self.query_one(Input).value = str(Path(__file__).with_name("sample_srs.md"))
            elif action == "recent":
                self.app.push_screen(SessionsScreen())
            elif action == "preview":
                self.preview()
            elif action == "analyse":
                if sha256(self.source.read_bytes()) != self.preview_sha256:
                    raise ValueError("The document changed after preview; preview and confirm it again")
                self.app.push_screen(AnalysisScreen(self.source, expected_sha256=self.preview_sha256))
        except Exception as error:
            self.query_one("#preview-text", Static).update("Unable to use this document: " + str(error) + "\nPaste a path to try again.")

    def preview(self):
        from .ingest import load_srs_document
        self.source = validate_source(self.query_one(Input).value)
        raw = self.source.read_bytes()
        self.preview_sha256 = sha256(raw)
        document = load_srs_document(self.source)
        duplicates = []
        for path in self.app.root.glob("session-*/session.json"):
            try:
                if json.loads(path.read_text())["source_sha256"] == sha256(raw):
                    duplicates.append(path.parent.name)
            except (OSError, ValueError, KeyError):
                continue
        text = f"{self.source}\n{document.format.upper()} · {len(raw):,} bytes · {len(document.requirements)} extracted items\n"
        text += f"Context: {len(document.context_items)} · uncertain: {len(document.uncertain_items)}\n"
        if duplicates:
            text += "Existing sessions for these exact bytes: " + ", ".join(duplicates) + "\nResume through Recent documents, or explicitly start a new isolated session.\n"
        text += "\n" + document.raw_text[:5000]
        if document.warnings:
            text += "\n\nExtraction warnings:\n" + "\n".join(w.message for w in document.warnings)
        self.query_one("#preview-text", Static).update(text)
        self.query_one("#analyse", Button).disabled = not bool(document.requirements)


class AnalysisScreen(BackScreen):
    def __init__(self, source, *, expected_sha256=None):
        super().__init__()
        self.source, self.busy = source, True
        self.expected_sha256 = expected_sha256
        self.states = dict.fromkeys(STAGES, "pending")

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("C1 analysis · existing local models and deterministic checks", classes="title")
        yield ProgressBar(total=len(STAGES), id="progress")
        yield Static("", id="stages", markup=False)
        yield Static("", id="analysis-result", markup=False)
        yield Button("Open requirement review", id="open-review", disabled=True, variant="primary")
        yield Footer()

    def on_mount(self):
        self.render_stages()
        self.analyse()

    def render_stages(self):
        self.query_one("#stages", Static).update("\n".join(f"{self.states[key].upper():10} {label}" for key, label in STAGES.items()))
        self.query_one(ProgressBar).update(progress=sum(v == "completed" for v in self.states.values()))

    def stage(self, key, status, detail):
        self.states[key] = status
        self.render_stages()
        self.query_one("#analysis-result", Static).update(detail)

    @work(thread=True, exit_on_error=False)
    def analyse(self):
        workspace = self.app.root / ("session-" + uuid.uuid4().hex)
        run_id = datetime.now(timezone.utc).strftime("RUN-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        try:
            if self.expected_sha256 and sha256(self.source.read_bytes()) != self.expected_sha256:
                raise ValueError("The SRS changed since preview; select and confirm the document again")
            session = DemoSession.create(workspace, source=self.source, run_id=run_id,
                registry=workspace / "registry.json", mandatory_ml=True, mandatory_rag=True,
                classifier=self.app.classifier,
                stage_progress=lambda *args: self.app.call_from_thread(self.stage, *args))
            self.app.call_from_thread(self.ready, session)
        except Exception as error:
            self.app.call_from_thread(self.failed, workspace, str(error))

    def ready(self, session):
        self.session, self.busy = session, False
        self.stage("review", "completed", "Saved session: " + str(session.workspace))
        self.query_one("#open-review", Button).disabled = False

    def failed(self, workspace, error):
        self.busy = False
        for key, state in self.states.items():
            if state == "running":
                self.states[key] = "failed"
        self.render_stages()
        self.query_one("#analysis-result", Static).update("Analysis incomplete. Existing data preserved.\n" + error + "\nRetained workspace: " + str(workspace))

    def on_button_pressed(self, event):
        if event.button.id == "open-review":
            self.app.switch_screen(SessionScreen(self.session))


class SessionScreen(BackScreen):
    ACTIONS = ["View evidence and diagnostics", "Generate clarification questions (offline)",
        "Answer / revise clarification", "Generate rewrite candidates (offline)", "Compare / select / edit candidates",
        "Write manual rewrite", "Review consistency comparisons", "Approve selected requirement",
        "Accept original without rewriting", "Escalate / resolve escalation", "Publish approved requirements",
        "Export DOCX, C2 JSON and reports", "Suggest clarification questions (Groq)",
        "Generate 2–3 rewrite proposals (Groq)", "Save and return to dashboard"]

    def __init__(self, session, *, results_only=False):
        super().__init__()
        self.session, self.results_only = session, results_only
        self.rid = None
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="summary", markup=False)
        with Horizontal(id="review-layout"):
            with Vertical(id="requirement-list"):
                yield Input(placeholder="Search ID or requirement text", id="search")
                yield DataTable(id="requirements", cursor_type="row")
            with Vertical(id="requirement-details"):
                with VerticalScroll(id="details-scroll"):
                    yield Static("", id="requirement-text", markup=False)
                yield OptionList(*self.ACTIONS, id="actions")
        yield Static("Saved · confirmed actions persist immediately", id="operation-status", markup=False)
        yield Footer()

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns("Requirement", "Tier", "Decision", "Ready")
        self.load_view()
        table.focus()
        if self.session.pending and not self.results_only:
            def recover(values):
                if values:
                    self.perform(lambda s: s.recover(values["recovery"] == "adopt"))
            self.app.push_screen(ReviewForm("Interrupted operation retained", [{"id": "recovery",
                "label": "Recovery action", "options": [("Verify and adopt already published output", "adopt"),
                    ("Cancel pending operation, retain all files", "cancel")]}],
                explanation="No API request, inference or decision is replayed. Adoption requires a verified prepared child."), recover)

    def load_view(self):
        self.data, self.source_text, self.manifest, self.state = self.session.review_read()
        self.basis = self.session._review_basis(self.state)
        rows = self.data["requirements"]
        tiers = Counter(r["tier"] for r in rows)
        unresolved = sum(len(clarification_resolution(self.state["requirements"][r["requirement_id"]], r["original_text"], [])["unresolved_questions"]) for r in rows)
        ready = sum(r["bdd_ready"] for r in self.session.read()[0]["requirements"])
        approved = sum(e["active"] for e in self.session.approval_intents()) if self.manifest.get("rag_policy") else 0
        from .wizard import _categorize_consistency_pairs
        peers = self.session._review_peers(self.state) if self.manifest.get("rag_policy") else rows
        conflicts, comparisons, _ = _categorize_consistency_pairs(self.session, peers, self.state)
        self.blocked_consistency = {rid for pair in conflicts + comparisons for rid in pair["requirement_ids"]}
        accepted = sum(r["human_decision"] in {"approved", "edited", "not_required"}
                       for r in self.session.read()[0]["requirements"])
        self.query_one("#summary", Static).update(
            f"{self.manifest['original_filename']} · {len(rows)} requirements · "
            f"{sum(len(r['defects']) for r in rows)} rule findings · tiers {tiers.get('TIER_1_AUTO_REFINE', 0)}/{tiers.get('TIER_2_CLARIFY', 0)}/{tiers.get('TIER_3_ESCALATE', 0)}\n"
            f"Pending clarifications: {unresolved} · current approval intents: {approved} · published BDD-ready: {ready}/{len(rows)}\n"
            f"Unresolved comparisons: {len(comparisons)} · confirmed conflicts: {len(conflicts)} · accepted decisions: {accepted}\n"
            f"Export readiness: {'complete authenticated snapshot' if ready == len(rows) else 'inspection / partial handoff; incomplete rows stay non-ready'}\n"
            f"Saved: {self.session.workspace}" + (" · RESULTS VIEW" if self.results_only else ""))
        self.filter_rows(self.query_one("#search", Input).value)

    def on_resize(self, event):
        self.set_class(event.size.width < 100, "narrow")

    def filter_rows(self, search):
        table = self.query_one(DataTable)
        table.clear()
        for row in self.data["requirements"]:
            if search.casefold() not in (row["requirement_id"] + " " + row["original_text"]).casefold():
                continue
            table.add_row(row["requirement_id"], row["tier"].split("_")[1], row["human_decision"], str(row["bdd_ready"]), key=row["requirement_id"])
        if self.rid is None and self.data["requirements"]:
            self.rid = self.data["requirements"][0]["requirement_id"]
        self.show_requirement()

    def on_input_changed(self, event):
        if event.input.id == "search" and hasattr(self, "data"):
            self.filter_rows(event.value)

    def on_data_table_row_highlighted(self, event):
        self.rid = str(event.row_key.value)
        self.show_requirement()

    def row(self):
        return next(r for r in self.data["requirements"] if r["requirement_id"] == self.rid)

    def show_requirement(self):
        if not self.rid:
            return
        row = self.row()
        record = self.state["requirements"][self.rid]
        findings = "\n".join(f"• {d['type']}: {d.get('evidence_span', '')} — {d['explanation']}" for d in row["defects"])
        questions = clarification_resolution(record, row["original_text"], [])["unresolved_questions"]
        selected = record["candidates"].get(record["selected_candidate_id"])
        text = f"{self.rid} · {TIERS[row['tier']]}\n\nORIGINAL\n{row['original_text']}\n\nQUALITY FINDINGS\n{findings or 'No implemented rule matched; this does not establish correctness.'}\n\n"
        text += f"GROUNDING: {row['grounding']['status']}\nWORKFLOW BLOCKERS\n"
        text += "\n".join(["Unresolved question: " + q for q in questions])
        if self.rid in self.blocked_consistency:
            text += "\nConsistency needs review; the conservative status is not proof of conflict."
        if record["escalation_active"]:
            text += "\nActive escalation requires explicit resolution and revalidation."
        if selected:
            text += "\n\nSELECTED CANDIDATE\n" + selected["text"] + "\n" + selected["status"]
        from .rag.fact_extractor import extract_facts
        facts = extract_facts(row["original_text"], use_spacy=False)
        if len(facts) > 1:
            text += f"\n\nEXTRACTION REVIEW\nPotentially non-atomic: the existing fact extractor identified {len(facts)} clauses. Review their boundaries; no automatic split or new IDs are applied."
        self.query_one("#requirement-text", Static).update(text)

    def on_option_list_option_selected(self, event):
        if event.option_list.id != "actions" or self.busy:
            return
        index = event.option_index
        if self.results_only and index not in {0, 11, 14}:
            self.notify("Open through Resume to record review decisions.")
            return
        if not self.rid and index not in {11, 14}:
            return
        try:
            [self.evidence, self.offline_questions, self.answer, self.offline_candidates,
             self.candidates, self.manual, self.consistency, self.approve, self.original,
             self.escalation, self.publish, self.export, self.cloud_questions,
             self.cloud_candidates, self.action_pause][index]()
        except Exception as error:
            self.query_one("#operation-status", Static).update("Action stopped; saved work retained: " + str(error))

    def perform(self, operation, callback=None):
        if self.busy:
            self.notify("The current operation must finish first.")
            return
        self.set_busy(True)
        return self._perform(operation, callback)

    @work(thread=True, group="session-operation", exit_on_error=False)
    def _perform(self, operation, callback=None):
        try:
            with _session_lock(self.session.workspace):
                fresh = DemoSession(self.session.workspace, analyser_factory=self.app.analyser_factory)
                if fresh._review_basis(fresh.review_read()[3]) != self.basis:
                    raise ValueError("Session changed since this screen was loaded; reopen the action after refresh")
                result = operation(fresh)
                fresh = DemoSession(fresh.workspace, analyser_factory=self.app.analyser_factory)
            self.app.call_from_thread(self.completed, fresh, result, callback)
        except Exception as error:
            self.app.call_from_thread(self.operation_failed, str(error))

    def set_busy(self, value):
        self.busy = value
        self.query_one("#actions", OptionList).disabled = value
        self.query_one("#operation-status", Static).update("Working · saved work retained" if value else "Saved · operation completed")

    def completed(self, session, result, callback):
        self.session = session
        self.set_busy(False)
        self.load_view()
        if callback:
            callback(result)

    def operation_failed(self, error):
        self.set_busy(False)
        self.query_one("#operation-status", Static).update("Stopped; saved work retained: " + error + " · Retry the action, enter a manual rewrite, or skip.")

    def record(self, action, reviewer):
        self.perform(lambda s: s.review_action(action, reviewer, True) if s.read()[2].get("rag_policy") else s.apply(action, reviewer, True))

    def evidence(self):
        row = self.row()
        from .rag.fact_extractor import extract_facts
        self.app.push_screen(Details("Evidence, source and quality diagnostics", json.dumps({
            "source": row["source"], "grounding": row["grounding"], "consistency": row["consistency"],
            "extracted_facts_not_automatic_support": [fact.to_dict() for fact in extract_facts(row["original_text"], use_spacy=False)],
            "workflow": self.state["requirements"][self.rid],
            "initial_ml": self.session.initial_ml_predictions() if self.session.meta.get("mandatory_ml") else "Not executed for this session"}, indent=2, ensure_ascii=False)))

    def offline_questions(self):
        rid = self.rid
        self.perform(lambda s: s.generate_review_questions([rid]),
            lambda result: self.app.push_screen(Details("Questions generated; no answers or approval", json.dumps(result, indent=2))))

    def answer(self):
        record = self.state["requirements"][self.rid]
        questions = list(record["questions"].values())
        if not questions:
            return self.notify("Generate or add a clarification question first.")
        from .lexical_patterns import PLACEHOLDER_PATTERN
        original = self.row()["original_text"]
        spans = list(dict.fromkeys([m.group(0) for m in PLACEHOLDER_PATTERN.finditer(original)] +
            [d["evidence_span"] for d in self.row()["defects"] if d.get("evidence_span")
             and original.count(d["evidence_span"]) == 1]))
        fields = [{"id": "question", "label": "Clarification question", "options": [(q["text"], q["question_id"]) for q in questions]},
                  {"id": "answer", "label": "Your stakeholder answer", "multiline": True},
                  {"id": "span", "label": "Source wording replaced (optional for whole-obligation answers)",
                   "options": [(span, span) for span in spans], "optional": True},
                  {"id": "reviewer", "label": "Reviewer identity"}]
        rid = self.rid
        def save(values):
            if values:
                answer = {"question_id": values["question"], "answer": values["answer"]}
                if values["span"]:
                    answer["replaces_span"] = values["span"]
                self.record({"requirement_id": rid, "clarification_answers": [answer]}, values["reviewer"])
        self.app.push_screen(ReviewForm("Answer clarification", fields,
            explanation="Navigation is separate from your answer. Review the text and confirm before saving. Answers do not approve a rewrite."), save)

    def offline_candidates(self):
        rid = self.rid
        self.perform(lambda s: s.generate_review_candidates([rid]) if s.read()[2].get("rag_policy") else self.legacy_generate(s, requirement_id=rid),
            lambda result: self.app.push_screen(Details("Candidate generation and independent validation", generation_text(result))))

    def legacy_generate(self, session, backend=None, *, requirement_id=None):
        from .rewrite_generator import generate_candidates_run
        target = session.workspace / "sidecars" / ("generation-" + uuid.uuid4().hex + ".json")
        rid = requirement_id or self.rid
        generate_candidates_run(session.current, session.source, target, backend=backend, requirement_ids=[rid])
        candidates = session.candidates(target)
        if candidates:
            session.apply({"requirement_id": rid, "candidate_texts": [c["text"] for _, c in candidates]}, "system:generator", True)
        return json.loads(target.read_text())

    def candidates(self):
        self.app.push_screen(CandidateScreen(self))

    def manual(self):
        rid = self.rid
        def save(values):
            if not values:
                return
            question = "What requirement should replace the original obligation?"
            self.record({"requirement_id": rid, "selected_candidate_text": values["rewrite"],
                "clarification_questions": [question], "clarification_answers": [
                    {"question": question, "answer": values["rewrite"]}]}, values["reviewer"])
        self.app.push_screen(ReviewForm("Manual rewrite", [
            {"id": "rewrite", "label": "Complete intended requirement", "multiline": True},
            {"id": "reviewer", "label": "Reviewer identity"}],
            explanation="Your exact whole obligation is separately attributed human evidence. It must still pass RAG, quality, meaning, consistency and readiness checks; it is not approval."), save)

    def consistency(self):
        self.app.push_screen(ConsistencyScreen(self))

    def approve(self):
        rid = self.rid
        record = self.state["requirements"][rid]
        selected = record["candidates"].get(record["selected_candidate_id"])
        if not selected:
            return self.notify("Select a candidate or review the original first.")
        def preview(session):
            if session.read()[2].get("rag_policy"):
                context = session.candidate_grounding_context()
                if record["selected_candidate_id"] not in context.receipts:
                    session.validate_candidate_evidence(rid, selected["text"])
                return session.approval_assessment(rid)
            from .wizard import Wizard
            return Wizard(session.workspace).candidate_assessment(session, rid, selected)
        def show(assessment):
            def confirm(values):
                if values:
                    self.record({"requirement_id": rid, "human_decision": "approved",
                        "selected_candidate_id": record["selected_candidate_id"]}, values["reviewer"])
            self.app.push_screen(ReviewForm("Explicit final approval", [{"id": "reviewer", "label": "Reviewer identity"}],
                explanation="Original:\n" + self.row()["original_text"] + "\n\nSelected:\n" + selected["text"] +
                "\n\nIndependent eligibility and blockers:\n" + assessment_text(assessment) +
                "\nApproval cannot override a failed check. Publication is a separate action.",
                details=json.dumps(assessment, indent=2, ensure_ascii=False),
                allow_save=assessment.get("approval_eligible", True)), confirm)
        self.perform(preview, show)

    def original(self):
        rid = self.rid
        def save(values):
            if values:
                if self.manifest.get("rag_policy"):
                    self.record({"requirement_id": rid, "selected_candidate_text": self.row()["original_text"]}, values["reviewer"])
                else:
                    self.record({"requirement_id": rid, "human_decision": "not_required"}, values["reviewer"])
        self.app.push_screen(ReviewForm("Review original without rewriting", [{"id": "reviewer", "label": "Reviewer identity"}],
            explanation=self.row()["original_text"] + "\nThis selects the unchanged original for separate validation and approval."), save)

    def escalation(self):
        rid = self.rid
        def save(values):
            if values:
                action = {"requirement_id": rid, "workflow_action": values["action"], "reason": values["reason"]}
                if values["action"] == "resolve_escalation":
                    action["resolution"] = values["reason"]
                self.record(action, values["reviewer"])
        self.app.push_screen(ReviewForm("Escalation decision", [
            {"id": "action", "label": "Action", "options": [("Escalate", "escalate"), ("Request resolution and revalidate", "resolve_escalation")]},
            {"id": "reason", "label": "Evidence-backed explanation", "multiline": True},
            {"id": "reviewer", "label": "Reviewer identity"}],
            explanation="A resolution statement cannot clear a remaining contradiction. Select and validate the corrected obligations first."), save)

    def publish(self):
        def save(values):
            if values:
                self.perform(lambda s: s.publish_approved(values["reviewer"], True))
        self.app.push_screen(ReviewForm("Publish current verified approvals", [{"id": "reviewer", "label": "Publisher identity"}],
            explanation="Every active approval, source hash, candidate receipt and final peer set is rechecked. Unapproved requirements stay unresolved."), save)

    def export(self):
        def save(values):
            if values:
                from .refined_export import export_refined_srs
                formats = {"docx", "json", "quality", "decisions", "traceability"} if values["format"] == "all" else {values["format"]}
                self.perform(lambda s: export_refined_srs(s, Path(values["destination"]), formats=formats),
                    lambda paths: self.app.push_screen(Details("Verified export files", "\n".join(str(p) for p in paths.values()))))
        destination = self.session.workspace / "exports" / uuid.uuid4().hex
        self.app.push_screen(ReviewForm("Export refined SRS and C2 handoff", [
            {"id": "format", "label": "Output format", "options": [("Complete review bundle", "all"),
                ("Refined SRS DOCX", "docx"), ("C2-compatible JSON", "json"), ("Requirement quality report", "quality"),
                ("Clarification and decision report", "decisions"), ("Traceability report", "traceability")]},
            {"id": "destination", "label": "New output directory", "value": str(destination)}],
            explanation="Exports DOCX, unchanged C2-compatible JSON, quality, decisions and traceability reports. Incomplete requirements are labelled and stay non-ready. Existing outputs are refused."), save)

    def cloud(self, *, questions=False):
        if ("campuscare" in self.manifest["original_filename"].casefold()
                or self.manifest["sha256"] == "203c2b8fd18db7e31beda432f3a6f7fb3aa99e8215579c39b5055023b7045805"):
            return self.notify("CampusCare is local-only. Use offline questions or manual review.", severity="warning")
        rid = self.rid
        def send(values):
            if values is None:
                return
            def generate(session):
                from .groq_generator import GroqGeneratorBackend
                backend = self.app.groq_backend or GroqGeneratorBackend.from_environment()
                backend.verify_availability()
                if questions:
                    return session.propose_review_clarifications(rid, backend=backend)
                if session.read()[2].get("rag_policy"):
                    return session.generate_review_candidates([rid], backend=backend)
                return self.legacy_generate(session, backend, requirement_id=rid)
            self.perform(generate, self.review_cloud_questions if questions else
                lambda result: self.app.push_screen(Details("Untrusted model proposals and validation", generation_text(result))))
        self.app.push_screen(ReviewForm("External provider consent · Groq", [],
            explanation="This checks the configured model, then sends the selected requirement, relevant evidence and active human answers to Groq. No automatic retry or model substitution. Model output cannot grant approval.\n\n" + self.row()["original_text"]), send)

    def cloud_questions(self):
        self.cloud(questions=True)

    def cloud_candidates(self):
        self.cloud()

    def review_cloud_questions(self, proposal):
        questions = proposal.get("clarification_questions", [])
        if not questions:
            return self.notify("The provider supplied no usable questions.")
        rid = self.rid
        def save(values):
            if values:
                self.record({"requirement_id": rid, "clarification_questions": [values["question"]]}, values["reviewer"])
        self.app.push_screen(ReviewForm("Review an untrusted question", [
            {"id": "question", "label": "Select question to accept", "options": [(q["question"], q["question"]) for q in questions]},
            {"id": "reviewer", "label": "Reviewer identity"}],
            explanation=json.dumps(questions, indent=2, ensure_ascii=False) + "\nAccepting a question supplies no answer."), save)


class CandidateScreen(BackScreen):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.items = list(owner.state["requirements"][owner.rid]["candidates"].items())
        for path in sorted((owner.session.workspace / "sidecars").glob("review-generation-*.json")):
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
                for row in report["requirements"]:
                    if row["requirement_id"] == owner.rid:
                        for item in row["diagnostic_suggestions"] + row["rejected_candidates"]:
                            self.items.append((None, {"text": item["text"], "status": "GENERATION_REJECTED",
                                                      "diagnostics": item, "history": path.name}))
            except (ValueError, OSError, KeyError, TypeError):
                continue

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Candidate comparison · selection and approval are separate", classes="title")
        yield OptionList(*[Text(f"{index + 1}. {c['status']} · {c['text']}") for index, (_, c) in enumerate(self.items)], id="candidate-list")
        yield Static("Select a candidate to inspect its checks. Earlier proposals and rejections remain in history.")
        yield Footer()

    def on_mount(self):
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event):
        cid, candidate = self.items[event.option_index]
        if cid is None:
            return self.app.push_screen(Details("Historical excluded proposal · cannot be selected or approved",
                candidate["text"] + "\nReason: " + str(candidate["diagnostics"].get("rejected_reason")
                    or candidate["diagnostics"].get("diagnostic_reason")) + "\n\n" +
                json.dumps(candidate["diagnostics"].get("evaluation", {}), indent=2, ensure_ascii=False)))
        rid = self.owner.rid
        def assessed(result):
            def save(values):
                if not values:
                    return
                self.app.pop_screen()
                if values["action"] == "reject":
                    action = {"requirement_id": rid, "selected_candidate_id": cid, "human_decision": "rejected"}
                elif values["action"] == "edit":
                    question = "What requirement should replace the original obligation?"
                    action = {"requirement_id": rid, "selected_candidate_text": values["text"],
                        "clarification_questions": [question],
                        "clarification_answers": [{"question": question, "answer": values["text"]}]}
                else:
                    action = {"requirement_id": rid, "selected_candidate_id": cid}
                self.owner.record(action, values["reviewer"])
            self.app.push_screen(ReviewForm("Candidate checks and decision", [
                {"id": "action", "label": "Action", "options": [("Select", "select"), ("Edit and select", "edit"), ("Reject", "reject")]},
                {"id": "text", "label": "Candidate text (edit only when choosing Edit)", "value": candidate["text"], "multiline": True},
                {"id": "reviewer", "label": "Reviewer identity"}], explanation=
                "Edited text is your confirmed whole-obligation clarification, never SRS evidence or approval.\n" +
                assessment_text(result), details=json.dumps(result, indent=2, ensure_ascii=False)), save)
        def check(session):
            from .wizard import Wizard
            if session.read()[2].get("rag_policy") and cid not in session.candidate_grounding_context().receipts:
                session.validate_candidate_evidence(rid, candidate["text"])
            return Wizard(session.workspace).candidate_assessment(session, rid, candidate)
        self.owner.perform(check, assessed)


class ConsistencyScreen(BackScreen):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.pairs = owner.session.consistency_pairs(gate_policy=True)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Consistency comparisons · no automatic non-applicability", classes="title")
        yield OptionList(*[Text(" / ".join(p["requirement_ids"]) + " · " + p["decision"]) for p in self.pairs], id="pairs")
        yield Static("Select a pair to inspect both obligations, choose evidence and record a scoped decision.")
        yield Footer()

    def on_mount(self):
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event):
        pair = self.pairs[event.option_index]
        evidence = [(ref + ": " + str(item.get("text", "Recorded human clarification")), ref) for ref, item in pair["evidence"].items()]
        description = pair["current_deterministic"]["explanation"]
        def save(values):
            if values:
                self.app.pop_screen()
                self.owner.perform(lambda s: s.adopt_consistency(pair["requirement_ids"],
                    decision=values["decision"], evidence_refs=values["evidence_refs"], scope=values["scope"],
                    conditions=values["conditions"], rationale=values["rationale"], reviewer=values["reviewer"],
                    coverage=values["coverage"], confirmed=True))
        self.app.push_screen(ReviewForm("Review both requirements", [
            {"id": "decision", "label": "Explicit conclusion", "options": [
                ("Confirmed conflict", "conflict_confirmed"), ("No conflict within reviewed scope", "consistent_within_scope"),
                ("Not applicable", "not_applicable"), ("Not yet decided", "unresolved")]},
            {"id": "scope", "label": "Scope actually reviewed"},
            {"id": "conditions", "label": "Conditions reviewed (state absence explicitly)"},
            {"id": "rationale", "label": "Evidence-backed explanation", "multiline": True},
            {"id": "coverage", "label": "Coverage", "options": [("Partial", "partial"), ("Complete pair", "complete")]},
            {"id": "reviewer", "label": "Reviewer identity"}], explanation=description,
            evidence=evidence, pair=pair["requirements"]), save)


class C1App(App):
    TITLE = "C1 · Requirement Quality & Refinement"
    CSS_PATH = "tui.tcss"

    def __init__(self, *, root=None, session=None, classifier=None, analyser_factory=None, groq_backend=None):
        super().__init__()
        self.root = Path(root) if root else Path.cwd() / ".c1-sessions"
        self.initial_session = session
        self.classifier, self.analyser_factory, self.groq_backend = classifier, analyser_factory, groq_backend

    def on_mount(self):
        self.push_screen(SessionScreen(self.initial_session) if self.initial_session else Dashboard())


def launch(*, root=None, session=None):
    C1App(root=root, session=session).run()
    return 0
