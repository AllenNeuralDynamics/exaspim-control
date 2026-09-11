# Filesystem/process boundaries return conservative states for all ordinary exceptions.
# ruff: noqa: BLE001
"""Submit a consented, verified dataset from a background worker, without Qt or hardware.

Submission is disabled by default. Enable it only after the user-owned external script calls
its real CLI instead of the hardcoded fixture, uses bounded HTTP timeouts, checks HTTP errors,
and exits zero only after service acceptance. This module neither inspects nor repairs that
script. ``accepted`` means submission acceptance under those prerequisites, not upload completion.

The caller must verify acquisition evidence and finalized metadata immediately before calling.
These checks only enforce the local Linux launch contract and basic existing dataset layout;
the configured VAST root must be the same mount visible to the downstream service. Calling
``submit_upload`` constitutes consent. All receipts, including failed or incomplete ones, block
retries pending manual reconciliation. No service polling or automatic retry is performed.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

_DEFAULT_INTERPRETER = Path(
    "/allen/programs/mindscope/workgroups/omfish/carsonb/rocky_miniconda/envs/"
    "exaspim_transformation/bin/python"
)
_DEFAULT_REPOSITORY = Path(
    "/home/carson.berry/allen/aind/scratch/carson.berry/aind-exaspim-data-transformation"
)
_DEFAULT_SCRIPT = _DEFAULT_REPOSITORY / "docs/examples/test_airflow.py"
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}")
_TERMINATION_GRACE_SECONDS = 5.0


@dataclass(frozen=True)
class UploadRequest:
    """Capture the immutable identity and canonical location authorized by the user.

    Parameters
    ----------
    run_id : str
        Nonblank identity captured for this acquisition.
    dataset_root : Path
        Existing canonical, absolute dataset directory beneath the configured VAST root.
    subject_id : str
        Nonblank subject captured for this acquisition, not a mutable GUI value.
    """

    run_id: str
    dataset_root: Path
    subject_id: str

    @property
    def source(self) -> Path:
        """Return the finalized directory containing all acquired IMS tiles."""
        return self.dataset_root / "exaSPIM"


@dataclass(frozen=True)
class SubmissionSettings:
    """Configure a local launch explicitly or through ``from_environment``.

    Parameters
    ----------
    enabled : bool
        Opt in only after repairing the external CLI and its HTTP error handling.
    vast_root : Path or None
        Required canonical, absolute staging root shared with the service.
    interpreter : Path
        External environment's executable; never falls back to this process's interpreter.
    script : Path
        User-owned submission CLI; it is not imported or inspected here.
    working_directory : Path
        Existing external repository, independent of any script override.
    project_name : str
        Project passed unchanged to the CLI.
    timeout_seconds : float
        Positive, finite timeout for submission, not the downstream Airflow job.
    """

    enabled: bool = False
    vast_root: Path | None = None
    interpreter: Path = _DEFAULT_INTERPRETER
    script: Path = _DEFAULT_SCRIPT
    working_directory: Path = _DEFAULT_REPOSITORY
    project_name: str = "Single Neuron Reconstructions"
    timeout_seconds: float = 120.0

    @classmethod
    def from_environment(cls) -> SubmissionSettings:
        """Read opt-in and local paths without inspecting or executing the external script.

        Returns
        -------
        SubmissionSettings
            Only ``EXASPIM_UPLOAD_ENABLED=1`` enables submission. Path overrides are
            ``EXASPIM_UPLOAD_VAST_ROOT``, ``EXASPIM_UPLOAD_PYTHON``,
            ``EXASPIM_UPLOAD_SCRIPT``, and ``EXASPIM_UPLOAD_CWD``. Missing or blank VAST
            roots remain unconfigured. CWD defaults to the fixed external repository,
            even when the script is overridden. Other settings allow explicit injection.
        """
        root = os.environ.get("EXASPIM_UPLOAD_VAST_ROOT", "")
        return cls(
            enabled=os.environ.get("EXASPIM_UPLOAD_ENABLED") == "1",
            vast_root=Path(root) if root.strip() else None,
            interpreter=Path(os.environ.get("EXASPIM_UPLOAD_PYTHON", str(_DEFAULT_INTERPRETER))),
            script=Path(os.environ.get("EXASPIM_UPLOAD_SCRIPT", str(_DEFAULT_SCRIPT))),
            working_directory=Path(os.environ.get("EXASPIM_UPLOAD_CWD", str(_DEFAULT_REPOSITORY))),
        )


@dataclass(frozen=True)
class SubmissionResult:
    """Report a local outcome without claiming downstream upload completion.

    Parameters
    ----------
    status : str
        ``disabled``, ``duplicate``, ``failed-to-start``, ``accepted``, or ``unknown``.
    message : str
        Diagnostic suitable for display; includes the log location when available.
    """

    status: str
    message: str


def receipt_path(request: UploadRequest) -> Path:
    """Return the per-dataset duplicate guard without creating any directories.

    Parameters
    ----------
    request : UploadRequest
        Immutable, consented dataset identity.

    Returns
    -------
    Path
        Receipt within the dataset's existing derivatives directory.
    """
    return request.dataset_root / "derivatives" / "upload_submission.json"


def _canonical_directory(path: Path) -> None:
    """Require an existing absolute directory with no symlink or traversal aliases."""
    if not path.is_absolute() or path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError("Dataset directories must be existing, absolute, and canonical.")


def _raise_walk_error(error: OSError) -> None:
    """Fail closed instead of silently omitting unreadable tile directories."""
    raise error


def _validate_source(source: Path) -> None:
    """Require at least one nonempty regular IMS file and reject all source symlinks."""
    _canonical_directory(source)
    found = False
    for directory, subdirectories, files in os.walk(source, onerror=_raise_walk_error):
        for name in subdirectories + files:
            path = Path(directory) / name
            if path.resolve(strict=True) != path:
                raise ValueError("Source entries must be canonical; symlinks are not allowed.")
            if path.suffix == ".ims":
                if not path.is_file() or path.stat().st_size == 0:
                    raise ValueError("Every IMS entry must be a nonempty regular file.")
                found = True
    if not found:
        raise ValueError("Source must contain at least one nonempty .ims file.")


def _validate_identity(request: UploadRequest, settings: SubmissionSettings) -> None:
    """Check captured identity and the timestamp required by the external CLI."""
    for value in (request.run_id, request.subject_id, settings.project_name):
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise ValueError(
                "Run ID, subject ID, and project must be nonblank strings without NUL."
            )
    timestamp = _TIMESTAMP.search(request.dataset_root.name)
    if timestamp is None:
        raise ValueError("The dataset name must contain YYYY-MM-DD_HH-MM-SS for the external CLI.")
    # Validate filename fields, not an instant; do not infer a timezone.
    datetime.strptime(timestamp.group(), "%Y-%m-%d_%H-%M-%S")  # noqa: DTZ007


def _validate_launch(settings: SubmissionSettings) -> None:
    """Require usable explicit local executables, working directory, and timeout."""
    if not math.isfinite(settings.timeout_seconds) or settings.timeout_seconds <= 0:
        raise ValueError("Submission timeout must be positive and finite.")
    for path, permission in ((settings.interpreter, os.X_OK), (settings.script, os.R_OK)):
        if not path.is_absolute() or not path.is_file() or not os.access(path, permission):
            raise ValueError(
                "Interpreter must be executable and script readable, at absolute paths."
            )
    if not settings.working_directory.is_absolute() or not settings.working_directory.is_dir():
        raise ValueError("The external working directory must exist at an absolute path.")


def _preflight(request: UploadRequest, settings: SubmissionSettings) -> None:
    """Validate the local contract without writing files or invoking the CLI."""
    if sys.platform != "linux":
        raise ValueError("Submission requires the configured interpreter on this Linux host.")
    if settings.vast_root is None:
        raise ValueError("A shared VAST root must be explicitly configured.")
    _canonical_directory(settings.vast_root)
    _canonical_directory(request.dataset_root)
    if settings.vast_root not in request.dataset_root.parents:
        raise ValueError("The dataset must be strictly beneath the configured VAST root.")
    _canonical_directory(receipt_path(request).parent)
    if os.path.lexists(receipt_path(request)):
        raise FileExistsError("An existing receipt blocks submission in every state.")
    _validate_identity(request, settings)
    _validate_source(request.source)
    _validate_launch(settings)


def _open_log(path: Path) -> BinaryIO:
    """Open an append-only regular log, refusing symlinks and blocking special files."""
    # NONBLOCK prevents hanging on a pre-existing FIFO before fstat can reject it.
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Submission log must be a regular file.")
        return os.fdopen(descriptor, "ab")
    except Exception:
        os.close(descriptor)
        raise


def _atomic_update(path: Path, payload: dict[str, object]) -> None:
    """Replace a receipt atomically, cleaning up only this operation's temporary file."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def _result(status: str, message: str, log: Path) -> SubmissionResult:
    """Attach the diagnostic log path without recording environment or credentials."""
    return SubmissionResult(status, f"{message} Log: {log}")


