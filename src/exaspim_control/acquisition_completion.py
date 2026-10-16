"""Popup-only evidence; observing a run never changes acquisition or cleanup behavior."""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from aind_data_schema.components.configs import ImagingConfig
from aind_data_schema.core.acquisition import Acquisition
from aind_data_schema.core.instrument import Instrument
from imohash import hashfile

from exaspim_control.upload_submission import UploadRequest, linux_path

logger = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable[..., None])


class UnverifiedAcquisition(ValueError):
    """The available evidence does not authorize an upload prompt."""


@dataclass(frozen=True)
class FileEvidence:
    """A closed source file's final relative location, size and sampled hash."""

    relative_path: str
    size: int
    fingerprint: bytes


@dataclass(frozen=True)
class AcquisitionEvidence:
    """Immutable snapshot handed from acquisition to the verification worker."""

    run_id: str
    subject_id: str
    dataset_roots: tuple[Path, ...]
    expected: tuple[tuple[str, int], ...]
    completed: tuple[tuple[str, int], ...]
    files: tuple[FileEvidence, ...]
    started_at: datetime
    finished_at: datetime | None
    cancelled: bool
    error: str | None


def _observe(method: F) -> F:
    """Keep optional evidence failures out of the hardware execution path."""
    @wraps(method)
    def guarded(self: RunEvidence, *args: Any, **kwargs: Any) -> None:
        try:
            method(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - Observations must not interrupt hardware cleanup.
            self.error = str(exc)
            logger.warning("Upload evidence unavailable: %s", exc)

    return guarded  # type: ignore[return-value]


@dataclass
class RunEvidence:
    """Worker-local recorder for the classic acquisition's existing boundaries.

    Notes
    -----
    These observations do not stop, retry, move or delete anything. A missing
    writer exit code or a failed observation makes the run ineligible.
    """

    run_id: str = field(default_factory=lambda: uuid4().hex)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    subject_id: str = ""
    dataset_roots: tuple[Path, ...] = ()
    expected: dict[str, int] = field(default_factory=dict)
    completed: dict[str, int] = field(default_factory=dict)
    files: list[FileEvidence] = field(default_factory=list)
    finished_at: datetime | None = None
    cancelled: bool = False
    error: str | None = None

    @_observe
    def configure(self, acquisition: Any) -> None:
        """Snapshot the classic acquisition's resolved name, subject and plan."""
        self.subject_id = str(acquisition.metadata.subject_id or "").strip()
        self.dataset_roots = tuple(sorted({
            Path(transfer.external_path, transfer.acquisition_name).absolute()
            for group in acquisition.file_transfers.values()
            for transfer in group.values()
        }))
        for tile in acquisition.config["acquisition"]["tiles"]:
            for repeat in range(tile["repeats"]):
                name = f"{tile['prefix']}_{tile['tile_number']:06}_ch_{tile['channel']}"
                if repeat:
                    name += f"_repeat_{repeat}"
                name += ".ims"
                if Path(name).name != name or name in self.expected:
                    raise UnverifiedAcquisition("Ambiguous output filenames")
                rounding = int(tile["round_z_mm"])
                count = rounding * math.ceil(tile["steps"] / rounding)
                if count <= 0:
                    raise UnverifiedAcquisition("No frames requested")
                self.expected[name] = count

    @_observe
    def record_tile(self, name: str, frames: int, writer: Any) -> None:
        """Record a successfully closed writer, before transfer can remove files."""
        primary = f"{name}.ims"
        if frames != self.expected[primary] or primary in self.completed:
            raise UnverifiedAcquisition("Incomplete or repeated tile execution")
        # The classic writer exposes its multiprocessing.Process as _process.
        # Unknown drivers fail closed rather than treating a wait as success.
        if writer._process.exitcode != 0:
            raise UnverifiedAcquisition("Writer did not exit successfully")
        directory = Path(writer.path, writer.acquisition_name)
        if not (directory / primary).is_file():
            raise UnverifiedAcquisition("Expected IMS source is missing")
        for path in sorted(directory.glob(f"{name}*")):
            if path.suffix not in {".ims", ".tiff", ".log", ".yaml"}:
                continue
            if path.is_symlink() or not path.is_file():
                raise UnverifiedAcquisition("Unexpected source type")
            folder = "exaSPIM" if path.suffix == ".ims" else "derivatives"
            self.files.append(file_evidence(path, f"{folder}/{path.name}"))
        self.completed[primary] = frames

    @_observe
    def finish(self, transfers: dict) -> None:
        """Mark normal run return only after the existing transfer waits."""
        for channels in transfers.values():
            for repeats in channels.values():
                for transfer in repeats.values():
                    if transfer.is_alive():
                        raise UnverifiedAcquisition("A transfer is still running")
        self.finished_at = datetime.now(timezone.utc)

    def snapshot(self) -> AcquisitionEvidence:
        """Copy run evidence without retaining mutable hardware or GUI objects."""
        return AcquisitionEvidence(
            self.run_id, self.subject_id, self.dataset_roots,
            tuple(self.expected.items()), tuple(self.completed.items()), tuple(self.files),
            self.started_at, self.finished_at, self.cancelled, self.error,
        )


def file_evidence(path: Path, relative_path: str) -> FileEvidence:
    """Sample a stable file using the classic transfer verifier's hash convention."""
    before = path.stat()
    fingerprint = hashfile(str(path), sample_size=1 << 14)
    after = path.stat()
    if before.st_size <= 0 or (before.st_size, before.st_mtime_ns) != (
        after.st_size, after.st_mtime_ns
    ):
        raise UnverifiedAcquisition(f"Empty or changing file: {path.name}")
    return FileEvidence(relative_path, before.st_size, fingerprint)


def _regular_file(root: Path, relative: str) -> Path:
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise UnverifiedAcquisition("Invalid output path")
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise UnverifiedAcquisition(f"Missing or unsafe output: {relative}")
    return path


def _verify_metadata(root: Path, evidence: AcquisitionEvidence, expected: set[str]) -> None:
    payload = json.loads(_regular_file(root, "acquisition.json").read_text())
    acquisition = Acquisition.model_validate(payload)
    # Some schema validators fill in a timezone; require it in the original evidence.
    for name in ("acquisition_start_time", "acquisition_end_time"):
        value = payload[name]
        if not isinstance(value, str) or datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).tzinfo is None:
            raise UnverifiedAcquisition("Metadata timestamps must include a timezone")
    instrument = Instrument.model_validate_json(_regular_file(root, "instrument.json").read_text())
    if acquisition.subject_id != evidence.subject_id:
        raise UnverifiedAcquisition("Metadata subject does not match this acquisition")
    if not acquisition.instrument_id or acquisition.instrument_id != instrument.instrument_id:
        raise UnverifiedAcquisition("Instrument metadata does not match")
    start, end = acquisition.acquisition_start_time, acquisition.acquisition_end_time
    tolerance = timedelta(seconds=60)
    if (start.tzinfo is None or end.tzinfo is None or end < start
            or abs(start - evidence.started_at) > tolerance
            or evidence.finished_at is None or end < evidence.finished_at - tolerance):
        raise UnverifiedAcquisition("Metadata timestamps do not describe this run")
    names = []
    for stream in acquisition.data_streams:
        for config in stream.configurations:
            if isinstance(config, ImagingConfig):
                for image in config.images:
                    # The current finalizer emits filenames relative to the imaging folder.
                    path = Path(str(image.file_name))
                    if path.parent not in (Path("."), Path("exaSPIM")):
                        raise UnverifiedAcquisition("Unexpected metadata image path")
                    names.append(path.name)
    if set(names) != expected or len(names) != len(expected):
        raise UnverifiedAcquisition("Metadata does not cover the exact acquired IMS files")
    manifest = json.loads(_regular_file(root, "processing_manifest.json").read_text())
    if manifest.get("dataset_status", {}).get("status") != "pending":
        raise UnverifiedAcquisition("Dataset is not pending submission")


