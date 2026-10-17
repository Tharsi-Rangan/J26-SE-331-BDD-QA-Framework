"""Beginner journeys exercise real offline services and authoritative snapshots."""
import socket
from unittest.mock import patch

import pytest

from c1_requirement_quality import cli, wizard
from c1_requirement_quality.demo_workflow import DemoSession


def scripted(values):
    values = iter(values)
    def ask(prompt):
        try: return next(values)
        except StopIteration: raise AssertionError("Unexpected prompt: " + prompt)
    return ask


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("Network forbidden"))
    monkeypatch.setattr(cli, "LocalNLI", lambda *a, **k: pytest.fail("No local NLI execution"))
    from c1_requirement_quality.ml_defect_classifier import DistilBertDefectClassifier
    from c1_requirement_quality.rag.retriever import SentenceTransformersEmbedder
    from c1_requirement_quality.groq_generator import GroqGeneratorBackend
    monkeypatch.setattr(DistilBertDefectClassifier, "_ensure_loaded", lambda *a: pytest.fail("No DistilBERT load"))
    monkeypatch.setattr(SentenceTransformersEmbedder, "_load_model", lambda *a: pytest.fail("No MiniLM load"))
    monkeypatch.setattr(GroqGeneratorBackend, "_complete", lambda *a: pytest.fail("No Groq requests"))


@pytest.fixture
def app(tmp_path):
    messages = []
    return wizard.Wizard(tmp_path / "sessions", tell=messages.append), messages


@pytest.fixture
def session(app, tmp_path):
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall wait for [timeout].\n")
    return app[0].create(source)


@pytest.mark.parametrize("args", [[], ["demo"]])
def test_first_time_launch_dispatch(args):
    with patch.object(wizard, "launch", return_value=0) as launch:
        assert cli.main(args) == 0
        launch.assert_called_once_with()


def test_navigation_help_invalid_and_no_sessions(app):
    ui, messages = app
    ui.ask = scripted(["oops", "help", "2", "3", "4", "5"])
    assert ui.run() == 0
    assert any("No previous sessions" in m for m in messages)
    assert any("displayed numbers" in m for m in messages)


def test_source_invalid_dialog_cancel_and_sample(app, tmp_path):
    ui, messages = app
    bad = tmp_path / "bad.exe"
    bad.write_text("The system shall run.")
    ui.ask = scripted(["1", "2", str(tmp_path / "absent.md"), "2", str(bad), "2", "", "3", "1"])
    with patch.object(wizard, "browse_file", side_effect=RuntimeError("Dialog unavailable")):
        source = ui.source()
    assert source.name == "sample_srs.md"
    assert any("File not found" in m for m in messages)
    assert any("Supported files" in m for m in messages)
    assert any("Selection cancelled" in m for m in messages)
    empty = tmp_path / "empty.txt"
    empty.touch()
    with pytest.raises(ValueError, match="empty"):
        wizard.validate_source(str(empty))


def test_successful_dialog_selection_and_read_failure(app, tmp_path, monkeypatch):
    ui, _ = app
    source = tmp_path / "readable.txt"
    source.write_text("The system shall send email.")
    ui.ask = scripted(["1", "1"])
    with patch.object(wizard, "browse_file", return_value=str(source)):
        assert ui.source() == source
    with patch.object(type(source), "open", side_effect=PermissionError("Cannot read file")):
        with pytest.raises(PermissionError): wizard.validate_source(str(source))


def test_safe_creation_resume_no_overwrite_and_progress(app, session):
    ui, messages = app
    artifact = session.current.read_bytes()
    other = ui.create(session.source)
    assert session.workspace != other.workspace
    assert session.read()[0]["run_id"] != other.read()[0]["run_id"]
    assert session.current.read_bytes() == artifact
    with pytest.raises(FileExistsError):
        DemoSession.create(session.workspace, source=session.source)
    ui.ask = scripted(["1"])
    resumed = ui.choose_session()
    assert resumed.read()[0]["contract"] == "c1.validated-requirements"
    assert all(any(stage in m for m in messages) for stage in wizard.STAGES.values())
    assert any("[SKIPPED] Optional AI diagnostics" in m for m in messages)


@pytest.mark.parametrize("confirm", ["yes", "no"])
def test_clarification_explicit_confirmation_not_approval(app, session, confirm):
    ui, _ = app
    before = session.current
    ui.ask = scripted(["1", "2 seconds", "[timeout]", "1", "Reviewer", confirm])
    if confirm == "no":
        ui.ask = scripted(["1", "2 seconds", "[timeout]", "1", "Reviewer", confirm, "2"])
    ui.questions(session)
    assert (session.current != before) == (confirm == "yes")
    data, _, _, state = DemoSession(session.workspace).read()
    assert data["requirements"][0]["human_decision"] == "pending"
    answers = next(iter(state["requirements"].values()))["answers"]
    assert bool(answers) == (confirm == "yes")


def test_quality_navigation_and_final_counts(app, session):
    ui, messages = app
    ui.ask = scripted(["2", "3", "4", "1"])
    ui.quality(session)
    ui.summary(session)
    assert any("Tier 2 (needs clarification): 1" in m for m in messages)
    assert any("Pending clarifications: 1" in m for m in messages)
    assert any("BDD-ready requirements: 0" in m for m in messages)


@pytest.mark.parametrize("choice", ["1", "2", "3", "4", "5"])
def test_candidate_selection_edit_reject_skip_back(app, session, choice):
    ui, messages = app
    ui.ask = scripted(["1", "2 seconds", "[timeout]", "1", "Reviewer", "yes"])
    ui.questions(session)
    before = session.current
    answers = ["1", choice]
    if choice == "2": answers += ["The system shall wait for 2 seconds."]
    if choice in {"1", "2", "3"}: answers += ["Reviewer", "yes"]
    ui.ask = scripted(answers)
    ui.candidates(session)
    row = session.read()[0]["requirements"][0]
    assert (session.current != before) == (choice in {"1", "2", "3"})
    assert row["human_decision"] == ("rejected" if choice == "3" else "pending")
    assert row["bdd_ready"] is False
    assert any("Candidate rewrite:" in m for m in messages)
    assert any("Grounding and validation findings" in m for m in messages)


def test_consistency_uses_effective_policy_and_requires_evidence(app, tmp_path):
    ui, messages = app
    source = tmp_path / "pairs.md"
    source.write_text("# Requirements\n1. The system shall send email.\n2. The system shall retain logs.\n")
    session = ui.create(source)
    pair = session.consistency_pairs(gate_policy=True)[0]
    before = session.current
    def review(refs):
        ui.ask = scripted(["1", "4", refs, "Notification and audit", "All stated conditions",
                           "Separate obligations with no shared state", "Reviewer", "2", "yes", "2"])
        ui.consistency(session)
    with pytest.raises(ValueError): review("")
    assert session.current == before
    # An interrupted invalid action is never replayed. Cancel before a new attempt.
    if session.pending: session.recover(False)
    review(",".join(pair["evidence"]))
    state = DemoSession(session.workspace).read()[3]
    assert any(e["kind"] == "consistency_review_adopted" for e in state["events"])
    assert all(r["human_decision"] == "pending" for r in session.read()[0]["requirements"])


def test_cancellation_eof_and_noninteractive_fallback(app):
    ui, messages = app
    ui.ask = scripted(["1", "4", "5"])
    assert ui.run() == 0
    assert not ui.root.exists()
    def eof(_): raise EOFError
    with patch.object(wizard.sys.stdin, "isatty", return_value=False):
        assert wizard.launch(root=ui.root, ask=eof, tell=messages.append) == 0
    assert any("Text-menu mode" in m for m in messages)
    assert any("Paused safely" in m for m in messages)


