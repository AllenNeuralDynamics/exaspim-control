"""Optional, nonmodal qtpy question; filesystem and submission work stays off Qt."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial
from threading import Event, Thread

from qtpy.QtCore import QEvent, QObject, Qt, Signal, Slot
from qtpy.QtWidgets import QMessageBox, QWidget

from exaspim_control.acquisition_completion import (
    AcquisitionEvidence,
    verify_completion,
)
from exaspim_control.upload_submission import (
    SubmissionResult,
    SubmissionSettings,
    UploadRequest,
    receipt_path,
    submit_upload,
)

logger = logging.getLogger(__name__)


class _Results(QObject):
    """Parentless bridge retained by each worker until it exits."""

    completed = Signal(object, str, object)


def _work(
    operation: Callable[[], object], evidence: AcquisitionEvidence,
    stage: str, results: _Results, closed: Event,
) -> None:
    """Run only non-Qt work; closing a parent discards late notifications."""
    if closed.is_set():
        return
    try:
        value = operation()
    except Exception as exc:  # noqa: BLE001 - Optional workers fail closed, never through Qt slots.
        logger.warning("Upload %s failed: %s", stage, exc)
        value = SubmissionResult("failed-to-start", str(exc))
    if not closed.is_set():
        results.completed.emit(evidence, stage, value)


def _candidate(evidence: AcquisitionEvidence, settings: SubmissionSettings) -> UploadRequest | None:
    request = verify_completion(evidence, settings.path_map)
    if receipt_path(request).exists():
        logger.info("Submission receipt already exists for %s", request.dataset_root)
        return None
    return request


def _submit(
    evidence: AcquisitionEvidence, settings: SubmissionSettings, closed: Event,
) -> SubmissionResult:
    # Re-read all evidence after consent; an old question must not submit changed data.
    request = verify_completion(evidence, settings.path_map)
    if closed.is_set():
        return SubmissionResult("disabled", "Window closed before submission started.")
    return submit_upload(request, settings)


class UploadPromptController(QObject):
    """Own optional questions for one existing acquisition window.

    Parameters
    ----------
    parent : QWidget
        Existing acquisition window; no layout or persistent controls are added.
    settings : SubmissionSettings or None
        Explicit injection for tests/deployment, otherwise environment configuration.

    Notes
    -----
    Call ``offer`` only after successful metadata finalization, on the GUI thread.
    Submission is disabled by default until the external script is repaired and
    EXASPIM_UPLOAD_ENABLED=1 is configured.
    """

    def __init__(self, parent: QWidget, settings: SubmissionSettings | None = None) -> None:
        super().__init__(parent)
        self.settings = settings if settings is not None else SubmissionSettings.from_environment()
        self._window = parent
        self._closed = Event()
        self._seen: set[str] = set()
        self._datasets: set[str] = set()
        self._dialogs: list[QMessageBox] = []
        self._results = _Results()
        self._results.completed.connect(self._completed, Qt.QueuedConnection)
        parent.installEventFilter(self)
        parent.destroyed.connect(self._closed.set)

    def offer(self, evidence: AcquisitionEvidence) -> None:
        """Verify one finalized run asynchronously; never infer success from a UI event."""
        if self._closed.is_set() or evidence.run_id in self._seen:
            return
        self._seen.add(evidence.run_id)
        if not self.settings.enabled:
            logger.info("Upload prompt disabled; configure it after repairing the external CLI.")
            return
        self._start(partial(_candidate, evidence, self.settings), evidence, "verification")

    def _start(
        self, operation: Callable[[], object], evidence: AcquisitionEvidence, stage: str,
    ) -> None:
        try:
            Thread(
                target=_work,
                args=(operation, evidence, stage, self._results, self._closed),
                name=f"upload-{stage}", daemon=True,
            ).start()
        except RuntimeError as exc:
            self._completed(evidence, stage, SubmissionResult("failed-to-start", str(exc)))

    @Slot(object, str, object)
    def _completed(self, evidence: AcquisitionEvidence, stage: str, value: object) -> None:
        if self._closed.is_set():
            return
        if isinstance(value, UploadRequest):
            self._question(evidence, value)
        elif isinstance(value, SubmissionResult):
            logger.info("Upload %s: %s", value.status, value.message)
            # Unverified acquisitions simply do not qualify for the success question.
            if stage == "submission" and value.status not in {"accepted", "disabled"}:
                self._warning(value.message)

    def _retain(self, dialog: QMessageBox) -> None:
        self._dialogs.append(dialog)
        dialog.setWindowModality(Qt.NonModal)
        dialog.setTextFormat(Qt.PlainText)
        dialog.finished.connect(partial(self._release, dialog))
        dialog.show()

    def _release(self, dialog: QMessageBox, _result: int) -> None:
        if dialog in self._dialogs:
            self._dialogs.remove(dialog)
        dialog.deleteLater()

    def _question(self, evidence: AcquisitionEvidence, request: UploadRequest) -> None:
        key = str(request.dataset_root)
        if key in self._datasets:
            return
        self._datasets.add(key)
        dialog = QMessageBox(self._window)
        dialog.setWindowTitle("Acquisition complete")
        dialog.setIcon(QMessageBox.Question)
        dialog.setText(
            "Imaging and VAST staging completed successfully.\n\n"
            "Submit this dataset for transformation and S3 upload?"
        )
        dialog.setInformativeText(
            f"Dataset: {request.dataset_root.name}\nSubject: {request.subject_id}\n"
            f"Project: {self.settings.project_name}\nVAST: {request.dataset_root}\n\n"
            "The configured downstream workflow, including screening processing, applies."
        )
        start = dialog.addButton("Start upload", QMessageBox.AcceptRole)
        decline = dialog.addButton("Not now", QMessageBox.RejectRole)
        dialog.setDefaultButton(decline)
        dialog.setEscapeButton(decline)

        def answered(_result: int) -> None:
            if not self._closed.is_set() and dialog.clickedButton() is start:
                operation = partial(_submit, evidence, self.settings, self._closed)
                self._start(operation, evidence, "submission")

        dialog.finished.connect(answered)
        self._retain(dialog)

    def _warning(self, message: str) -> None:
        dialog = QMessageBox(self._window)
        dialog.setWindowTitle("Upload submission needs attention")
        dialog.setIcon(QMessageBox.Warning)
        dialog.setText(message)
        dialog.setInformativeText(
            "Data remains on VAST. Check the log and transfer service before retrying."
        )
        dialog.setStandardButtons(QMessageBox.Ok)
        self._retain(dialog)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Dismiss pending questions when the existing acquisition window closes."""
        if watched is self._window and event.type() == QEvent.Close:
            self._closed.set()
            for dialog in tuple(self._dialogs):
                dialog.reject()
        return super().eventFilter(watched, event)