def verify_completion(
    evidence: AcquisitionEvidence, path_map: tuple[tuple[str, str], ...] = ()
) -> UploadRequest:
    """Validate final VAST data read-only, in a worker rather than the Qt thread.

    Parameters
    ----------
    evidence : AcquisitionEvidence
        Snapshot recorded by the completed acquisition, before source deletion.
    path_map : tuple of (str, str)
        Extra local-to-``/allen`` translations; see ``linux_path``.

    Returns
    -------
    UploadRequest
        The captured dataset and subject eligible for an operator question.

    Raises
    ------
    ValueError, OSError
        Completion, integrity, metadata or destination cannot be verified.
    """
    if (evidence.error or evidence.cancelled or evidence.finished_at is None
            or not evidence.subject_id or not evidence.expected
            or dict(evidence.expected) != dict(evidence.completed)):
        raise UnverifiedAcquisition("Acquisition did not complete successfully")
    if len(evidence.dataset_roots) != 1:
        raise UnverifiedAcquisition("A single transfer destination is required")
    root = evidence.dataset_roots[0].resolve(strict=True)
    try:
        linux_path(root, path_map)
    except ValueError as exc:
        raise UnverifiedAcquisition(str(exc)) from exc
    expected = {name for name, _ in evidence.expected}
    actual = {
        path.relative_to(root / "exaSPIM").as_posix()
        for path in (root / "exaSPIM").rglob("*.ims")
    }
    if actual != expected:
        raise UnverifiedAcquisition("Missing or unexpected IMS inputs on VAST")
    recorded = set()
    for item in evidence.files:
        if item.relative_path in recorded:
            raise UnverifiedAcquisition("Duplicate output evidence")
        recorded.add(item.relative_path)
        path = _regular_file(root, item.relative_path)
        if file_evidence(path, item.relative_path) != item:
            raise UnverifiedAcquisition(f"Transfer verification failed: {item.relative_path}")
    if {f"exaSPIM/{name}" for name in expected} - recorded:
        raise UnverifiedAcquisition("IMS fingerprint evidence is incomplete")
    _verify_metadata(root, evidence, expected)
    for name in ("acquisition_config.yaml", "instrument_config.yaml"):
        path = _regular_file(root, f"derivatives/{name}")
        if not path.stat().st_size:
            raise UnverifiedAcquisition("Empty acquisition configuration")
    if not any(
        path.is_file() and path.stat().st_size for path in (root / "derivatives").glob("*.log")
    ):
        raise UnverifiedAcquisition("Acquisition log is missing")
    return UploadRequest(evidence.run_id, root, evidence.subject_id)