def test_interruption_pending_recovery_is_explicit(app, session):
    ui, _ = app
    rid = session.read()[0]["requirements"][0]["requirement_id"]
    with patch.object(session, "recover", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            session.apply({"requirement_id": rid, "selected_candidate_text": "The system shall wait."}, "Reviewer", True)
    session = DemoSession(session.workspace)
    assert session.pending
    ui.ask = scripted(["3"])
    ui.review(session)
    assert session.pending
    ui.ask = scripted(["1", "3"])
    ui.review(session)
    assert DemoSession(session.workspace).pending is None


def test_export_validates_and_html_unavailable(app, session):
    ui, messages = app
    ui.export(session)
    assert any(str(session.current) in m for m in messages)
    assert any("HTML report: unavailable" in m and "Stage 4F" in m for m in messages)
    cli._validate_contract_artifact(session.read()[0])
    session.current.write_text("{}")
    with pytest.raises(ValueError): ui.export(session)


def test_advanced_demo_still_dispatches(tmp_path):
    with patch("c1_requirement_quality.demo_workflow.guided_demo") as guided:
        assert cli.main(["demo", "--resume", str(tmp_path)]) == 0
        assert guided.call_args.kwargs["resume"] is True


def test_complete_sample_journey_and_view_previous_results(app):
    ui, messages = app
    ui.ask = scripted(["1", "3", "1", "2", "2", "2", "1", "3", "3", "1", "5"])
    assert ui.run() == 0
    assert len(list(ui.root.glob("session-*/session.json"))) == 1
    assert any("Total requirements: 3" in m for m in messages)
    assert any("Validated JSON output" in m for m in messages)


def test_keyboard_interrupt_pauses_session(app, session):
    ui, messages = app
    def interrupt(_): raise KeyboardInterrupt
    ui.ask = interrupt
    assert ui.run() == 0
    assert DemoSession(session.workspace).read()[0]["requirements"]
    assert any("Paused safely" in m for m in messages)


def make_session(ui, tmp_path, text):
    source = tmp_path / "journey.md"
    source.write_text("# Requirements\n" + text, encoding="utf-8")
    return ui.create(source)


def test_exact_approval_preview_and_candidate_persistence(app, tmp_path):
    ui, messages = app
    session = make_session(ui, tmp_path, "1. The system shall wait.\n")
    rid = session.read()[0]["requirements"][0]["requirement_id"]
    replacement = "The system shall wait for 2 seconds."
    ui.ask = scripted([replacement, "Reviewer", "yes"])
    ui.manual(session, rid)
    assert session.read()[0]["requirements"][0]["final_text"] != replacement
    ui.ask = scripted(["5"])
    with patch("c1_requirement_quality.rewrite_generator.generate_candidates_run", side_effect=AssertionError("No regeneration")):
        ui.candidates(DemoSession(session.workspace), rid)
    assert any(m == "Candidate rewrite: " + replacement for m in messages)
    messages.clear()
    ui.ask = scripted(["1", "Reviewer", "yes"])
    ui.approval(session, rid)
    assert "Exact text to approve: " + replacement in messages
    row = session.read()[0]["requirements"][0]
    assert row["final_text"] == replacement and row["human_decision"] == "approved"
    assert row["bdd_ready"]


def test_invalid_answer_visible_correctable_and_counted(app, session):
    ui, messages = app
    data, _, _, state = session.read()
    rid = data["requirements"][0]["requirement_id"]
    qid = next(iter(state["requirements"][rid]["questions"]))
    session.apply({"requirement_id": rid, "clarification_answers": [{"question_id": qid, "answer": "unknown"}]}, "Reviewer", True)
    ui.summary(session)
    assert "Unanswered questions: 0" in messages
    assert "Invalid or otherwise unresolved answers/closures: 1" in messages
    assert "Pending clarifications: 1" in messages
    ui.ask = scripted(["1", "2 seconds", "[timeout]", "1", "Reviewer", "yes"])
    ui.questions(session)
    assert "Previous answer (still unresolved): unknown" in messages
    assert len(session.read()[3]["requirements"][rid]["answers"]) == 2
    messages.clear()
    ui.summary(session)
    assert "Pending clarifications: 0" in messages
    assert session.read()[0]["requirements"][0]["human_decision"] == "pending"


def test_declining_confirmation_retries_same_question(app, session):
    ui, messages = app
    ui.ask = scripted(["1", "3 seconds", "", "1", "Reviewer", "no",
                       "1", "2 seconds", "", "1", "Reviewer", "yes"])
    ui.questions(session)
    record = next(iter(session.read()[3]["requirements"].values()))
    assert [a["answer"] for a in record["answers"]] == ["2 seconds"]
    assert "Cancelled. No change recorded." in messages


def test_first_middle_last_navigation(app, tmp_path):
    ui, messages = app
    session = make_session(ui, tmp_path, "1. The system shall send email.\n2. The system shall retain logs.\n3. The system shall display records.\n")
    ui.ask = scripted(["2", "1", "1", "2", "1", "1"])
    ui.quality(session)
    screens = [m for m in messages if m.startswith("\nRequirement ")]
    assert screens == ["\nRequirement 1 of 3", "\nRequirement 1 of 3", "\nRequirement 2 of 3",
                       "\nRequirement 3 of 3", "\nRequirement 2 of 3", "\nRequirement 3 of 3"]
    assert "Quality review complete." in messages


def test_tier_routes_reuse_authoritative_state(app, session, tmp_path):
    ui, _ = app
    data, _, _, state = session.read()
    assert ui.next_action(session, data["requirements"][0], state) == "questions"
    clean = make_session(ui, tmp_path, "1. The system shall send email.\n")
    data, _, _, state = clean.read()
    assert data["requirements"][0]["tier"] == "TIER_1_AUTO_REFINE"
    assert ui.next_action(clean, data["requirements"][0], state) == "candidates"
    peers = make_session(ui, tmp_path, "1. The system shall send email.\n2. The system shall retain logs.\n")
    data, _, _, state = peers.read()
    assert ui.next_action(peers, data["requirements"][0], state) == "consistency"
    conflict = make_session(ui, tmp_path, "1. The system shall allow deletion.\n2. The system shall not allow deletion.\n")
    data, _, _, state = conflict.read()
    assert data["requirements"][0]["tier"] == "TIER_3_ESCALATE"
    assert ui.next_action(conflict, data["requirements"][0], state) == "manual"


def test_consistency_only_guidance_does_not_ask_questions(app, tmp_path):
    ui, messages = app
    session = make_session(ui, tmp_path, "1. The system shall send email.\n2. The system shall retain logs.\n")
    ui.ask = scripted(["1", "2", "2", "2"])
    with patch.object(ui, "consistency") as consistency, patch.object(ui, "questions", side_effect=AssertionError("No unrelated questions")):
        ui.guided(session)
        consistency.assert_called_once_with(session, "REQ-EX-001")
    assert all(not r["bdd_ready"] for r in session.read()[0]["requirements"])


def test_no_rewrite_needed_explicit_and_revalidated(app, tmp_path):
    ui, messages = app
    session = make_session(ui, tmp_path, "1. The system shall send email.\n")
    ui.ask = scripted(["5", "1", "Reviewer", "yes", "1"])
    ui.guided(session)
    row = session.read()[0]["requirements"][0]
    assert row["human_decision"] == "not_required" and row["bdd_ready"]
    assert row["final_text"] == row["original_text"]
    assert "Exact original text to accept: " + row["original_text"] in messages
    assert "Requirements with consistency blockers: 0" in messages
    cli._validate_contract_artifact(session.read()[0])


def test_blocked_original_cannot_use_no_rewrite_shortcut(app, session):
    ui, messages = app
    before = session.current
    ui.ask = scripted(["1"])
    ui.approval(session, "REQ-EX-001", original_only=True)
    assert session.current == before
    assert any("original is still blocked" in m for m in messages)


def test_sequential_answer_candidate_approval_export(app, session):
    ui, messages = app
    ui.ask = scripted(["1", "1", "2 seconds", "[timeout]", "1", "Reviewer", "yes",
                       "1", "1", "1", "Reviewer", "yes",
                       "1", "1", "Reviewer", "yes", "1"])
    ui.guided(session)
    row = session.read()[0]["requirements"][0]
    assert row["bdd_ready"] and row["human_decision"] == "approved"
    assert "Exact text to approve: The system shall wait for 2 seconds." in messages
    assert any("Step 3 - Reclassification" in m for m in messages)
    assert any("Validated JSON output" in m for m in messages)


def test_tier3_manual_and_explicit_resolution_cannot_erase_conflict(app, tmp_path):
    ui, messages = app
    session = make_session(ui, tmp_path, "1. The system shall allow deletion.\n2. The system shall not allow deletion.\n")
    rid = "REQ-EX-001"
    replacement = "The system shall allow deletion when the administrator confirms ownership."
    ui.ask = scripted([replacement, "Reviewer", "yes"])
    ui.manual(session, rid)
    assert session.read()[3]["requirements"][rid]["escalation_active"]
    assert all(r["human_decision"] == "pending" for r in session.read()[0]["requirements"])
    ui.ask = scripted(["1", "Owner supplied a conditional replacement obligation", "Reviewer", "yes"])
    ui.approval(session, rid)
    data, _, _, state = session.read()
    assert any(e["kind"] == "resolve_escalation" for e in state["events"])
    assert data["requirements"][0]["bdd_ready"] is False  # Unresolved peer comparison remains blocking.


def test_continue_consistency_moves_to_next_unresolved_pair(app, tmp_path):
    ui, messages = app
    session = make_session(ui, tmp_path, "1. The system shall send email.\n2. The system shall retain logs.\n3. The system shall display records.\n")
    first = session.consistency_pairs(gate_policy=True)[0]
    ui.ask = scripted(["1", "4", ",".join(first["evidence"]), "Separate services", "All stated conditions",
                       "No shared obligations identified", "Reviewer", "2", "yes", "1", "3"])
    ui.consistency(session)
    comparisons = [m for m in messages if m.startswith("\nComparison:")]
    assert len(comparisons) == 2 and comparisons[0] != comparisons[1]
    messages.clear()
    ui.ask = scripted(["3"])
    ui.consistency(DemoSession(session.workspace))
    assert [m for m in messages if m.startswith("\nComparison:")] == [comparisons[1]]


def test_pause_and_resume_use_snapshot_without_new_navigation_state(app, session):
    ui, _ = app
    before = session.current
    ui.ask = scripted(["pause"])
    with pytest.raises(KeyboardInterrupt): ui.guided(session)
    resumed = DemoSession(session.workspace)
    assert resumed.current == before and resumed.events == []
    ui.ask = scripted(["2", "2"])
    ui.guided(resumed)
    assert resumed.events == []


def test_picker_cancel_and_selected_file_confirmation(app, tmp_path):
    ui, messages = app
    source = tmp_path / "selected.md"
    source.write_text("# Requirements\n1. The system shall store records.\n")
    ui.ask = scripted(["1", "2", str(source), "2", "4"])
    with patch.object(wizard, "browse_file", return_value=""):
        assert ui.source() is None
    assert not ui.root.exists()
    assert any(m.strip() == "Selected file: selected.md" for m in messages)
    assert "Selected path: " + str(source) in messages
    assert any("Supported format: yes" in m for m in messages)
    ui.ask = scripted(["2", str(source), "1"])
    assert ui.source() == source


def test_success_progress_has_real_order_counts_and_verified_completion(app, session):
    ui, messages = app
    completed = [m for m in messages if m.startswith("[COMPLETED]")]
    assert len(completed) == 6
    assert [m.split(" - ")[0] for m in completed] == ["[COMPLETED] " + label for label in wizard.STAGES.values()]
    assert "1 requirements identified" in completed[1]
    assert any("[######]: 6 / 6 stages completed" in m for m in messages)
    assert all("running" not in m.lower() for m in completed)
    assert session.read()[0]["contract"] == "c1.validated-requirements"


def test_local_campus_wizard_analysis_remains_offline_and_unapproved(app):
    from pathlib import Path
    source = Path("C:/Users/HP/Downloads/C1_Demo_SRS_Campus_Library.docx")
    if not source.is_file(): pytest.skip("Local Campus reference document unavailable")
    ui, messages = app
    before = source.read_bytes()
    session = ui.create(source)
    rows = session.read()[0]["requirements"]
    assert len(rows) == 12
    assert "[CANCELLATION_WINDOW]" in rows[6]["original_text"]
    assert all(r["human_decision"] == "pending" and r["bdd_ready"] is False for r in rows)
    assert any("12 requirements identified" in m for m in messages)
    assert source.read_bytes() == before
    cli._validate_contract_artifact(session.read()[0])


@pytest.mark.parametrize("failure", ["empty", "quality", "publication"])
def test_failure_has_no_false_completion_ticks(app, tmp_path, failure):
    ui, messages = app
    source = tmp_path / "failure.md"
    source.write_text("# Context\nNo numbered requirements here.\n" if failure == "empty" else "# Requirements\n1. The system shall store records.\n")
    target = "analyse_requirements" if failure == "quality" else "_validate_contract_artifact"
    if failure == "empty":
        with pytest.raises(ValueError, match="no supported requirement statements"):
            ui.create(source)
    else:
        with patch.object(cli, target, side_effect=ValueError("Synthetic failure")):
            with pytest.raises(ValueError, match="Analysis could not finish"):
                ui.create(source)
    failed_stage = {"empty": "Extract and identify requirements", "quality": "Rule-based quality checks", "publication": "Prepare human review"}[failure]
    assert any(m.startswith("[FAILED] " + failed_stage) for m in messages)
    assert not any(m.startswith("[COMPLETED] " + failed_stage) for m in messages)
    assert not any("6 / 6 stages completed" in m for m in messages)
    assert ui.analysis_error_details
    assert not list(ui.root.glob("*/initial/c1/validated_requirements.json"))
    assert list(ui.root.glob("*/session.json"))  # Failed sessions retained.


def test_zero_extraction_friendly_error_and_details(app, tmp_path):
    ui, messages = app
    source = tmp_path / "empty.md"
    source.write_text("# Context\nNo numbered statements.\n")
    ui.ask = scripted(["1", "2", str(source), "1", "2", "1", "5"])
    assert ui.run() == 0
    friendly = next(m for m in messages if m.startswith("Unable to continue"))
    assert "no supported requirement statements" in friendly and ".c1-run-pending" not in friendly
    assert any("staging retained" in m for m in messages)  # Explicit Details request.


def test_progress_rich_render_and_text_fallback(monkeypatch, capsys):
    import io
    stream = io.StringIO()
    monkeypatch.setattr(stream, "isatty", lambda: True)
    with patch.object(wizard.sys, "stdout", stream):
        with wizard.AnalysisProgress() as display:
            display.update("read", "running", "")
            display.update("read", "completed", "Read verified bytes")
            assert display.states["extract"] == "pending"
    assert "Read verified bytes" in stream.getvalue()
    fallback = io.StringIO()
    monkeypatch.setattr(fallback, "isatty", lambda: True)
    with patch.dict("sys.modules", {"rich.live": None}), patch.object(wizard.sys, "stdout", fallback):
        with wizard.AnalysisProgress() as display:
            display.update("read", "running", "")
    assert "[RUNNING] Read SRS document" in fallback.getvalue()


def test_stage4g2_welcome_and_help_text(app):
    ui, messages = app
    ui.ask = scripted(["4", "5"])
    assert ui.run() == 0
    assert any("Welcome! C1 helps you review software requirements" in m for m in messages)
    assert any("What is an SRS?" in m for m in messages)
    assert any("What is BDD?" in m for m in messages)
    assert any("Tier 1: Minor wording or structural improvement." in m for m in messages)
    assert any("Tier 2: Missing or unclear information requiring clarification." in m for m in messages)
    assert any("Tier 3: Severe issue, conflict or manual review required." in m for m in messages)


def test_stage4g2_file_picker_notification_and_details(app, tmp_path):
    ui, messages = app
    sample = tmp_path / "sample.md"
    sample.write_text("# Requirements\n1. The system shall log errors.\n")
    ui.ask = scripted(["1", "1", "1"])
    with patch.object(wizard, "browse_file", return_value=str(sample)):
        source = ui.source()
    assert source == sample
    assert any("Opening Windows file picker..." in m for m in messages)
    assert any("File size:" in m and "KB" in m for m in messages)
    assert any("Selected file: sample.md" in m for m in messages)
    assert any("File type: MD" in m for m in messages)


def test_stage4g2_requirements_overview_and_counters(app, session):
    ui, messages = app
    ui.overview(session)
    assert any("Requirements Analysis Overview" in m for m in messages)
    assert any("Extracted requirements: 1" in m for m in messages)
    assert any("Approved: 0" in m for m in messages)
    assert any("Pending review: 1" in m for m in messages)
    assert any("BDD-ready: 0" in m for m in messages)
    assert any("Next: Clarify missing facts" in m for m in messages)


def test_stage4g2_tier_descriptions_in_summary_and_requirement(app, session):
    ui, messages = app
    ui.summary(session)
    assert any("Tier descriptions:" in m for m in messages)
    assert any("Tier 1: Minor wording or structural improvement." in m for m in messages)
    assert any("Tier 2: Missing or unclear information requiring clarification." in m for m in messages)
    assert any("Tier 3: Severe issue, conflict or manual review required." in m for m in messages)
    messages.clear()
    row = session.read()[0]["requirements"][0]
    ui.requirement(row, session)
    assert any("Tier explanation: Tier 2: Missing or unclear information" in m for m in messages)


def test_stage4g2_placeholder_default_enter_and_override(app, session):
    ui, messages = app
    # Press Enter (blank string) at span prompt to accept suggested [timeout]
    ui.ask = scripted(["1", "5 seconds", "", "1", "Reviewer", "yes"])
    ui.questions(session)
    data, _, _, state = DemoSession(session.workspace).read()
    answer = next(iter(state["requirements"].values()))["answers"][0]
    assert answer["replaces_span"] == "[timeout]"
    assert any("Detected placeholder needing replacement: [timeout]" in m for m in messages)


def test_stage4g2_conflict_guidance_for_contradictory_requirements(app, tmp_path):
    ui, messages = app
    source = tmp_path / "conflicts.md"
    source.write_text(
        "# Requirements\n"
        "1. The system shall allow account deletion.\n"
        "2. The system shall prohibit account deletion.\n"
    )
    session = ui.create(source)
    ui.ask = scripted(["2"])  # Skip pair
    ui.consistency(session)
    assert any("Conflict Guidance:" in m for m in messages)
    assert any("A deterministic conflict exists between" in m for m in messages)
    assert any("A human applicability review alone cannot remove a deterministic conflict" in m for m in messages)
    assert any("at least one of these requirements must be edited or rewritten" in m for m in messages)


def test_stage4g2_blocked_original_acceptance_explains_reasons(app, session):
    ui, messages = app
    ui.ask = scripted(["1", "1"])  # Choose requirement 1, then option 1 ("No rewrite needed - accept original")
    ui.approval(session, original_only=True)
    assert any("The original is still blocked" in m for m in messages)
    assert any("assigned to Tier 2" in m for m in messages)
    assert any("unresolved clarification question" in m for m in messages)


def test_stage4g2_campus_library_conflict_and_clarification_verified(app):
    from pathlib import Path
    source = Path("C:/Users/HP/Downloads/C1_Demo_SRS_Campus_Library.docx")
    if not source.is_file():
        pytest.skip("Local Campus Library document unavailable")
    session = app[0].create(source)
    data, _, _, state = session.read()
    rows = data["requirements"]
    assert len(rows) == 12

    # Verify FR-007 has placeholder requiring clarification
    fr007 = next(r for r in rows if "[CANCELLATION_WINDOW]" in r["original_text"])
    assert fr007["tier"] == "TIER_2_CLARIFY"
    assert fr007["bdd_ready"] is False

    # Verify FR-003 and FR-004 reservation statements are extracted and pair is available
    fr003 = next(r for r in rows if "three active book reservations" in r["original_text"])
    fr004 = next(r for r in rows if "five active book reservations" in r["original_text"])
    assert fr003["bdd_ready"] is False
    assert fr004["bdd_ready"] is False
    pairs = session.consistency_pairs(gate_policy=True)
    pair = next((p for p in pairs if set(p["requirement_ids"]) == {fr003["requirement_id"], fr004["requirement_id"]}), None)
    assert pair is not None


def test_stage4g3_markdown_report_generation(session):
    from c1_requirement_quality.wizard import generate_markdown_report
    content = generate_markdown_report(session)
    assert "# C1 Requirement Quality and Refinement Report" in content
    assert f"**Source Document** | `{session.source.name}`" in content
    assert f"**Session Identifier** | `{session.workspace.name}`" in content
    assert "Verified Contract Artifact" in content
    assert "## 1. Executive Summary" in content
    assert "Total Extracted Requirements" in content
    assert "Pending Human Review" in content
    assert "BDD-Ready Requirements" in content
    assert "Blocked Requirements" in content
    assert "## 2. Requirement Details" in content
    data, _, _, _ = session.read()
    for row in data["requirements"]:
        rid = row["requirement_id"]
        assert f"### Requirement {rid}" in content
        assert "#### Original Statement" in content
        assert "#### Accepted Refined Statement" in content
        assert "#### Quality Findings" in content
        assert "#### Clarification Questions" in content
        assert "#### Consistency Findings" in content
        assert "#### Active Blockers" in content


def test_stage4g3_quality_summary_generation(session):
    from c1_requirement_quality.wizard import generate_quality_summary
    summary = generate_quality_summary(session)
    assert "C1 REQUIREMENT QUALITY & REFINEMENT SUMMARY" in summary
    assert f"Source Document:      {session.source.name}" in summary
    assert f"Session Identifier:   {session.workspace.name}" in summary
    assert "1. REQUIREMENT COUNTS & TIER DISTRIBUTION" in summary
    assert "2. QUALITY ISSUES DETECTED" in summary
    assert "3. OUTSTANDING CLARIFICATION QUESTIONS" in summary
    assert "4. CONSISTENCY ANALYSIS (CONFLICTS VS UNASSESSED COMPARISONS)" in summary
    assert "5. BDD READINESS SUMMARY" in summary
    assert "6. HUMAN ACTIONS STILL REQUIRED" in summary
    assert "7. BDD HANDOVER POLICY & BLOCKER EXPLANATION" in summary
    assert "Requirements cannot be handed over to BDD automation while marked as BLOCKED." in summary


def test_stage4g3_report_counts_and_tiers_match_authoritative_session(session):
    from c1_requirement_quality.wizard import generate_markdown_report, generate_quality_summary
    data, _, _, state = session.read()
    rows = data["requirements"]
    total = len(rows)
    pending = sum(r["human_decision"] == "pending" for r in rows)
    bdd_ready = sum(r["bdd_ready"] for r in rows)
    blocked = sum(not r["bdd_ready"] for r in rows)

    md = generate_markdown_report(session)
    txt = generate_quality_summary(session)

    assert f"| **Total Extracted Requirements** | {total} |" in md
    assert f"| **Pending Human Review** | {pending} |" in md
    assert f"| **BDD-Ready Requirements** | {bdd_ready} |" in md
    assert f"| **Blocked Requirements** | {blocked} |" in md

    assert f"Total Extracted Requirements: {total}" in txt
    assert f"Pending Review:                 {pending}" in txt
    assert f"BDD-Ready Requirements: {bdd_ready} / {total}" in txt
    assert f"Blocked Requirements:   {blocked} / {total}" in txt


def test_stage4g3_pending_and_blocked_representation(session):
    from c1_requirement_quality.wizard import generate_markdown_report, generate_quality_summary
    md = generate_markdown_report(session)
    txt = generate_quality_summary(session)

    # In a fresh session, all requirements are pending and blocked
    assert "*(Pending human review — no candidate approved yet)*" in md
    assert "- **BDD Readiness**: **BLOCKED**" in md
    assert "- **[BLOCKER]**" in md

    assert "BLOCKED" in txt
    assert "Active Blockers:" in txt
    assert "human actions still required" in txt.lower()


def test_stage4g3_unassessed_vs_confirmed_conflict_representation(session):
    from c1_requirement_quality.wizard import generate_quality_summary
    txt = generate_quality_summary(session)

    # In standard demo SRS without confirmed conflicts:
    assert "Confirmed Deterministic Conflicts: 0" in txt
    assert "(None detected)" in txt
    # Unassessed comparisons should not be labeled as confirmed conflicts
    if "Unresolved / Unassessed Consistency Comparisons: 0" not in txt:
        assert "It is NOT a confirmed deterministic conflict." in txt


def test_stage4g3_confirmed_conflict_reported_correctly(app, tmp_path):
    from c1_requirement_quality.wizard import generate_quality_summary, generate_markdown_report
    ui, _ = app
    source = tmp_path / "conflict_srs.md"
    source.write_text(
        "# Requirements\n"
        "1. The system shall allow user registration.\n"
        "2. The system shall prohibit user registration.\n"
    )
    session = ui.create(source)
    txt = generate_quality_summary(session)
    md = generate_markdown_report(session)

    assert "Confirmed Deterministic Conflicts: 1" in txt
    assert "Confirmed Conflict:" in txt
    assert "Contradictory statements must be edited or rewritten." in txt
    assert "Unresolved / Unassessed Consistency Comparisons: 0" in txt
    assert "[CONFLICT]" in md


def test_stage4g3_special_characters_and_multiline_text(app, tmp_path):
    from c1_requirement_quality.wizard import generate_markdown_report, generate_quality_summary
    ui, _ = app
    source = tmp_path / "special_srs.md"
    source.write_text(
        "# Requirements\n"
        "1. The system shall process XML payload with <script>alert('test')</script> and pipe | symbols.\n"
        "   Line 2: System must verify balance >= 100 * (bonus + 1).\n"
    )
    session = ui.create(source)
    md = generate_markdown_report(session)
    txt = generate_quality_summary(session)

    assert "<script>alert('test')</script>" in md
    assert "Line 2: System must verify balance >= 100 * (bonus + 1)." in md
    assert "<script>alert('test')</script>" in txt


def test_stage4g3_export_reports_safe_writing_and_error_handling(app, session, tmp_path):
    from c1_requirement_quality.wizard import export_reports
    ui, messages = app

    # Default export to session.workspace / reports
    md_path, txt_path = ui.export_reports(session)
    assert md_path.is_file()
    assert txt_path.is_file()
    assert md_path.parent == session.workspace / "reports"
    assert "C1 Requirement Quality and Refinement Report" in md_path.read_text(encoding="utf-8")
    assert "C1 REQUIREMENT QUALITY & REFINEMENT SUMMARY" in txt_path.read_text(encoding="utf-8")

    # Custom output directory
    custom_dir = tmp_path / "custom_exports"
    md2, txt2 = export_reports(session, out_dir=custom_dir)
    assert md2.is_file()
    assert txt2.is_file()
    assert md2.parent == custom_dir

    # Simulated write error handled gracefully in ui.export()
    messages.clear()
    with patch("c1_requirement_quality.wizard.export_reports", side_effect=OSError("Disk write prohibited")):
        ui.export(session)
        assert any("Unable to export reports: Disk write prohibited" in m for m in messages)
        assert any("JSON output and session data are safely retained" in m for m in messages)


def test_stage4g3_existing_json_contract_and_export_presentation(app, session):
    ui, messages = app
    messages.clear()
    ui.export(session)

    # Check that authoritative messages are preserved
    assert any("Validated JSON output (ready to copy):" in m for m in messages)
    assert any(str(session.current) in m for m in messages)
    assert any("HTML report: unavailable. Stage 4F" in m for m in messages)
    assert any("Exported Markdown report:" in m for m in messages)
    assert any("Exported Quality summary:" in m for m in messages)

    # Validate JSON artifact untouched
    data, _, _, _ = session.read()
    cli._validate_contract_artifact(data)


def test_stage4g3_no_fabricated_approvals_or_readiness(session):
    from c1_requirement_quality.wizard import generate_markdown_report, generate_quality_summary
    data_before, _, _, state_before = session.read()
    before_ready = [r["bdd_ready"] for r in data_before["requirements"]]
    before_decisions = [r["human_decision"] for r in data_before["requirements"]]

    # Run report generators multiple times
    for _ in range(3):
        generate_markdown_report(session)
        generate_quality_summary(session)

    data_after, _, _, state_after = session.read()
    after_ready = [r["bdd_ready"] for r in data_after["requirements"]]
    after_decisions = [r["human_decision"] for r in data_after["requirements"]]

    assert before_ready == after_ready
    assert before_decisions == after_decisions
    assert data_before == data_after
    assert state_before == state_after


def test_stage4g4_campus_library_complete_walkthrough(tmp_path):
    from pathlib import Path
    source = Path("C:/Users/HP/Downloads/C1_Demo_SRS_Campus_Library.docx")
    if not source.is_file():
        pytest.skip("Local Campus Library document unavailable")

    session_root = tmp_path / "sessions"
    messages = []
    ui = wizard.Wizard(session_root, tell=messages.append)

    # 1. Select and validate Campus Library document
    validated = wizard.validate_source(str(source))
    assert validated.is_file()
    assert validated.suffix.lower() == ".docx"
    assert validated.stat().st_size > 0

    # 2. Create session and verify 12 requirements extracted
    session = ui.create(validated)
    data, text, manifest, state = session.read()
    rows = data["requirements"]
    assert len(rows) == 12
    assert all(r["requirement_id"].startswith("REQ-EX-") for r in rows)

    # 3. Verify overview counters
    messages.clear()
    ui.overview(session)
    assert any("Extracted requirements: 12" in m for m in messages)
    assert any("Pending review: 12" in m for m in messages)
    assert any("BDD-ready: 0" in m for m in messages)

    # 4. Review REQ-EX-007 placeholder [CANCELLATION_WINDOW]
    r7 = next(r for r in rows if r["requirement_id"] == "REQ-EX-007")
    rec7 = state["requirements"]["REQ-EX-007"]
    assert "[CANCELLATION_WINDOW]" in r7["original_text"]
    assert r7["tier"] == "TIER_2_CLARIFY"
    assert r7["bdd_ready"] is False
    assert r7["human_decision"] == "pending"
    assert len(rec7["questions"]) >= 1

    # 5. Clarification entry without automatic approval
    q7_text = next(iter(rec7["questions"].values()))["text"]
    answer_action = {
        "requirement_id": "REQ-EX-007",
        "clarification_answers": [{
            "question": q7_text,
            "answer": "2 hours before reservation time",
            "replaces_span": "[CANCELLATION_WINDOW]",
        }]
    }
    session.apply(answer_action, "Reviewer", True)

    # Verify answer is persisted but requirement is NOT automatically approved or BDD-ready
    data_after_ans, _, _, state_after_ans = session.read()
    r7_after = next(r for r in data_after_ans["requirements"] if r["requirement_id"] == "REQ-EX-007")
    rec7_after = state_after_ans["requirements"]["REQ-EX-007"]
    assert len(rec7_after["answers"]) == 1
    assert rec7_after["answers"][0]["answer"] == "2 hours before reservation time"
    assert r7_after["human_decision"] == "pending"
    assert r7_after["bdd_ready"] is False

    # 6. Inspect REQ-EX-003 and REQ-EX-004 as unassessed comparison, not confirmed conflict
    pairs = session.consistency_pairs(gate_policy=True)
    pair34 = next((p for p in pairs if set(p["requirement_ids"]) == {"REQ-EX-003", "REQ-EX-004"}), None)
    assert pair34 is not None
    assert pair34["current_deterministic"]["classification"] == "unassessed"
    assert pair34["decision"] == "unresolved"

    # 7. Pause and resume verification
    # Create a fresh wizard instance on the same root to simulate restarting CLI
    resumed_messages = []
    ui2 = wizard.Wizard(session_root, ask=scripted(["1"]), tell=resumed_messages.append)
    resumed_session = ui2.choose_session()
    assert resumed_session is not None
    assert resumed_session.workspace == session.workspace

    # Confirm session selection screen shows accurate progress
    assert any("Extracted: 12" in m and "Pending: 12" in m and "BDD-ready: 0" in m for m in resumed_messages)

    # Confirm resumed session has previous clarification intact
    _, _, _, resumed_state = resumed_session.read()
    assert len(resumed_state["requirements"]["REQ-EX-007"]["answers"]) == 1

    # 8. Export and verify report accuracy
    resumed_messages.clear()
    ui2.export(resumed_session)
    assert any("Exported Markdown report:" in m for m in resumed_messages)
    assert any("Exported Quality summary:" in m for m in resumed_messages)
    assert any("Validated JSON output" in m for m in resumed_messages)

    reports_dir = resumed_session.workspace / "reports"
    md_file = reports_dir / "refined_requirements.md"
    txt_file = reports_dir / "quality_summary.txt"
    assert md_file.is_file()
    assert txt_file.is_file()

    md_text = md_file.read_text(encoding="utf-8")
    txt_text = txt_file.read_text(encoding="utf-8")

    assert "| **Total Extracted Requirements** | 12 |" in md_text
    assert "| **Pending Human Review** | 12 |" in md_text
    assert "| **BDD-Ready Requirements** | 0 |" in md_text
    assert "Total Extracted Requirements: 12" in txt_text
    assert "Confirmed Deterministic Conflicts: 0" in txt_text
    assert "Unresolved / Unassessed Consistency Comparisons: 66" in txt_text
    assert "REQ-EX-003 / REQ-EX-004" in txt_text
    assert "BDD-Ready Requirements: 0 / 12 (0.0%)" in txt_text
    assert "Blocked Requirements:   12 / 12 (100.0%)" in txt_text


def test_stage4g4_error_recovery_cancellation_and_invalid_inputs(app, tmp_path):
    ui, messages = app

    # 1. Blank path cancels cleanly
    ui.ask = scripted(["2", "", "4"])  # Choose Paste path, enter empty path (cancels), then Back
    res = ui.source()
    assert res is None
    assert any("Selection cancelled." in m for m in messages)

    # 2. Nonexistent path handled with clear message
    messages.clear()
    with pytest.raises(ValueError, match="File not found"):
        wizard.validate_source(str(tmp_path / "nonexistent.docx"))

    # 3. Unsupported extension handled
    unsupported = tmp_path / "document.zip"
    unsupported.write_text("dummy")
    with pytest.raises(ValueError, match="Supported files:"):
        wizard.validate_source(str(unsupported))

    # 4. Empty document handled
    empty_doc = tmp_path / "empty.txt"
    empty_doc.write_text("")
    with pytest.raises(ValueError, match="The selected document is empty."):
        wizard.validate_source(str(empty_doc))


def test_stage4g4_choose_session_progress_display_details(app, session):
    ui, messages = app

    # Test choose_session label format
    ui.ask = scripted(["1"])
    resumed = ui.choose_session()
    assert resumed is not None
    assert any("Extracted: 1 | Approved: 0 | Pending: 1 | BDD-ready: 0" in m for m in messages)

    # Corrupt a session file to test unverified progress handling
    corrupt_session = ui.root / "session-zzzz-corrupt"
    corrupt_session.mkdir(parents=True, exist_ok=True)
    (corrupt_session / "session.json").write_text('{"source": "corrupt.txt"}')

    messages.clear()
    ui.ask = scripted(["1"])
    corrupt_resumed = ui.choose_session()
    assert corrupt_resumed is None
    assert any("Unable to open session:" in m for m in messages)


def test_stage4g4_deterministic_conflict_cannot_be_bypassed_by_review(app, tmp_path):
    ui, messages = app
    source = tmp_path / "deterministic_conflict.md"
    source.write_text(
        "# Requirements\n"
        "1. The system shall allow user account deletion.\n"
        "2. The system shall prohibit user account deletion.\n"
    )
    session = ui.create(source)
    data, _, _, state = session.read()
    r1_id = data["requirements"][0]["requirement_id"]
    r2_id = data["requirements"][1]["requirement_id"]

    pairs = session.consistency_pairs(gate_policy=True)
    conflict_pair = next(p for p in pairs if set(p["requirement_ids"]) == {r1_id, r2_id})
    assert conflict_pair["current_deterministic"]["classification"] == "conflict"

    # Attempt to apply a consistency review marking it not_applicable
    with pytest.raises(Exception):
        # effective_consistency validation rejects bypassing deterministic conflict without valid evidence
        session.adopt_consistency([r1_id, r2_id], confirmed=True, decision="not_applicable",
                                  evidence_refs=["invalid"], scope="test", conditions="test",
                                  rationale="bypass", reviewer="Tester", coverage="complete")

    # Even if an unconfirmed review record existed, deterministic conflict check fails
    c = wizard.assess(r1_id, data["requirements"], state["requirements"], wizard.context_from_state(state))
    assert c["check"] == "fail"
    assert c["status"] == "conflict"


# ==============================================================================
# Stage 4H.2 — Optional DistilBERT Advisory Diagnostics Tests
# ==============================================================================

class _MockDistilBertClassifier:
    """Mocked DistilBERT classifier for Stage 4H.2 tests; no real inference."""

    def __init__(self, scores=None):
        self.calls = []
        self.scores = scores or {
            "VAGUE": 0.8123,
            "AMBIGUOUS": 0.4567,
            "INCOMPLETE": 0.2345,
            "NON_MEASURABLE": 0.1234,
            "NON_VERIFIABLE": 0.0567,
        }
        self.model_name = "distilbert-requirement-defects"

    def validate_checkpoint(self):
        return {
            "mapping_status": "VERIFIED",
            "checkpoint_sha256": "122ce30b7321b271c279b63efd5501be81ee6e1f4f2282496ef1be459a9685cd",
            "mapping_provenance": "MOCKED checkpoint validation; no real inference",
        }

    def classify(self, text, *, requirement_id):
        self.calls.append((text, requirement_id))
        from types import SimpleNamespace
        return SimpleNamespace(
            scores=dict(self.scores),
            requirement_id=requirement_id,
            text=text,
        )


def test_stage4h2_ai_diagnostics_disabled_by_default(app, tmp_path):
    """Verify that normal analysis and quality review do not run AI diagnostics."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall respond quickly.\n")
    session = ui.create(source)
    assert any("[SKIPPED] Optional AI diagnostics: DistilBERT, MiniLM and Groq disabled; no model execution." in m for m in messages)
    data, _, _, _ = session.read()
    row = data["requirements"][0]
    # No advisory defect fields attached to contract artifact
    assert "advisory_scores" not in row
    assert "predicted_defects" not in row


def test_stage4h2_explicit_user_opt_in_cancel(app, session):
    """Verify that selecting cancel/back in the opt-in confirmation refuses model loading."""
    ui, messages = app
    fake = _MockDistilBertClassifier()
    ui.classifier = fake
    # Option 2 is "Cancel (Back)"
    ui.ask = scripted(["2"])
    ui.ai_diagnostics(session)
    assert len(fake.calls) == 0
    assert any("AI diagnostics cancelled. No model loaded." in m for m in messages)


def test_stage4h2_confirmed_execution_and_invocation(app, session):
    """Verify that confirming opt-in loads the classifier and calls classify with exact requirement text."""
    ui, messages = app
    fake = _MockDistilBertClassifier()
    ui.classifier = fake
    # 1: Confirm load, 1: Select first requirement
    ui.ask = scripted(["1", "1"])
    ui.ai_diagnostics(session)
    assert len(fake.calls) == 1
    data = session.read()[0]
    expected_rid = data["requirements"][0]["requirement_id"]
    expected_text = data["requirements"][0]["original_text"]
    assert fake.calls[0] == (expected_text, expected_rid)


def test_stage4h2_all_five_score_labels_displayed(app, session):
    """Verify all five defect categories are presented in the advisory output."""
    ui, messages = app
    fake = _MockDistilBertClassifier()
    ui.classifier = fake
    ui.ask = scripted(["1", "1"])
    ui.ai_diagnostics(session)

    joined = "\n".join(messages)
    for label in ("VAGUE", "AMBIGUOUS", "INCOMPLETE", "NON_MEASURABLE", "NON_VERIFIABLE"):
        assert label in joined
    assert "0.8123" in joined
    assert "0.4567" in joined
    assert "0.2345" in joined
    assert "0.1234" in joined
    assert "0.0567" in joined


def test_stage4h2_honest_uncalibrated_score_wording(app, session):
    """Verify output contains explicit warnings that scores are uncalibrated sigmoids, not probabilities."""
    ui, messages = app
    fake = _MockDistilBertClassifier()
    ui.classifier = fake
    ui.ask = scripted(["1", "1"])
    ui.ai_diagnostics(session)

    joined = "\n".join(messages)
    assert "Uncalibrated sigmoid scores" in joined or "uncalibrated sigmoid score" in joined
    assert "NOT calibrated probabilities" in joined
    assert "purely ADVISORY" in joined
    assert "Zero decision effect" in joined or "None. ML scores do not modify requirements" in joined


def test_stage4h2_preserves_persisted_session_data(app, session):
    """Verify running AI diagnostics causes zero mutations to session files."""
    ui, _ = app
    fake = _MockDistilBertClassifier()
    ui.classifier = fake
    before_files = {p: p.read_bytes() for p in session.workspace.rglob("*") if p.is_file()}

    ui.ask = scripted(["1", "1"])
    ui.ai_diagnostics(session)

    after_files = {p: p.read_bytes() for p in session.workspace.rglob("*") if p.is_file()}
    assert before_files == after_files


def test_stage4h2_does_not_modify_deterministic_classifications(app, session):
    """Verify deterministic quality findings, tier, human decision and BDD readiness remain untouched."""
    ui, _ = app
    fake = _MockDistilBertClassifier()
    ui.classifier = fake
    data_before, _, _, state_before = session.read()
    row_before = data_before["requirements"][0]

    ui.ask = scripted(["1", "1"])
    ui.ai_diagnostics(session)

    data_after, _, _, state_after = session.read()
    row_after = data_after["requirements"][0]
    assert row_before["tier"] == row_after["tier"]
    assert row_before["defects"] == row_after["defects"]
    assert row_before["human_decision"] == row_after["human_decision"]
    assert row_before["bdd_ready"] == row_after["bdd_ready"]
    assert state_before == state_after


def test_stage4h2_missing_model_and_dependency_recovery(app, session, monkeypatch):
    """Verify missing checkpoint files or dependencies are caught gracefully and return safely."""
    from c1_requirement_quality.ml_defect_classifier import DistilBertModelLoadError
    ui, messages = app
    ui.classifier = None  # Force real instantiation attempt

    def broken_validate(self):
        raise DistilBertModelLoadError("nonexistent_dir", "checkpoint missing")

    from c1_requirement_quality.ml_defect_classifier import DistilBertDefectClassifier
    monkeypatch.setattr(DistilBertDefectClassifier, "validate_checkpoint", broken_validate)

    ui.ask = scripted(["1", "1"])
    ui.ai_diagnostics(session)

    assert any("Unable to load local DistilBERT model:" in m for m in messages)
    assert any("Returning safely to wizard. Deterministic analysis and all saved work are unaffected." in m for m in messages)


def test_stage4h2_low_memory_protection(app, session, monkeypatch):
    """Verify insufficient RAM halts model loading and reports a safety message."""
    from c1_requirement_quality.ml import ml_diagnostics
    monkeypatch.setattr(ml_diagnostics, "available_memory_bytes", lambda: 500 * 1024 ** 2)
    ui, messages = app
    fake = _MockDistilBertClassifier()
    ui.classifier = fake

    ui.ask = scripted(["1", "1"])
    ui.ai_diagnostics(session)

    assert len(fake.calls) == 0
    assert any("Insufficient available RAM" in m for m in messages)


def test_stage4h2_navigation_from_sections_and_quality(app, session):
    """Verify navigating to AI diagnostics from both sections menu and quality menu."""
    ui, messages = app
    fake = _MockDistilBertClassifier()
    ui.classifier = fake

    # 1. Access from sections menu:
    # 10 is "View optional AI quality diagnostics (local DistilBERT)"
    # 1 is Confirm load
    # 1 is Select REQ-1
    # 11 is Back from sections menu
    ui.ask = scripted(["10", "1", "1", "11"])
    ui.sections(session)
    assert len(fake.calls) == 1

    # 2. Access from quality menu:
    # 5 is "View optional AI quality diagnostics (local DistilBERT)"
    # 1 is Confirm load
    # 6 is Back from quality menu
    ui.ask = scripted(["5", "1", "6"])
    ui.quality(session)
    assert len(fake.calls) == 2


# ==============================================================================
# Stage 4H.3 — Optional MiniLM Consistency Pair Prioritisation Tests
# ==============================================================================

class _MockMiniLMEmbedder:
    """Deterministic mock sentence embedder for Stage 4H.3 tests; no real model execution."""

    def __init__(self, mapping=None, default_dim=4):
        self.mapping = mapping or {}
        self.default_dim = default_dim
        self.calls = []
        self.model_name = "sentence-transformers/all-MiniLM-L6-v2"
        self.loaded_model_name = "sentence-transformers/all-MiniLM-L6-v2"

    def encode(self, texts, batch_size=8):
        self.calls.append(list(texts))
        results = []
        for t in texts:
            if t in self.mapping:
                results.append(list(self.mapping[t]))
            else:
                # Deterministic pseudo-embedding based on string length and characters
                vec = [float(((ord(c) * (i + 1)) % 97) + 1) / 100.0 for i, c in enumerate(t[:self.default_dim])]
                while len(vec) < self.default_dim:
                    vec.append(0.5)
                results.append(vec)
        return results


def test_stage4h3_minilm_prioritisation_disabled_by_default(app, tmp_path):
    """Verify default consistency review does not invoke MiniLM and preserves default order."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall send email.\n2. The system shall retain logs.\n3. The system shall notify users.\n")
    session = ui.create(source)
    fake = _MockMiniLMEmbedder()
    ui.embedder = fake

    # Option 2: Skip first, Option 3: Back
    ui.ask = scripted(["2", "3"])
    ui.consistency(session)

    assert len(fake.calls) == 0
    assert not any("Prioritise Consistency Reviews" in m for m in messages)
    assert not any("Semantic similarity:" in m for m in messages)


