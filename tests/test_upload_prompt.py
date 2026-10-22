"""Exercise real headless Qt dialogs with temporary data and fake submissions."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from threading import Event, get_ident
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from qtpy.QtCore import QCoreApplication, QEvent, Qt, QThread
from qtpy.QtTest import QTest
from qtpy.QtWidgets import QApplication, QMessageBox, QWidget
from test_acquisition_completion import CompletionCase, _finalized_case

from exaspim_control import upload_prompt as prompt
from exaspim_control.upload_submission import SubmissionResult, SubmissionSettings


@pytest.fixture(scope="module")
def app() -> QApplication:
    """Keep one headless application alive for the module."""
    return QApplication.instance() or QApplication([])


def _until(app: QApplication, condition: Callable[[], bool]) -> None:
    """Pump Qt while an actual background thread returns its queued result."""
    for _ in range(1000):
        app.processEvents()
        if condition():
            return
        QTest.qWait(2)
    pytest.fail("Timed out waiting for the popup worker")


@pytest.fixture
def ui(tmp_path: Path, app: QApplication) -> Iterator[tuple]:
    """A plain QWidget is sufficient: no napari, device SDK or acquisition is opened."""
    case = _finalized_case(tmp_path)
    window = QWidget()
    settings = SubmissionSettings(enabled=True, path_map=case.path_map)
    controller = prompt.UploadPromptController(window, settings)
    window.show()
    yield case, window, controller
    window.close()
    app.processEvents()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _question(app: QApplication, case: CompletionCase, controller: prompt.UploadPromptController
              ) -> QMessageBox:
    controller.offer(case.run.snapshot())
    _until(app, lambda: bool(controller._dialogs))
    return controller._dialogs[0]


def test_question_is_nonmodal_safe_default_on_gui_thread(ui: tuple, app: QApplication) -> None:
    case, window, controller = ui
    box = _question(app, case, controller)
    assert box.parent() is window
    assert box.thread() is QThread.currentThread()
    assert box.windowModality() == Qt.NonModal
    assert box.textFormat() == Qt.PlainText
    assert box.defaultButton().text() == "Not now"
    assert box.escapeButton().text() == "Not now"
    assert str(case.root) in box.informativeText()
    assert "Single Neuron Reconstructions" in box.informativeText()
    assert "transformation and S3 upload" in box.text()


@pytest.mark.parametrize("answer", ["button", "escape", "close", "parent-close"])
def test_decline_never_spawns_or_writes_receipt(
    ui: tuple, app: QApplication, monkeypatch: pytest.MonkeyPatch, answer: str,
) -> None:
    case, window, controller = ui
    submit = Mock()
    monkeypatch.setattr(prompt, "submit_upload", submit)
    box = _question(app, case, controller)
    if answer == "button":
        box.defaultButton().click()
    elif answer == "escape":
        QTest.keyClick(box, Qt.Key_Escape)
    elif answer == "close":
        box.close()
    else:
        window.close()
    app.processEvents()
    assert not controller._dialogs
    submit.assert_not_called()
    assert not (case.root / "derivatives" / "upload_submission.json").exists()


def test_accept_revalidates_and_submits_captured_identity_off_thread(
    ui: tuple, app: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, _, controller = ui
    called = Event()
    captured = []
    main_thread = get_ident()

    def submit(request: object, settings: SubmissionSettings) -> SubmissionResult:
        captured.append((request, settings, get_ident()))
        called.set()
        return SubmissionResult("accepted", "Accepted, not uploaded")

    monkeypatch.setattr(prompt, "submit_upload", submit)
    box = _question(app, case, controller)
    original_subject = case.run.subject_id
    case.run.subject_id = "edited-after-question"
    next(button for button in box.buttons() if button.text() == "Start upload").click()
    _until(app, called.is_set)
    assert captured[0][0].subject_id == original_subject
    assert captured[0][0].dataset_root == case.root
    assert captured[0][1] is controller.settings
    assert captured[0][2] != main_thread
    assert not controller._dialogs  # No second success dialog.


def test_changed_data_after_question_is_not_submitted(
    ui: tuple, app: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, _, controller = ui
    submit = Mock()
    monkeypatch.setattr(prompt, "submit_upload", submit)
    box = _question(app, case, controller)
    next((case.root / "exaSPIM").glob("*.ims")).write_bytes(b"changed")
    next(button for button in box.buttons() if button.text() == "Start upload").click()
    _until(app, lambda: bool(controller._dialogs))
    assert controller._dialogs[0].icon() == QMessageBox.Warning
    submit.assert_not_called()


def test_verification_runs_in_worker_and_failure_has_no_success_popup(
    ui: tuple, app: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, _, controller = ui
    observed = []
    received = []
    controller._results.completed.connect(lambda *args: received.append(args))

    def invalid(*_args: object) -> None:
        observed.append(get_ident())
        raise ValueError("Unverified")

    monkeypatch.setattr(prompt, "verify_completion", invalid)
    controller.offer(case.run.snapshot())
    _until(app, lambda: bool(received))
    assert observed[0] != get_ident()
    assert not controller._dialogs


def test_duplicate_events_and_datasets_show_one_question(ui: tuple, app: QApplication) -> None:
    case, _, controller = ui
    evidence = case.run.snapshot()
    box = _question(app, case, controller)
    controller.offer(evidence)
    controller._completed(replace(evidence, run_id="other-run"), "verification", case.verify())
    assert controller._dialogs == [box]
    box.close()
    controller.offer(evidence)
    app.processEvents()
    assert not controller._dialogs


def test_existing_receipt_suppresses_question(ui: tuple) -> None:
    case, _, controller = ui
    (case.root / "derivatives" / "upload_submission.json").write_text("{}")
    value = prompt._candidate(case.run.snapshot(), controller.settings)
    assert value is None
    controller._completed(case.run.snapshot(), "verification", value)
    assert not controller._dialogs


def test_disabled_and_closed_controllers_never_start_workers(
    ui: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, window, controller = ui
    start = Mock()
    monkeypatch.setattr(controller, "_start", start)
    controller.settings = replace(controller.settings, enabled=False)
    controller.offer(case.run.snapshot())
    start.assert_not_called()
    window.close()
    controller.offer(replace(case.run.snapshot(), run_id="later"))
    controller._completed(case.run.snapshot(), "verification", case.verify())
    start.assert_not_called()
    assert not controller._dialogs


def test_environment_settings_default_disabled(app: QApplication, monkeypatch: pytest.MonkeyPatch
                                               ) -> None:
    monkeypatch.delenv("EXASPIM_UPLOAD_ENABLED", raising=False)
    window = QWidget()
    controller = prompt.UploadPromptController(window)
    assert not controller.settings.enabled
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert controller._closed.is_set()


@pytest.mark.parametrize(
    "status", ["accepted", "disabled", "unknown", "failed-to-start", "duplicate"],
)
def test_submission_outcomes_use_logs_or_small_warning(ui: tuple, status: str) -> None:
    case, _, controller = ui
    controller._completed(case.run.snapshot(), "submission", SubmissionResult(status, "detail"))
    assert bool(controller._dialogs) == (status not in {"accepted", "disabled"})
    if controller._dialogs:
        box = controller._dialogs[0]
        assert box.icon() == QMessageBox.Warning
        box.accept()
        controller._release(box, 0)  # Repeated cleanup is harmless before deferred deletion.


def test_worker_start_error_is_contained(ui: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    case, _, controller = ui
    monkeypatch.setattr(prompt, "Thread", Mock(side_effect=RuntimeError("no thread")))
    controller._start(lambda: None, case.run.snapshot(), "submission")
    assert controller._dialogs[0].icon() == QMessageBox.Warning


def test_close_before_or_during_work_discards_results(ui: tuple) -> None:
    case, _, _ = ui
    closed = Event()
    closed.set()
    results = Mock()
    operation = Mock()
    prompt._work(operation, case.run.snapshot(), "verification", results, closed)
    operation.assert_not_called()
    closed.clear()
    prompt._work(closed.set, case.run.snapshot(), "verification", results, closed)
    results.completed.emit.assert_not_called()


def test_close_during_post_consent_verification_does_not_start_process(
    ui: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, _, controller = ui
    closed = Event()
    closed.set()
    submit = Mock()
    monkeypatch.setattr(prompt, "submit_upload", submit)
    result = prompt._submit(case.run.snapshot(), controller.settings, closed)
    assert result.status == "disabled"
    submit.assert_not_called()