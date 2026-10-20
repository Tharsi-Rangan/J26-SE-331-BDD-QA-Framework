"""Textual Pilot journeys over real C1 services with injected offline models.

All reviewer input here is explicitly synthetic test data, not stakeholder
answers or actual user approval. Live requests are prohibited by the fixture.
"""
import asyncio
import json
import socket
from unittest.mock import patch

import pytest

pytest.importorskip("textual")
from textual.widgets import Checkbox, Input, OptionList, Select, Static, TextArea
from c1_requirement_quality.tui import C1App, Dashboard, Details, ImportScreen, ReviewForm, SessionScreen
from c1_requirement_quality.demo_workflow import DemoSession
from test_candidate_validation import context
from test_grounded_review_intents import review

_SYSTEM_CONNECT = socket.socket.connect


def run_journey(coroutine):
    # Windows asyncio creates its internal socketpair using loopback TCP.
    # Construct that IPC pair before restoring the fixture's complete network
    # prohibition; no application operation runs while connect is restored.
    with patch.object(socket.socket, "connect", _SYSTEM_CONNECT):
        loop = asyncio.new_event_loop()
    return asyncio.run(coroutine, loop_factory=lambda: loop)


async def choose(pilot, screen, index):
    menu = screen.query_one("#actions", OptionList)
    menu.highlighted = index
    menu.focus()
    await pilot.press("enter")
    await pilot.pause()


async def submit(app, pilot, values, *, confirm=True):
    form = app.screen
    assert isinstance(form, ReviewForm)
    for key, value in values.items():
        widget = form.query_one("#" + key)
        if isinstance(widget, TextArea):
            widget.load_text(value)
        else:
            widget.value = value
    if confirm and form.query("#confirmed"):
        checkbox = form.query_one("#confirmed", Checkbox)
        checkbox.scroll_visible(animate=False)
        await pilot.pause()
        await pilot.click("#confirmed")
    await pilot.click("#save")
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def test_keyboard_dashboard_help_import_and_cancel(tmp_path):
    async def journey():
        app = C1App(root=tmp_path / "sessions")
        async with app.run_test(size=(100, 38)) as pilot:
            await pilot.press("down", "down", "down", "enter")
            assert isinstance(app.screen, Details)
            await pilot.press("escape", "home", "enter")
            assert isinstance(app.screen, ImportScreen)
            app.screen.query_one(Input).value = str(tmp_path / "missing.docx")
            await pilot.click("#preview")
            assert "Unable" in str(app.screen.query_one("#preview-text", Static).render())
            await pilot.press("escape")
            assert isinstance(app.screen, Dashboard)
            assert not (tmp_path / "sessions").exists()
    run_journey(journey())


@pytest.mark.parametrize("review", [("The system shall wait for [timeout].",
    ["The system shall wait for [timeout]."])], indirect=True)
def test_selectable_human_answer_generation_approval_export_resume(review, tmp_path):
    session, rid, _, control, factory = review
    export = tmp_path / "handoff"
    async def journey():
        app = C1App(session=session, root=tmp_path, analyser_factory=factory)
        async with app.run_test(size=(120, 46)) as pilot:
            screen = app.screen
            assert isinstance(screen, SessionScreen)
            screen.query_one("#search", Input).value = "wait"
            await pilot.pause()
            assert screen.query_one("#requirements").row_count == 1
            await choose(pilot, screen, 2)
            qid = next(iter(screen.state["requirements"][rid]["questions"]))
            values = {"question": qid, "answer": "2 seconds", "span": "[timeout]", "reviewer": "synthetic-reviewer"}
            await submit(app, pilot, values, confirm=False)
            assert isinstance(app.screen, ReviewForm)
            assert not DemoSession(session.workspace, analyser_factory=factory).review_read()[3]["requirements"][rid]["answers"]
            await submit(app, pilot, values)
            assert isinstance(app.screen, SessionScreen)
            await choose(pilot, screen, 3)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert isinstance(app.screen, Details)
            await pilot.press("escape")
            candidates = screen.session.review_read()[3]["requirements"][rid]["candidates"]
            assert candidates
            await choose(pilot, screen, 4)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await submit(app, pilot, {"action": "select", "reviewer": "synthetic-reviewer"})
            await choose(pilot, screen, 7)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert isinstance(app.screen, ReviewForm)
            await submit(app, pilot, {"reviewer": "synthetic-reviewer"})
            assert screen.session.approval_intents()[-1]["active"]
            await choose(pilot, screen, 10)
            await submit(app, pilot, {"reviewer": "synthetic-reviewer"})
            assert screen.session.read()[0]["requirements"][0]["bdd_ready"]
            await choose(pilot, screen, 11)
            await submit(app, pilot, {"destination": str(export), "format": "all"})
            assert isinstance(app.screen, Details)
            await pilot.press("escape")
            await pilot.resize_terminal(80, 30)
            await pilot.pause()
            assert "narrow" in screen.classes
            await pilot.press("ctrl+s")
            assert isinstance(app.screen, Dashboard)
    run_journey(journey())
    resumed = DemoSession(session.workspace, analyser_factory=factory)
    assert resumed.read()[0]["requirements"][0]["final_text"] == "The system shall wait for 2 seconds."
    contract = json.loads((export / "c1/validated_requirements.json").read_text())
    assert contract == resumed.read()[0]
    assert (export / "refined_srs.docx").is_file()
    assert (export / "decision_report.json").is_file()
    assert (export / "traceability_report.json").is_file()