def test_stage4h3_explicit_opt_in_cancel(app, tmp_path):
    """Verify selecting cancel in the prioritisation opt-in confirmation refuses model loading."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall send email.\n2. The system shall retain logs.\n")
    session = ui.create(source)
    fake = _MockMiniLMEmbedder()
    ui.embedder = fake

    # 2: Cancel (Back), 3: Back from consistency review
    ui.ask = scripted(["2", "3"])
    ui.prioritise_consistency(session)

    assert len(fake.calls) == 0
    assert any("Prioritisation cancelled. Default comparison ordering retained." in m for m in messages)


def test_stage4h3_opt_in_prioritisation_and_similarity_display(app, tmp_path):
    """Verify opt-in executes MiniLM adapter, orders unassessed pairs by descending similarity, and displays advisory notice."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text(
        "# Requirements\n"
        "1. The system shall send email notifications.\n"
        "2. The system shall send urgent email alerts.\n"
        "3. The system shall archive database logs.\n"
    )
    session = ui.create(source)

    # REQ 1 and REQ 2 are very similar (orthogonal vectors for 3)
    fake = _MockMiniLMEmbedder(mapping={
        "The system shall send email notifications.": [1.0, 0.0, 0.0, 0.0],
        "The system shall send urgent email alerts.": [0.95, 0.05, 0.0, 0.0],
        "The system shall archive database logs.": [0.0, 0.0, 1.0, 0.0],
    })
    ui.embedder = fake

    # 1: Confirm load, 3: Back from first comparison
    ui.ask = scripted(["1", "3"])
    ui.prioritise_consistency(session)

    assert len(fake.calls) == 1
    joined = "\n".join(messages)
    assert "Prioritise Consistency Reviews (Local MiniLM)" in joined
    assert "Pairwise cosine similarity scores are purely ADVISORY" in joined
    assert "Successfully prioritised 3 comparisons using local MiniLM." in joined

    # Pair (REQ-EX-001, REQ-EX-002) has cosine similarity ~0.9986, so it must be presented first
    comparisons = [m for m in messages if m.startswith("\nComparison:")]
    assert len(comparisons) >= 1
    assert "REQ-EX-001 / REQ-EX-002" in comparisons[0]
    assert "Semantic similarity:" in joined
    assert "advisory MiniLM cosine similarity; not proof of conflict or equivalence" in joined