def _finish(
    path: Path,
    payload: dict[str, object],
    result: SubmissionResult,
    exit_code: int | None,
) -> SubmissionResult:
    """Record an outcome atomically, retaining the initial guard on write failure."""
    try:
        _atomic_update(path, {**payload, "state": result.status, "exit_code": exit_code})
    except Exception as error:
        return SubmissionResult(
            "unknown",
            f"{result.message} Final receipt update failed ({type(error).__name__}); "
            "submission may have occurred. Reconcile the receipt, log, and service; do not retry.",
        )
    return result


def _stop_child(process: subprocess.Popen[bytes]) -> int:
    """Terminate only this child after timeout, then reap it; never cancel an Airflow job."""
    with suppress(ProcessLookupError):
        process.terminate()
    try:
        return process.wait(timeout=_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            process.kill()
        return process.wait()


def _wait(
    process: subprocess.Popen[bytes], timeout: float, log: Path
) -> tuple[SubmissionResult, int | None]:
    """Interpret the CLI outcome conservatively, without retries or network requests."""
    try:
        exit_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            exit_code = _stop_child(process)
        except Exception as error:
            message = f"Submission timed out; child cleanup failed ({type(error).__name__})."
            exit_code = process.returncode
        else:
            message = "Submission timed out; the local child was stopped."
        result = _result("unknown", f"{message} Service acceptance is unknown; do not retry.", log)
        return result, exit_code
    except Exception as error:
        return _result(
            "unknown",
            f"Cannot determine child outcome ({type(error).__name__}); do not retry.",
            log,
        ), process.returncode
    if exit_code == 0:
        return _result(
            "accepted", "Submission accepted by the configured CLI; upload is not complete.", log
        ), exit_code
    return _result(
        "unknown", f"CLI exited {exit_code}; it may already have submitted. Do not retry.", log
    ), exit_code


def submit_upload(request: UploadRequest, settings: SubmissionSettings) -> SubmissionResult:
    """Submit once after explicit consent; call synchronously ONLY in a background worker.

    Parameters
    ----------
    request : UploadRequest
        Captured identity whose full evidence and metadata the caller has just revalidated.
    settings : SubmissionSettings
        Opt-in and local launch configuration; the external script prerequisites must hold.

    Returns
    -------
    SubmissionResult
        Errors are returned, not raised. A zero exit means ``accepted`` only under the
        documented script contract. Nonzero exits and timeouts are ``unknown`` because
        service acceptance may precede a CLI failure. Every receipt blocks another launch.

    Notes
    -----
    No directories or acquisition data are created, moved, or removed. Only a log, receipt,
    and temporary receipt files are written under existing derivatives. The child uses a
    new session and file redirection so GUI shutdown need not kill it. Worker lifetime and
    daemon orchestration belong to the caller; an interrupted parent can leave ``submitting``.
    """
    if not settings.enabled:
        return SubmissionResult("disabled", "Upload submission is disabled; nothing was started.")
    try:
        path = receipt_path(request)
        log_path = path.with_name("upload_submission.log")
    except Exception as error:
        return SubmissionResult("failed-to-start", f"Invalid request ({type(error).__name__}).")
    try:
        _preflight(request, settings)
    except FileExistsError:
        return _result(
            "duplicate", "An existing receipt blocks submission; reconcile manually.", log_path
        )
    except Exception as error:
        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
        return _result("failed-to-start", f"Preflight failed: {detail}", log_path)

    payload: dict[str, object] = {
        "run_id": request.run_id,
        "source": str(request.source),
        "subject_id": request.subject_id,
        "project_name": settings.project_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state": "submitting",
        "exit_code": None,
    }
    argv = [
        str(settings.interpreter), str(settings.script), str(request.source),
        "--project-name", settings.project_name, "--subject-id", request.subject_id,
    ]
    claimed = False
    process: subprocess.Popen[bytes] | None = None
    try:
        with _open_log(log_path) as log:
            try:
                stream = path.open("x", encoding="utf-8")
            except FileExistsError:
                return _result(
                    "duplicate", "Another process already claimed this dataset.", log_path
                )
            with stream:
                claimed = True
                json.dump(payload, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            process = subprocess.Popen(
                argv, cwd=str(settings.working_directory), shell=False, start_new_session=True,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True,
            )
    except Exception as error:
        status = "unknown" if process is not None else "failed-to-start"
        message = "Submission did not start"
        exit_code = None
        if process is not None:
            message = "Submission may have started"
            _, exit_code = _wait(process, settings.timeout_seconds, log_path)
        result = _result(status, f"{message} ({type(error).__name__}); do not retry.", log_path)
        return _finish(path, payload, result, exit_code) if claimed else result
    result, exit_code = _wait(process, settings.timeout_seconds, log_path)
    return _finish(path, payload, result, exit_code)