def test_cloud_consent_cancel_never_calls_provider(review, tmp_path):
    class Forbidden:
        def verify_availability(self):
            pytest.fail("Cancelled cloud action must not probe the provider")
    async def journey():
        app = C1App(session=review[0], root=tmp_path, analyser_factory=review[4], groq_backend=Forbidden())
        async with app.run_test(size=(100, 36)) as pilot:
            await choose(pilot, app.screen, 13)
            assert isinstance(app.screen, ReviewForm)
            await pilot.press("escape")
            await app.workers.wait_for_complete()
            assert isinstance(app.screen, SessionScreen)
    run_journey(journey())


def test_import_progress_uses_actual_stage_events_with_injected_models(context, tmp_path, monkeypatch):
    from c1_requirement_quality import cli
    from c1_requirement_quality.ml.ml_defect_classifier import EXPERIMENT2_FILES, EXPERIMENT2_LABELS
    from types import SimpleNamespace
    from c1_requirement_quality.tui import AnalysisScreen
    _, _, _, _, control, factory = context
    monkeypatch.setattr(cli, "RAGGroundingAnalyser", factory)
    class Classifier:
        model_name = "distilbert-requirement-defects"
        def validate_checkpoint(self):
            return {"mapping_status": "VERIFIED", "checkpoint_sha256": EXPERIMENT2_FILES["model.safetensors"],
                    "mapping_provenance": "Injected test adapter; no actual model inference"}
        def classify(self, text, *, requirement_id):
            return SimpleNamespace(to_dict=lambda: {**self.validate_checkpoint(), "requirement_id": requirement_id,
                "text": text, "scores": {label: 0.2 for label in EXPERIMENT2_LABELS}, "threshold_applied": None,
                "predicted_defects": [], "model_name": self.model_name, "token_limit": 128, "truncated": False})
    source = tmp_path / "preview.md"
    source.write_text("# Requirements\n1. The system shall retain logs.\n")
    original = source.read_bytes()
    async def journey():
        app = C1App(root=tmp_path / "sessions", classifier=Classifier(), analyser_factory=factory)
        async with app.run_test(size=(120, 42)) as pilot:
            await pilot.press("enter")
            app.screen.query_one(Input).value = str(source)
            await pilot.click("#preview")
            await pilot.click("#analyse")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert isinstance(app.screen, AnalysisScreen)
            assert all(state == "completed" for state in app.screen.states.values())
            await pilot.click("#open-review")
            assert isinstance(app.screen, SessionScreen)
            assert app.screen.session.initial_ml_predictions()
            await pilot.press("ctrl+s", "down", "enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, SessionScreen)
            assert app.screen.session.read()[0]["requirements"][0]["original_text"] == "The system shall retain logs."
    run_journey(journey())
    assert source.read_bytes() == original


def test_api_failure_retains_review_and_reports_no_success(review, tmp_path):
    from c1_requirement_quality.groq_generator import GroqGenerationError
    class Failing:
        def verify_availability(self):
            raise GroqGenerationError("Synthetic provider timeout; no content request")
    before = review[0].current.read_bytes()
    events = list(review[0].events)
    async def journey():
        app = C1App(session=review[0], root=tmp_path, analyser_factory=review[4], groq_backend=Failing())
        async with app.run_test(size=(100, 38)) as pilot:
            screen = app.screen
            await choose(pilot, screen, 13)
            await submit(app, pilot, {})
            assert isinstance(app.screen, SessionScreen)
            assert "timeout" in str(screen.query_one("#operation-status", Static).render())
    run_journey(journey())
    resumed = DemoSession(review[0].workspace, analyser_factory=review[4])
    assert resumed.current.read_bytes() == before and resumed.events == events


def test_interactive_cli_dispatches_to_textual(monkeypatch):
    import sys
    from unittest.mock import Mock
    from c1_requirement_quality import cli, tui
    launch = Mock(return_value=0)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(tui, "launch", launch)
    assert cli.main([]) == 0
    launch.assert_called_once_with(root=None)


def test_selectable_consistency_evidence_is_saved_only_with_confirmation(context, tmp_path, monkeypatch):
    from c1_requirement_quality import cli
    from textual.widgets import SelectionList
    _, _, _, _, _, factory = context
    source = tmp_path / "pair.md"
    source.write_text("# Requirements\n1. The system shall retain logs.\n2. The user shall view reports.\n")
    monkeypatch.setattr(cli, "RAGGroundingAnalyser", factory)
    cli.run(source, tmp_path / "pair", "RUN-20261020-120000-tuiu", registry_path=tmp_path / "pair-registry.json",
            grounding_mode="rag", mandatory_rag=True)
    session = DemoSession.create(tmp_path / "pair-review", artifact=tmp_path / "pair/c1/validated_requirements.json", source=source)
    session = DemoSession(session.workspace, analyser_factory=factory)
    async def journey():
        app = C1App(session=session, root=tmp_path, analyser_factory=factory)
        async with app.run_test(size=(120, 46)) as pilot:
            owner = app.screen
            await choose(pilot, owner, 6)
            await pilot.press("enter")
            await pilot.pause()
            values = {"decision": "not_applicable", "scope": "Entire synthetic pair",
                "conditions": "No shared condition", "rationale": "The reviewed obligations concern different actions",
                "coverage": "complete", "reviewer": "synthetic-reviewer"}
            app.screen.query_one(SelectionList).select_all()
            await submit(app, pilot, values, confirm=False)
            assert not owner.session.events
            await submit(app, pilot, values)
            assert isinstance(app.screen, SessionScreen)
            assert owner.session.consistency_pairs(gate_policy=True)[0]["decision"] == "not_applicable"
    run_journey(journey())