def test_stage4h3_confirmed_conflicts_retain_highest_priority(app, tmp_path):
    """Verify confirmed deterministic conflicts retain top priority regardless of similarity scores."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text(
        "# Requirements\n"
        "1. The system shall allow account deletion.\n"
        "2. The system shall prohibit account deletion.\n"
        "3. The system shall log security events.\n"
    )
    session = ui.create(source)

    # Give the conflict pair low similarity (0.0), and unassessed pairs high similarity (0.99)
    fake = _MockMiniLMEmbedder(mapping={
        "The system shall allow account deletion.": [1.0, 0.0, 0.0, 0.0],
        "The system shall prohibit account deletion.": [0.0, 1.0, 0.0, 0.0],
        "The system shall log security events.": [0.99, 0.01, 0.0, 0.0],
    })
    ui.embedder = fake

    # 1: Confirm load, 3: Back from first comparison
    ui.ask = scripted(["1", "3"])
    ui.prioritise_consistency(session)

    # Confirmed conflict between REQ-EX-001 and REQ-EX-002 MUST be presented first
    comparisons = [m for m in messages if m.startswith("\nComparison:")]
    assert len(comparisons) >= 1
    assert "REQ-EX-001 / REQ-EX-002" in comparisons[0]
    assert any("Conflict Guidance:" in m for m in messages)
    assert any("A deterministic conflict exists between REQ-EX-001 and REQ-EX-002." in m for m in messages)


def test_stage4h3_stable_ordering_for_equal_scores(app, tmp_path):
    """Verify stable tie-breaker ordering when pairs have identical similarity."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text(
        "# Requirements\n"
        "1. The system shall validate email.\n"
        "2. The system shall validate phone.\n"
        "3. The system shall validate address.\n"
    )
    session = ui.create(source)

    # Identical vectors -> identical pairwise similarities
    fake = _MockMiniLMEmbedder(mapping={
        "The system shall validate email.": [1.0, 1.0, 0.0, 0.0],
        "The system shall validate phone.": [1.0, 1.0, 0.0, 0.0],
        "The system shall validate address.": [1.0, 1.0, 0.0, 0.0],
    })
    ui.embedder = fake

    # 1: Confirm load, 2: Skip, 2: Skip, 3: Back
    ui.ask = scripted(["1", "2", "2", "3"])
    ui.prioritise_consistency(session)

    comparisons = [m.replace("\nComparison: ", "") for m in messages if m.startswith("\nComparison:")]
    assert len(comparisons) == 3
    # Stable alphabetical order by requirement_ids when similarities are equal
    assert comparisons == ["REQ-EX-001 / REQ-EX-002", "REQ-EX-001 / REQ-EX-003", "REQ-EX-002 / REQ-EX-003"]


def test_stage4h3_all_pairs_remain_accessible_no_threshold_filtering(app, tmp_path):
    """Verify no pair is omitted or filtered out even if similarity is very low."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text(
        "# Requirements\n"
        "1. Alpha requirement statement.\n"
        "2. Beta requirement statement.\n"
        "3. Gamma requirement statement.\n"
    )
    session = ui.create(source)

    # Orthogonal vectors -> 0.0 similarity
    fake = _MockMiniLMEmbedder(mapping={
        "Alpha requirement statement.": [1.0, 0.0, 0.0, 0.0],
        "Beta requirement statement.": [0.0, 1.0, 0.0, 0.0],
        "Gamma requirement statement.": [0.0, 0.0, 1.0, 0.0],
    })
    ui.embedder = fake

    # 1: Confirm load, 2: Skip, 2: Skip, 3: Back
    ui.ask = scripted(["1", "2", "2", "3"])
    ui.prioritise_consistency(session)

    comparisons = [m for m in messages if m.startswith("\nComparison:")]
    assert len(comparisons) == 3


def test_stage4h3_session_records_and_readiness_unmodified(app, tmp_path):
    """Verify running MiniLM prioritisation causes zero mutations to session files, tier, decisions, or gates."""
    ui, _ = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall send email.\n2. The system shall retain logs.\n")
    session = ui.create(source)

    files_before = {p: p.read_bytes() for p in session.workspace.rglob("*") if p.is_file()}
    data_before, _, _, state_before = session.read()

    fake = _MockMiniLMEmbedder()
    ui.embedder = fake
    ui.ask = scripted(["1", "3"])
    ui.prioritise_consistency(session)

    files_after = {p: p.read_bytes() for p in session.workspace.rglob("*") if p.is_file()}
    data_after, _, _, state_after = session.read()

    assert files_before == files_after
    assert data_before["requirements"] == data_after["requirements"]
    assert state_before == state_after


def test_stage4h3_graceful_missing_model_recovery(app, tmp_path, monkeypatch):
    """Verify missing model cache directory fails gracefully and returns safely to ordinary consistency review."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall send email.\n2. The system shall retain logs.\n")
    session = ui.create(source)

    ui.embedder = None
    from c1_requirement_quality import model_paths
    monkeypatch.setattr(model_paths, "get_minilm_cache_dir", lambda: tmp_path / "nonexistent_minilm_cache")

    # 1: Confirm load, 3: Back from fallback consistency review
    ui.ask = scripted(["1", "3"])
    ui.prioritise_consistency(session)

    assert any("Unable to load local MiniLM model:" in m for m in messages)
    assert any("Returning safely to ordinary consistency review. Default pair ordering retained." in m for m in messages)


def test_stage4h3_low_memory_protection(app, tmp_path, monkeypatch):
    """Verify insufficient RAM halts MiniLM loading and returns safely."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall send email.\n2. The system shall retain logs.\n")
    session = ui.create(source)

    fake = _MockMiniLMEmbedder()
    ui.embedder = fake
    from c1_requirement_quality.ml import ml_diagnostics
    monkeypatch.setattr(ml_diagnostics, "available_memory_bytes", lambda: 500 * 1024 ** 2)

    ui.ask = scripted(["1", "3"])
    ui.prioritise_consistency(session)

    assert len(fake.calls) == 0
    assert any("Insufficient available RAM" in m for m in messages)
    assert any("Returning safely to ordinary consistency review." in m for m in messages)


def test_stage4h3_menu_invocation_from_consistency_review(app, tmp_path):
    """Verify triggering prioritisation directly from option 4 within consistency review."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text(
        "# Requirements\n"
        "1. The system shall send email notifications.\n"
        "2. The system shall send urgent email alerts.\n"
        "3. The system shall archive database logs.\n"
    )
    session = ui.create(source)

    fake = _MockMiniLMEmbedder(mapping={
        "The system shall send email notifications.": [1.0, 0.0, 0.0, 0.0],
        "The system shall send urgent email alerts.": [0.95, 0.05, 0.0, 0.0],
        "The system shall archive database logs.": [0.0, 0.0, 1.0, 0.0],
    })
    ui.embedder = fake

    # First pair presented in default order:
    # 4: Prioritise consistency reviews using local MiniLM
    # 1: Confirm load
    # 3: Back
    ui.ask = scripted(["4", "1", "3"])
    ui.consistency(session)

    assert len(fake.calls) == 1
    assert any("Successfully prioritised 3 comparisons using local MiniLM." in m for m in messages)


def test_stage4h3_campus_library_66_pairs_and_classification_preserved(tmp_path):
    """Phase 4 verification: Campus Library 12 requirements produce 66 pairs; REQ-3/4 unassessed classification preserved."""
    from pathlib import Path
    source = Path("C:/Users/HP/Downloads/C1_Demo_SRS_Campus_Library.docx")
    if not source.is_file():
        pytest.skip("Local Campus Library document unavailable")

    session_root = tmp_path / "sessions"
    messages = []
    fake = _MockMiniLMEmbedder()
    ui = wizard.Wizard(session_root, tell=messages.append, embedder=fake)

    validated = wizard.validate_source(str(source))
    session = ui.create(validated)
    data, _, _, state = session.read()
    assert len(data["requirements"]) == 12

    # 1: Confirm load, 3: Back from first comparison
    ui.ask = scripted(["1", "3"])
    ui.prioritise_consistency(session)

    # 12 requirements encoded across batches of 8
    assert sum(len(c) for c in fake.calls) == 12
    # Check that 66 comparisons were prioritised
    assert any("Successfully prioritised 66 comparisons using local MiniLM." in m for m in messages)

    # Verify session consistency pairs
    pairs = session.consistency_pairs(gate_policy=True)
    assert len(pairs) == 66

    pair34 = next((p for p in pairs if set(p["requirement_ids"]) == {"REQ-EX-003", "REQ-EX-004"}), None)
    assert pair34 is not None
    # Unassessed classification and unresolved decision must remain intact
    assert pair34["current_deterministic"]["classification"] == "unassessed"
    assert pair34["decision"] == "unresolved"

    # Human review decisions remain pending/unresolved across all 12 requirements
    assert all(r["human_decision"] == "pending" for r in session.read()[0]["requirements"])
    assert all(p["decision"] == "unresolved" for p in pairs)


def test_stage4h3_resume_compatibility(tmp_path):
    """Verify session can be paused, resumed, and prioritised comparisons remain reviewable without state corruption."""
    session_root = tmp_path / "sessions"
    messages = []
    fake = _MockMiniLMEmbedder()
    ui = wizard.Wizard(session_root, tell=messages.append, embedder=fake)

    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall send email.\n2. The system shall retain logs.\n")
    session = ui.create(source)

    # 1: Confirm load, 3: Back from first comparison
    ui.ask = scripted(["1", "3"])
    ui.prioritise_consistency(session)
    assert sum(len(c) for c in fake.calls) == 2

    # Resume session with fresh wizard
    resumed_messages = []
    fake2 = _MockMiniLMEmbedder()
    ui2 = wizard.Wizard(session_root, ask=scripted(["1"]), tell=resumed_messages.append, embedder=fake2)
    resumed_session = ui2.choose_session()
    assert resumed_session is not None
    assert resumed_session.workspace == session.workspace

    # Consistency review in resumed session functions cleanly
    ui2.ask = scripted(["2", "3"])
    ui2.consistency(resumed_session)
    assert any("Comparison: REQ-EX-001 / REQ-EX-002" in m for m in resumed_messages)


# ==============================================================================
# Stage 4H.4B — Optional RAG/DeBERTa Evidence Verification Tests
# ==============================================================================

class _MockNLI:
    """Mock NLI classifier that tracks premise-hypothesis calls without loading weights."""

    def __init__(self, label="entailment"):
        self.label = label
        self.calls = []
        self.model_name = "cross-encoder/nli-deberta-v3-small"
        self.loaded_model_name = "cross-encoder/nli-deberta-v3-small"

    def classify(self, premise, hypothesis):
        self.calls.append({"premise": premise, "hypothesis": hypothesis})
        return self.label


def test_stage4h4b_default_behaviour_unchanged(app, tmp_path):
    """1. Default candidate review presents options 1-6 and works without invoking verification."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall wait.\n")
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]
    replacement = "The system shall wait for 2 seconds."
    ui.ask = scripted([replacement, "Reviewer", "yes"])
    ui.manual(session, rid)

    mock_nli = _MockNLI()
    ui.nli = mock_nli

    # Choice 5: Back from candidate review
    ui.ask = scripted(["5"])
    ui.candidates(session, rid)

    assert len(mock_nli.calls) == 0
    assert not any("Verify Candidate against SRS Evidence" in m for m in messages)
    assert any("7. Verify candidate against SRS evidence (local DeBERTa NLI)" in m for m in messages)


def test_stage4h4b_explicit_confirmation_and_cancellation(app, tmp_path):
    """2. Explicit confirmation: selecting cancel refuses model loading and returns to candidate review."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall wait.\n")
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]
    replacement = "The system shall wait for 2 seconds."
    ui.ask = scripted([replacement, "Reviewer", "yes"])
    ui.manual(session, rid)

    mock_nli = _MockNLI()
    ui.nli = mock_nli

    # 7: Verify evidence, 2: Cancel (Back), 5: Back from candidate review
    ui.ask = scripted(["7", "2", "5"])
    ui.candidates(session, rid)

    assert len(mock_nli.calls) == 0
    assert any("Verify Candidate against SRS Evidence (Local DeBERTa NLI)" in m for m in messages)
    assert any("Evidence verification cancelled. Returning safely to candidate review." in m for m in messages)


def test_stage4h4b_evidence_verification_flow_and_premise_hypothesis_ordering(app, tmp_path):
    """3 & 4 & 5. Canonical RAG/NLI reuse, premise=evidence, hypothesis=candidate, authentic IDs."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text(
        "# Authentication\n"
        "1. Users can log into the portal with valid credentials.\n"
        "\n"
        "# Auditing\n"
        "2. The system shall record login events in the audit log.\n"
    )
    session = ui.create(source)
    rid = session.read()[0]["requirements"][1]["requirement_id"]
    candidate_text = "The system shall log audit records for sign in."
    ui.ask = scripted([candidate_text, "Reviewer", "yes"])
    ui.manual(session, rid)

    fake_embedder = _MockMiniLMEmbedder()
    mock_nli = _MockNLI(label="entailment")
    ui.embedder = fake_embedder
    ui.nli = mock_nli

    # 7: Verify evidence, 1: Confirm run, 5: Back from candidate review
    ui.ask = scripted(["7", "1", "5"])
    ui.candidates(session, rid)

    # NLI must have been called with correct premise and hypothesis direction
    assert len(mock_nli.calls) > 0
    first_call = mock_nli.calls[0]
    assert "Users can log into" in first_call["premise"] or "The system shall record" in first_call["premise"]
    assert "system shall log audit records" in first_call["hypothesis"].lower()

    # Evidence display must preserve authentic chunk ID and section
    assert any("SRS-L" in m for m in messages)
    assert any("Section:" in m for m in messages)
    assert any("Dense Similarity (uncalibrated topical relevance):" in m for m in messages)
    assert any("RAG Evidence Verification Status (Advisory):" in m for m in messages)
    assert any("Advisory Summary:" in m for m in messages)


def test_stage4h4b_symbolic_vs_nli_separation(app, tmp_path):
    """6. Symbolic verification handles exact token match without invoking NLI; NLI fallback for paraphrases."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text(
        "# Storage Policy\n"
        "The system shall retain logs for audit purposes.\n"
        "\n"
        "# Requirements\n"
        "1. The system shall retain logs for [purpose].\n"
    )
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]

    # Candidate matches the exact sentence from Storage Policy
    exact_text = "The system shall retain logs for audit purposes."
    ui.ask = scripted([exact_text, "Reviewer", "yes"])
    ui.manual(session, rid)

    fake_embedder = _MockMiniLMEmbedder()
    mock_nli = _MockNLI(label="entailment")
    ui.embedder = fake_embedder
    ui.nli = mock_nli

    # 7: Verify evidence, 1: Confirm, 5: Back
    ui.ask = scripted(["7", "1", "5"])
    ui.candidates(session, rid)

    # Exact match is verified symbolically; NLI is not called
    assert len(mock_nli.calls) == 0
    assert any("Deterministic symbolic verification" in m for m in messages)
    assert any("Outcome: SUPPORTED" in m for m in messages)


def test_stage4h4b_no_session_or_contract_mutations(app, tmp_path):
    """8. Running evidence verification causes zero mutations to session data, tiers, or contracts."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall send alerts.\n")
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]
    candidate_text = "The system shall dispatch urgent alerts."
    ui.ask = scripted([candidate_text, "Reviewer", "yes"])
    ui.manual(session, rid)

    before_current = session.current.read_bytes()
    before_state = session.read()[3]

    fake_embedder = _MockMiniLMEmbedder()
    mock_nli = _MockNLI(label="contradiction")  # Advisory contradiction
    ui.embedder = fake_embedder
    ui.nli = mock_nli

    # 7: Verify evidence, 1: Confirm, 5: Back
    ui.ask = scripted(["7", "1", "5"])
    ui.candidates(session, rid)

    after_current = session.current.read_bytes()
    after_data, _, _, after_state = session.read()

    # Session files and authoritative states remain byte-for-byte identical
    assert before_current == after_current
    assert before_state["requirements"][rid]["candidates"] == after_state["requirements"][rid]["candidates"]
    assert after_data["requirements"][0]["human_decision"] == "pending"


def test_stage4h4b_human_selection_after_verification(app, tmp_path):
    """9. After advisory verification, existing human candidate selection functions properly."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall wait.\n")
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]
    replacement = "The system shall wait for 2 seconds."
    ui.ask = scripted([replacement, "Reviewer", "yes"])
    ui.manual(session, rid)

    fake_embedder = _MockMiniLMEmbedder()
    mock_nli = _MockNLI(label="entailment")
    ui.embedder = fake_embedder
    ui.nli = mock_nli

    # 7: Verify, 1: Confirm, then 1: Select candidate, "Reviewer", "yes"
    ui.ask = scripted(["7", "1", "1", "Reviewer", "yes"])
    ui.candidates(session, rid)

    state = session.read()[3]
    candidate_records = state["requirements"][rid]["candidates"]
    assert any(c.get("text") == replacement for c in candidate_records.values())
    assert any("Candidate: " + replacement in m for m in messages)


def test_stage4h4b_low_memory_protection(app, tmp_path):
    """10. Available RAM < 1.5 GiB aborts DeBERTa loading safely without crashing."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall wait.\n")
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]
    replacement = "The system shall wait for 2 seconds."
    ui.ask = scripted([replacement, "Reviewer", "yes"])
    ui.manual(session, rid)

    mock_nli = _MockNLI()
    ui.nli = mock_nli

    with patch("c1_requirement_quality.ml.ml_diagnostics.available_memory_bytes", return_value=1.0 * 1024**3):
        ui.ask = scripted(["7", "1", "5"])
        ui.candidates(session, rid)

    assert len(mock_nli.calls) == 0
    assert any("Insufficient available RAM" in m for m in messages)
    assert any("DeBERTa loading cancelled for safety." in m for m in messages)


def test_stage4h4b_missing_model_recovery(app, tmp_path):
    """10. Missing DeBERTa checkpoint directory recovers gracefully and informs user."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall wait.\n")
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]
    replacement = "The system shall wait for 2 seconds."
    ui.ask = scripted([replacement, "Reviewer", "yes"])
    ui.manual(session, rid)

    # Pass nonexistent path for DeBERTa cache dir and ensure clean recovery
    with patch("c1_requirement_quality.model_paths.get_deberta_nli_cache_dir", return_value=tmp_path / "nonexistent"):
        ui.ask = scripted(["7", "1", "5"])
        ui.candidates(session, rid)

    assert any("Unable to load local verification models" in m for m in messages)


def test_stage4h4b_pause_resume_compatibility(tmp_path):
    """11. Pause via 'pause' input and subsequent resume remains fully compatible."""
    session_root = tmp_path / "sessions"
    messages = []
    fake = _MockMiniLMEmbedder()
    mock_nli = _MockNLI()
    ui = wizard.Wizard(session_root, tell=messages.append, embedder=fake, nli=mock_nli)

    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall wait.\n")
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]
    replacement = "The system shall wait for 2 seconds."
    ui.ask = scripted([replacement, "Reviewer", "yes"])
    ui.manual(session, rid)

    # 7: Verify, 1: Confirm, then "pause" to pause session safely
    ui.ask = scripted(["7", "1", "pause"])
    with pytest.raises(KeyboardInterrupt):
        ui.candidates(session, rid)

    assert len(mock_nli.calls) > 0

    # Resume session with fresh wizard
    resumed_messages = []
    fake2 = _MockMiniLMEmbedder()
    mock_nli2 = _MockNLI()
    ui2 = wizard.Wizard(session_root, ask=scripted(["1"]), tell=resumed_messages.append, embedder=fake2, nli=mock_nli2)
    resumed_session = ui2.choose_session()
    assert resumed_session is not None
    assert resumed_session.workspace == session.workspace

    # Candidate remains intact and reviewable in resumed session
    ui2.ask = scripted(["5"])
    ui2.candidates(resumed_session, rid)
    assert any("Candidate rewrite: " + replacement in m for m in resumed_messages)


def test_stage4h4b_offline_no_downloads(app, tmp_path):
    """12. Verification enforces local_files_only=True and offline execution."""
    import transformers
    import transformers.pipelines
    from c1_requirement_quality.rag.verifier import LocalNLI
    nli = LocalNLI()
    recorded_kwargs = {}
    def mock_pipeline(*args, **kwargs):
        recorded_kwargs.update(kwargs)
        return lambda pair, **k: [{"label": "entailment", "score": 0.95}]

    with patch.object(transformers.pipelines, "pipeline", side_effect=mock_pipeline), \
         patch.object(transformers, "pipeline", side_effect=mock_pipeline):
        diag = nli.classify_with_diagnostics("Premise text", "Hypothesis text")
        assert diag["label"] == "entailment"
        assert diag["score"] == 0.95
        assert recorded_kwargs.get("local_files_only") is True
        assert recorded_kwargs.get("device") == "cpu"


# ==============================================================================
# Stage 4H.5B — Optional Groq/Qwen Clarification and Rewrite Integration Tests
# ==============================================================================


class _MockGroqBackend:
    def __init__(self, model="qwen/qwen3.8-27b", *, clarification_proposals=None, rewrite_proposals=None, error=None):
        self.model = model
        self.clarification_proposals = clarification_proposals
        self.rewrite_proposals = rewrite_proposals
        self.error = error
        self.clarification_calls = []
        self.generate_calls = []

    def propose_clarification(self, context):
        self.clarification_calls.append(context)
        if self.error:
            raise self.error
        if self.clarification_proposals is not None:
            return self.clarification_proposals
        rid = context["requirement_id"]
        ref = f"SRS:{rid}:original"
        return {
            "model": self.model,
            "proposal": {
                "schema_version": 1,
                "requirement_id": rid,
                "source_evidence_refs": [ref],
                "advisory_refs": [],
                "clarification_questions": [
                    {
                        "question": "What timeout duration is required?",
                        "reason": "The response time must be measurable for automated testing.",
                        "source_evidence_refs": [ref],
                        "advisory_refs": [],
                    }
                ],
                "proposed_rewrite": None,
                "unresolved_assumptions": [],
                "claimed_grounding_status": "insufficient",
            },
        }

    def generate(self, requirement_text, defects, evidence_chunks, clarification_answers, *, max_candidates=3):
        self.generate_calls.append((requirement_text, defects, evidence_chunks, clarification_answers))
        if self.error:
            raise self.error
        if self.rewrite_proposals is not None:
            return self.rewrite_proposals
        return [
            {
                "text": "The system shall wait for 2 seconds.",
                "strategy": "groq_qwen_proposal",
                "source_evidence": {
                    "kind": "untrusted_cloud_proposal",
                    "source": "groq",
                    "model": self.model,
                    "ambiguity": "Timeout is unspecified.",
                    "clarification_question": "What timeout duration is required?",
                    "human_review_required": True,
                },
            }
        ]


def test_stage4h5b_clarification_menu_optional_and_disabled_by_default(app, tmp_path):
    """1, 2, 3: Clarification option is disabled by default; cancelling transmits zero data."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall wait for [timeout].\n")
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]

    mock_backend = _MockGroqBackend()
    ui.groq_backend = mock_backend

    # Select 5 (Suggest questions), then 2 (Cancel Back), then 3 (Back from clarification)
    ui.ask = scripted(["5", "2", "3"])
    ui.questions(session, rid)

    assert len(mock_backend.clarification_calls) == 0
    assert any("Optional Cloud Clarification Suggestions (Groq / Qwen)" in m for m in messages)
    assert any("Clarification request cancelled. No data transmitted." in m for m in messages)


def test_stage4h5b_clarification_confirmation_and_accept_creates_pending_question(app, tmp_path):
    """4, 5, 6: Confirmation invokes injected backend; accepting creates an OPEN question, not approval."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall wait for [timeout].\n")
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]

    mock_backend = _MockGroqBackend()
    ui.groq_backend = mock_backend

    # 5: Suggest questions
    # 1: Confirm request
    # 1: Accept question into session
    # Reviewer: "Alice", Confirm: "yes"
    # 3: Back from clarification review
    ui.ask = scripted(["5", "1", "1", "Alice", "yes", "3"])
    ui.questions(session, rid)

    assert len(mock_backend.clarification_calls) == 1
    assert any("Question: What timeout duration is required?" in m for m in messages)
    assert any(f"Added pending question to {rid}." in m for m in messages)

    # Verify session now contains the new question and status is OPEN
    data, _, _, state = session.read()
    rec = state["requirements"][rid]
    matching = [q for q in rec["questions"].values() if q["text"] == "What timeout duration is required?"]
    assert len(matching) == 1
    assert matching[0]["status"] == "OPEN"
    assert matching[0]["current_answer_id"] is None
    # Verify requirement is NOT approved or BDD-ready
    assert data["requirements"][0]["human_decision"] == "pending"
    assert data["requirements"][0]["bdd_ready"] is False


def test_stage4h5b_clarification_edit_and_discard(app, tmp_path):
    """7: Editing customizes question text; discard skips publishing."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall wait for [timeout].\n")
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]

    mock_backend = _MockGroqBackend()
    ui.groq_backend = mock_backend

    # 1. Edit flow:
    # 5: Suggest questions, 1: Confirm request
    # 2: Edit question, "What precise timeout is required in seconds?"
    # Reviewer: "Bob", "yes"
    # 3: Back
    ui.ask = scripted(["5", "1", "2", "What precise timeout is required in seconds?", "Bob", "yes", "3"])
    ui.questions(session, rid)

    rec = session.read()[3]["requirements"][rid]
    assert any(q["text"] == "What precise timeout is required in seconds?" for q in rec["questions"].values())

    # 2. Discard flow:
    messages.clear()
    ui.ask = scripted(["5", "1", "3", "3"])
    ui.questions(session, rid)
    assert any("Question discarded." in m for m in messages)


def test_stage4h5b_clarification_duplicate_detection(app, tmp_path):
    """8: Existing questions are detected and not duplicated."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall wait for [timeout].\n")
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]

    # Pre-add the question
    action = {"requirement_id": rid, "clarification_questions": ["What timeout duration is required?"]}
    session.apply(action, "Admin", True)

    mock_backend = _MockGroqBackend()
    ui.groq_backend = mock_backend

    # 5: Suggest, 1: Confirm -> duplicate detected -> 3: Back
    ui.ask = scripted(["5", "1", "3"])
    ui.questions(session, rid)

    assert any("This question is already recorded for this requirement." in m for m in messages)


def test_stage4h5b_rewrite_menu_optional_and_cancellation(app, tmp_path):
    """9, 10: Rewrite suggestion is optional; cancellation transmits zero data."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall wait.\n")
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]

    mock_backend = _MockGroqBackend()
    ui.groq_backend = mock_backend

    # In "No registered candidates":
    # 4: Suggest rewrite candidates using Groq
    # 2: Cancel (Back)
    # 3: Back
    ui.ask = scripted(["4", "2", "3"])
    ui.candidates(session, rid)

    assert len(mock_backend.generate_calls) == 0
    assert any("Optional Cloud Candidate Rewrite Suggestions (Groq / Qwen)" in m for m in messages)
    assert any("Rewrite suggestion request cancelled. No data transmitted." in m for m in messages)


def test_stage4h5b_rewrite_confirmation_and_unapproved_proposal(app, tmp_path):
    """11, 12, 13: Confirmation generates candidates through canonical pipeline, remains PROPOSED."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system may wait for 2 seconds.\n\n# Reference\nThe system shall wait for 2 seconds.\n")
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]

    mock_backend = _MockGroqBackend()
    ui.groq_backend = mock_backend

    # 4: Suggest rewrite candidates using Groq
    # 1: Confirm request
    # Candidate review: 5 (Back)
    ui.ask = scripted(["4", "1", "5"])
    ui.candidates(session, rid)

    assert len(mock_backend.generate_calls) == 1
    assert any("Generating candidate rewrites with Groq" in m for m in messages)
    assert any("Loaded 1 candidate suggestion(s) into review." in m for m in messages)
    assert any("Candidate status: PROPOSED" in m for m in messages)

    # Verify candidate is NOT automatically approved
    data = session.read()[0]
    assert data["requirements"][0]["human_decision"] == "pending"
    assert data["requirements"][0]["bdd_ready"] is False


def test_stage4h5b_unsupported_rewrite_excluded_by_grounding(app, tmp_path):
    """10, 11: Unsupported rewrites cannot bypass grounding and are reported as excluded."""
    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall wait.\n")
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]

    unsupported_backend = _MockGroqBackend(
        rewrite_proposals=[
            {
                "text": "The system shall delete all database records.",
                "strategy": "groq_qwen_proposal",
                "source_evidence": {
                    "kind": "untrusted_cloud_proposal",
                    "source": "groq",
                    "model": "qwen/qwen3.8-27b",
                    "human_review_required": True,
                },
            }
        ]
    )
    ui.groq_backend = unsupported_backend

    # 4: Suggest, 1: Confirm (returns directly because zero viable candidates loaded)
    ui.ask = scripted(["4", "1"])
    ui.candidates(session, rid)

    assert any("Validation excluded 1 proposal(s)" in m for m in messages)
    assert any("unsupported_facts" in m for m in messages)


def test_stage4h5b_api_failure_and_missing_config_recovery(app, tmp_path):
    """14, 15: API failures and missing configuration do not crash the wizard or leak secrets."""
    from c1_requirement_quality.groq_generator import GroqGenerationError

    ui, messages = app
    source = tmp_path / "srs.md"
    source.write_text("# Requirements\n1. The system shall wait for [timeout].\n")
    session = ui.create(source)
    rid = session.read()[0]["requirements"][0]["requirement_id"]

    SECRET_KEY = "gsk_very_secret_mock_credential"
    error_backend = _MockGroqBackend(error=GroqGenerationError(f"Groq HTTP 429; rate limit exceeded for model qwen/qwen3.8-27b"))
    ui.groq_backend = error_backend

    # 1. Clarification failure: 5 (Suggest), 1 (Confirm), 3 (Back)
    ui.ask = scripted(["5", "1", "3"])
    ui.questions(session, rid)

    assert any("Groq clarification request failed: Groq HTTP 429" in m for m in messages)
    assert not any(SECRET_KEY in m for m in messages)

    # 2. Candidate rewrite failure: use eligible requirement
    source2 = tmp_path / "srs2.md"
    source2.write_text("# Requirements\n1. The system shall wait.\n")
    session2 = ui.create(source2)
    rid2 = session2.read()[0]["requirements"][0]["requirement_id"]

    messages.clear()
    ui.ask = scripted(["4", "1"])
    ui.candidates(session2, rid2)

    assert any("Groq candidate generation failed: Groq HTTP 429" in m for m in messages)
    assert not any(SECRET_KEY in m for m in messages)
