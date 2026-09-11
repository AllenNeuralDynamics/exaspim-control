"""Verify completion with real temporary files and metadata, never hardware or transfers.

The recorder is exercised directly: importing the hardware acquisition worker is deliberately
outside this suite's scope. Sampled hashes detect changes in sampled regions, not every byte.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest
from aind_data_schema.components.wrappers import AssetPath
from test_metadata_launch import (
    _FIXED_DT,
    _build_metadata_launch,
    _expected_acquisition,
)

from exaspim_control import acquisition_completion as completion
from exaspim_control.upload_submission import UploadRequest

_NAME = "tile_000000_ch_CH639"
_IMS = f"{_NAME}.ims"
_DATA = b"0123456789abcdef" * (1 << 14)


@dataclass
class CompletionCase:
    """Keep paths, lightweight acquisition inputs, and the recorder together."""

    mount: Path
    root: Path
    source: Path
    acquisition: MagicMock
    writer: SimpleNamespace
    run: completion.RunEvidence

    def verify(self) -> UploadRequest:
        """Verify a new snapshot against this case's explicitly configured mount."""
        return completion.verify_completion(self.run.snapshot(), self.mount)

    def payload(self, name: str = "acquisition.json") -> dict[str, Any]:
        """Read a finalization artifact for a focused mutation."""
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def write_payload(self, payload: dict[str, Any], name: str = "acquisition.json") -> None:
        """Serialize a mutated artifact without touching repository fixtures."""
        (self.root / name).write_text(json.dumps(payload), encoding="utf-8")


def _new_case(tmp_path: Path, repeats: int = 1) -> CompletionCase:
    """Configure the real recorder using only plain values and a mocked acquisition."""
    mount = tmp_path / "vast"
    root = mount / "exaSPIM_123_2022-12-27_08-26-49"
    source = tmp_path / "local" / root.name
    root.mkdir(parents=True)
    source.mkdir(parents=True)
    transfer = SimpleNamespace(external_path=mount, acquisition_name=root.name)
    acquisition = MagicMock(
        metadata=SimpleNamespace(subject_id=" 123 "),
        file_transfers={"camera": {"CH639": transfer}},
        config={"acquisition": {"tiles": [{
            "prefix": "tile", "tile_number": 0, "channel": "CH639",
            "repeats": repeats, "round_z_mm": 4, "steps": 5,
        }]}},
    )
    writer = SimpleNamespace(
        path=source.parent, acquisition_name=source.name,
        _process=SimpleNamespace(exitcode=0),
    )
    run = completion.RunEvidence(started_at=_FIXED_DT)
    run.configure(acquisition)
    assert run.error is None
    return CompletionCase(mount, root, source, acquisition, writer, run)


def _finalized_case(tmp_path: Path, repeats: int = 1) -> CompletionCase:
    """Capture hashes before moving sources, then write valid final-layout metadata."""
    case = _new_case(tmp_path, repeats)
    for folder in ("exaSPIM", "derivatives"):
        (case.root / folder).mkdir()
    for name, frames in case.run.expected.items():
        primary = Path(name)
        for suffix in (".ims", ".tiff", ".log", ".yaml"):
            (case.source / primary.with_suffix(suffix)).write_bytes(_DATA)
        case.run.record_tile(primary.stem, frames, case.writer)
        assert case.run.error is None
        for path in case.source.iterdir():
            folder = "exaSPIM" if path.suffix == ".ims" else "derivatives"
            path.rename(case.root / folder / path.name)
    transfer = Mock()
    transfer.is_alive.return_value = False
    case.run.finish({"camera": {"CH639": {0: transfer}}})
    assert case.run.error is None
    assert case.run.finished_at is not None
    case.run.finished_at = _FIXED_DT
    launch = _build_metadata_launch()
    launch.instrument.config["instrument"]["id"] = "exaspim123"
    launch.instrument.config["instrument"]["devices"] = {
        "639 nm": {
            "type": "laser", "driver": "voxel.devices.laser.oxxius.lbx",
            "init": {"wavelength": 639},
        },
        "vp-151mx": {
            "type": "camera", "driver": "voxel.devices.camera.vieworks.egrabber",
            "properties": {"sensor_width_px": 14192, "sensor_height_px": 10640},
        },
        "z": {
            "type": "scanning_stage", "driver": "voxel.devices.stage.asi.tiger",
            "init": {"instrument_axis": "z"},
        },
    }
    acquisition = _expected_acquisition()
    imaging = acquisition.data_streams[0].configurations[0]
    image = imaging.images[0]
    imaging.images = [
        image.model_copy(update={"file_name": AssetPath(name)}, deep=True)
        for name in case.run.expected
    ]
    instrument = launch.parse_instrument(coordinate_system=acquisition.coordinate_system)
    assert instrument.instrument_id == acquisition.instrument_id
    acquisition.write_standard_file(output_directory=case.root, prefix=None)
    instrument.write_standard_file(output_directory=case.root, prefix=None)
    case.write_payload({"dataset_status": {"status": "pending"}}, "processing_manifest.json")
    for name in ("acquisition_config.yaml", "instrument_config.yaml"):
        (case.root / "derivatives" / name).write_text("config: present\n", encoding="utf-8")
    return case


@pytest.fixture
def recording(tmp_path: Path) -> CompletionCase:
    """Provide an unexecuted, configured acquisition."""
    return _new_case(tmp_path)


@pytest.fixture
def finalized(tmp_path: Path) -> CompletionCase:
    """Provide a complete, independently schema-valid acquisition."""
    return _finalized_case(tmp_path)


def test_run_defaults_have_unique_identity_and_aware_start() -> None:
    """Fresh records never reuse another run's identity or mutable containers."""
    before = datetime.now(timezone.utc)
    first, second = completion.RunEvidence(), completion.RunEvidence()
    assert first.run_id != second.run_id
    assert len(first.run_id) == 32
    assert before <= first.started_at <= datetime.now(timezone.utc)
    assert first.started_at.utcoffset() == timedelta(0)
    assert first.finished_at is None and first.error is None and not first.cancelled
    first.expected[_IMS] = 8
    first.completed[_IMS] = 8
    first.files.append(completion.FileEvidence(f"exaSPIM/{_IMS}", 1, b"hash"))
    assert not second.expected and not second.completed and not second.files


@pytest.mark.parametrize("subject,expected", [(123, "123"), (" 123 ", "123"), (None, "")])
def test_configure_captures_subject_and_rounded_repeated_plan(
    tmp_path: Path, subject: Any, expected: str
) -> None:
    """Capture normalized identity, repeat suffixes, and rounded frame counts."""
    case = _new_case(tmp_path, repeats=3)
    case.acquisition.metadata.subject_id = subject
    run = completion.RunEvidence()
    run.configure(case.acquisition)
    assert run.error is None
    assert run.subject_id == expected
    assert run.dataset_roots == (case.root.absolute(),)
    assert run.expected == {
        _IMS: 8, f"{_NAME}_repeat_1.ims": 8, f"{_NAME}_repeat_2.ims": 8,
    }
    case.acquisition.config["acquisition"]["tiles"].clear()
    case.acquisition.metadata.subject_id = "different"
    assert len(run.expected) == 3 and run.subject_id == expected


def test_configure_deduplicates_and_sorts_destinations(recording: CompletionCase) -> None:
    """Repeated transfer definitions for one dataset do not imply multiple datasets."""
    first = SimpleNamespace(external_path=recording.mount, acquisition_name="a")
    last = SimpleNamespace(external_path=recording.mount, acquisition_name="z")
    recording.acquisition.file_transfers = {"one": {0: last, 1: first}, "two": {0: last}}
    run = completion.RunEvidence()
    run.configure(recording.acquisition)
    assert run.error is None
    assert run.dataset_roots == (recording.mount / "a", recording.mount / "z")


@pytest.mark.parametrize(
    "change,message",
    [
        ({"prefix": "nested/tile"}, "Ambiguous"),
        ({"prefix": "../tile"}, "Ambiguous"),
        ({"prefix": "/absolute/tile"}, "Ambiguous"),
        ({"channel": "CH639/other"}, "Ambiguous"),
        ({"steps": 0}, "No frames"),
        ({"steps": -8}, "No frames"),
        ({"round_z_mm": 0}, "division by zero"),
    ],
)
def test_configure_invalid_plan_fails_closed_without_raising(
    recording: CompletionCase, change: dict[str, Any], message: str
) -> None:
    """Unsafe names and invalid requested frame counts cannot authorize a prompt."""
    recording.acquisition.config["acquisition"]["tiles"][0].update(change)
    run = completion.RunEvidence()
    run.configure(recording.acquisition)
    assert message in (run.error or "")
    assert run.finished_at is None


def test_configure_duplicate_names_fail_closed(recording: CompletionCase) -> None:
    """Two tiles resolving to the same filename are ambiguous even with equal counts."""
    tiles = recording.acquisition.config["acquisition"]["tiles"]
    tiles.append(dict(tiles[0]))
    run = completion.RunEvidence()
    run.configure(recording.acquisition)
    assert run.error == "Ambiguous output filenames"


@pytest.mark.parametrize("tiles", [[], [{"repeats": 0}]])
def test_no_expected_work_cannot_be_verified(recording: CompletionCase, tiles: list) -> None:
    """An empty plan or zero repetitions never constitutes completed work."""
    recording.acquisition.config["acquisition"]["tiles"] = tiles
    run = completion.RunEvidence(started_at=_FIXED_DT)
    run.configure(recording.acquisition)
    run.finish({})
    assert not run.expected
    with pytest.raises(completion.UnverifiedAcquisition, match="did not complete"):
        completion.verify_completion(run.snapshot(), recording.mount)


def test_record_tile_captures_supported_sidecars_only(recording: CompletionCase) -> None:
    """Source evidence uses final relative paths and excludes unrelated extensions."""
    for suffix in (".ims", ".tiff", ".log", ".yaml", ".txt"):
        (recording.source / f"{_NAME}{suffix}").write_bytes(_DATA)
    (recording.source / "unrelated.ims").write_bytes(b"unrelated")
    recording.run.record_tile(_NAME, 8, recording.writer)
    assert recording.run.error is None
    assert recording.run.completed == {_IMS: 8}
    assert {item.relative_path for item in recording.run.files} == {
        f"exaSPIM/{_IMS}", *(f"derivatives/{_NAME}{ext}" for ext in (".tiff", ".log", ".yaml")),
    }
    for item in recording.run.files:
        source = recording.source / Path(item.relative_path).name
        assert item == completion.file_evidence(source, item.relative_path)


@pytest.mark.parametrize("exit_code", [None, 1, -9])
def test_writer_unsuccessful_outcome_fails_closed(
    recording: CompletionCase, exit_code: int | None
) -> None:
    """Waiting on a writer is insufficient without an observed zero exit code."""
    (recording.source / _IMS).write_bytes(_DATA)
    recording.writer._process.exitcode = exit_code
    recording.run.record_tile(_NAME, 8, recording.writer)
    assert recording.run.error == "Writer did not exit successfully"
    assert not recording.run.completed and not recording.run.files


@pytest.mark.parametrize("writer", [SimpleNamespace(), SimpleNamespace(_process=SimpleNamespace())])
def test_missing_writer_outcome_is_logged_not_raised(
    recording: CompletionCase, writer: SimpleNamespace, caplog: pytest.LogCaptureFixture
) -> None:
    """Unknown writer drivers cannot leak optional observation errors into acquisition."""
    recording.run.record_tile(_NAME, 8, writer)
    assert recording.run.error
    assert "Upload evidence unavailable" in caplog.text
    assert not recording.run.completed


@pytest.mark.parametrize("frames", [0, 7, 9])
def test_record_tile_requires_exact_frame_count(recording: CompletionCase, frames: int) -> None:
    """Neither underproduction nor overproduction matches the planned tile."""
    recording.run.record_tile(_NAME, frames, recording.writer)
    assert recording.run.error == "Incomplete or repeated tile execution"
    assert not recording.run.completed


def test_record_unknown_tile_fails_closed(recording: CompletionCase) -> None:
    """Unplanned work cannot silently expand the expected plan."""
    recording.run.record_tile("unknown", 8, recording.writer)
    assert recording.run.error and not recording.run.completed


def test_record_duplicate_tile_does_not_duplicate_evidence(recording: CompletionCase) -> None:
    """Repeated completion notifications retain the first manifest but invalidate the run."""
    (recording.source / _IMS).write_bytes(_DATA)
    recording.run.record_tile(_NAME, 8, recording.writer)
    original = tuple(recording.run.files)
    recording.run.record_tile(_NAME, 8, recording.writer)
    assert recording.run.error == "Incomplete or repeated tile execution"
    assert tuple(recording.run.files) == original


def test_missing_primary_source_fails_closed(recording: CompletionCase) -> None:
    """A successful process without its IMS output is not a completed tile."""
    recording.run.record_tile(_NAME, 8, recording.writer)
    assert recording.run.error == "Expected IMS source is missing"
    assert not recording.run.completed


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_nonregular_source_sidecar_fails_closed(recording: CompletionCase, kind: str) -> None:
    """The recorder refuses directories and symlinks among recognized source files."""
    (recording.source / _IMS).write_bytes(_DATA)
    path = recording.source / f"{_NAME}.tiff"
    if kind == "directory":
        path.mkdir()
    else:
        path.symlink_to(recording.source / _IMS)
    recording.run.record_tile(_NAME, 8, recording.writer)
    assert recording.run.error == "Unexpected source type"
    assert not recording.run.completed


def test_hash_read_failure_is_an_observation_error(
    recording: CompletionCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hashing failure leaves the hardware-facing observer nonthrowing."""
    (recording.source / _IMS).write_bytes(_DATA)
    monkeypatch.setattr(completion, "hashfile", Mock(side_effect=OSError("unreadable")))
    recording.run.record_tile(_NAME, 8, recording.writer)
    assert recording.run.error == "unreadable"
    assert not recording.run.completed


@pytest.mark.parametrize("flag,value", [("cancelled", True), ("error", "earlier failure")])
def test_abort_and_error_remain_sticky_across_later_success(
    recording: CompletionCase, flag: str, value: Any
) -> None:
    """Later configure, record, and finish observations never erase a failed run."""
    run = completion.RunEvidence(started_at=_FIXED_DT)
    setattr(run, flag, value)
    run.configure(recording.acquisition)
    (recording.source / _IMS).write_bytes(_DATA)
    run.record_tile(_NAME, 8, recording.writer)
    run.finish({})
    assert getattr(run, flag) == value
    assert run.completed == run.expected and run.finished_at is not None
    with pytest.raises(completion.UnverifiedAcquisition, match="did not complete"):
        completion.verify_completion(run.snapshot(), recording.mount)


def test_finish_observes_every_nested_transfer() -> None:
    """Normal return is timestamped only after every configured nested worker is checked."""
    workers = [Mock() for _ in range(4)]
    for worker in workers:
        worker.is_alive.return_value = False
    run = completion.RunEvidence()
    before = datetime.now(timezone.utc)
    run.finish({"one": {"red": {0: workers[0], 1: workers[1]}, "green": {0: workers[2]}},
                "two": {"red": {0: workers[3]}}})
    assert run.error is None
    assert before <= run.finished_at <= datetime.now(timezone.utc)
    for worker in workers:
        worker.is_alive.assert_called_once_with()


@pytest.mark.parametrize("kind", ["alive", "missing-method", "raises"])
def test_unavailable_transfer_outcome_fails_closed(kind: str) -> None:
    """No completion timestamp is captured for a running or unobservable transfer."""
    worker = Mock()
    worker.is_alive.return_value = True
    if kind == "missing-method":
        worker = SimpleNamespace()
    elif kind == "raises":
        worker.is_alive.side_effect = OSError("outcome unavailable")
    run = completion.RunEvidence()
    run.finish({"camera": {"CH639": {0: worker}}})
    assert run.error and run.finished_at is None


def test_no_transfers_records_return_but_does_not_authorize_upload(
    recording: CompletionCase,
) -> None:
    """Local-only acquisitions can finish, but have no eligible external destination."""
    recording.acquisition.file_transfers = {}
    run = completion.RunEvidence(started_at=_FIXED_DT)
    run.configure(recording.acquisition)
    (recording.source / _IMS).write_bytes(_DATA)
    run.record_tile(_NAME, 8, recording.writer)
    run.finish({})
    assert run.error is None and run.finished_at is not None
    with pytest.raises(completion.UnverifiedAcquisition, match="single configured VAST"):
        completion.verify_completion(run.snapshot(), recording.mount)


def test_snapshot_is_frozen_and_detached_from_live_state(finalized: CompletionCase) -> None:
    """Tuples and frozen file records cannot be changed through GUI or worker state."""
    snapshot = finalized.run.snapshot()
    assert snapshot.expected == snapshot.completed == ((_IMS, 8),)
    assert snapshot.started_at == snapshot.finished_at == _FIXED_DT
    assert snapshot.dataset_roots == (finalized.root,)
    finalized.run.expected.clear()
    finalized.run.completed.clear()
    finalized.run.files.clear()
    finalized.run.subject_id = "changed"
    finalized.run.cancelled = True
    assert snapshot.subject_id == "123" and not snapshot.cancelled
    assert snapshot.files and snapshot.expected == ((_IMS, 8),)
    for instance, field, value in (
        (snapshot, "subject_id", "changed"), (snapshot.files[0], "size", 0),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(instance, field, value)


def test_file_evidence_uses_transfer_sample_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The actual hasher receives the classic transfer sample size and source filename."""
    path = tmp_path / _IMS
    path.write_bytes(_DATA)
    hasher = Mock(wraps=completion.hashfile)
    monkeypatch.setattr(completion, "hashfile", hasher)
    evidence = completion.file_evidence(path, f"exaSPIM/{_IMS}")
    assert evidence.relative_path == f"exaSPIM/{_IMS}"
    assert evidence.size == len(_DATA) and isinstance(evidence.fingerprint, bytes)
    hasher.assert_called_once_with(str(path), sample_size=1 << 14)


@pytest.mark.parametrize("kind", ["empty", "size", "mtime"])
def test_file_evidence_rejects_empty_or_changing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Changes between the two stat calls fail even if a hash can be obtained."""
    path = tmp_path / _IMS
    path.write_bytes(b"" if kind == "empty" else _DATA)
    before = path.stat()
    if kind != "empty":
        after = SimpleNamespace(
            st_size=before.st_size + (kind == "size"),
            st_mtime_ns=before.st_mtime_ns + (kind == "mtime"),
        )
        monkeypatch.setattr(Path, "stat", Mock(side_effect=[before, after]))
        monkeypatch.setattr(completion, "hashfile", Mock(return_value=b"fingerprint"))
    with pytest.raises(completion.UnverifiedAcquisition, match="Empty or changing file"):
        completion.file_evidence(path, f"exaSPIM/{_IMS}")


def test_valid_final_layout_verifies_read_only(finalized: CompletionCase) -> None:
    """Real schema models and pre-transfer fingerprints produce immutable request values."""
    before = {p.relative_to(finalized.root): p.read_bytes()
              for p in finalized.root.rglob("*") if p.is_file()}
    request = finalized.verify()
    assert request == UploadRequest(finalized.run.run_id, finalized.root.resolve(), "123")
    assert request.source == finalized.root / "exaSPIM"
    after = {p.relative_to(finalized.root): p.read_bytes()
             for p in finalized.root.rglob("*") if p.is_file()}
    assert before == after
    assert not any(finalized.source.iterdir())


@pytest.mark.parametrize(
    "changes",
    [
        {"error": "failed"}, {"cancelled": True}, {"finished_at": None}, {"subject_id": ""},
        {"expected": ()}, {"completed": ()}, {"completed": ((_IMS, 7),)},
        {"completed": ((_IMS, 9),)}, {"completed": ((_IMS, 8), ("extra.ims", 8))},
        {"expected": ((_IMS, 8), ("missing.ims", 8))},
    ],
)
def test_incomplete_run_rejected_before_filesystem_access(
    finalized: CompletionCase, changes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any missing work or unsuccessful outcome blocks verification before path resolution."""
    resolve = Mock(side_effect=AssertionError("must not access filesystem"))
    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(completion.UnverifiedAcquisition, match="did not complete"):
        completion.verify_completion(replace(finalized.run.snapshot(), **changes), finalized.mount)
    resolve.assert_not_called()


@pytest.mark.parametrize("kind", ["none", "zero", "duplicate", "multiple"])
def test_requires_one_explicit_vast_destination(finalized: CompletionCase, kind: str) -> None:
    """No destination, duplicate roots, and multiple destinations all fail closed."""
    roots = {
        "none": (finalized.root,), "zero": (), "duplicate": (finalized.root,) * 2,
        "multiple": (finalized.root, finalized.mount / "other"),
    }
    evidence = replace(finalized.run.snapshot(), dataset_roots=roots[kind])
    mount = None if kind == "none" else finalized.mount
    with pytest.raises(completion.UnverifiedAcquisition, match="single configured VAST"):
        completion.verify_completion(evidence, mount)


@pytest.mark.parametrize("kind", ["equal", "outside", "prefix", "missing-root", "missing-mount"])
def test_dataset_must_exist_strictly_beneath_mount(
    finalized: CompletionCase, tmp_path: Path, kind: str
) -> None:
    """Resolve existing paths and check actual ancestry, not lexical path prefixes."""
    sibling = tmp_path / "vast-other"
    sibling.mkdir()
    roots = {
        "equal": finalized.mount, "outside": tmp_path, "prefix": sibling,
        "missing-root": finalized.mount / "missing", "missing-mount": finalized.root,
    }
    evidence = replace(finalized.run.snapshot(), dataset_roots=(roots[kind],))
    mount = tmp_path / "absent" if kind == "missing-mount" else finalized.mount
    with pytest.raises((completion.UnverifiedAcquisition, FileNotFoundError)):
        completion.verify_completion(evidence, mount)


@pytest.mark.parametrize("kind", ["missing", "extra", "nested", "renamed", "directory"])
def test_exact_ims_layout_is_required(finalized: CompletionCase, kind: str) -> None:
    """Missing, additional, nested, renamed, or nonregular IMS entries cannot pass."""
    path = finalized.root / "exaSPIM" / _IMS
    if kind == "extra":
        path.with_name("unexpected.ims").write_bytes(_DATA)
    elif kind == "nested":
        path.parent.joinpath("nested").mkdir()
        path.rename(path.parent / "nested" / path.name)
    elif kind == "renamed":
        path.rename(path.with_suffix(".tiff"))
    else:
        path.unlink()
        if kind == "directory":
            path.mkdir()
    with pytest.raises(completion.UnverifiedAcquisition, match="IMS inputs|unsafe output"):
        finalized.verify()


def test_unrecorded_non_ims_notes_do_not_expand_required_inputs(finalized: CompletionCase) -> None:
    """Unrelated text is not an IMS tile or claimed transfer evidence."""
    (finalized.root / "exaSPIM" / "notes.txt").write_text("notes", encoding="utf-8")
    (finalized.root / "derivatives" / "operator.txt").write_text("notes", encoding="utf-8")
    assert finalized.verify().subject_id == "123"


@pytest.mark.parametrize("kind", ["all", "ims-only"])
def test_missing_fingerprint_evidence_is_rejected(finalized: CompletionCase, kind: str) -> None:
    """File presence cannot replace a pre-transfer fingerprint for each acquired IMS."""
    finalized.run.files = [] if kind == "all" else [
        item for item in finalized.run.files if not item.relative_path.endswith(".ims")
    ]
    with pytest.raises(
        completion.UnverifiedAcquisition, match="fingerprint evidence is incomplete",
    ):
        finalized.verify()


@pytest.mark.parametrize("suffix", [".ims", ".tiff", ".log", ".yaml"])
@pytest.mark.parametrize("kind", ["missing", "empty", "size", "sample-hash"])
def test_transferred_primary_and_sidecars_require_original_content(
    finalized: CompletionCase, suffix: str, kind: str
) -> None:
    """Verify every recorded file, including same-size corruption in a sampled region."""
    folder = "exaSPIM" if suffix == ".ims" else "derivatives"
    path = finalized.root / folder / f"{_NAME}{suffix}"
    if kind == "missing":
        path.unlink()
    else:
        content = {"empty": b"", "size": _DATA + b"extra", "sample-hash": b"X" + _DATA[1:]}
        path.write_bytes(content[kind])
    with pytest.raises(completion.UnverifiedAcquisition):
        finalized.verify()


def test_verification_rejects_file_changing_during_hash(
    finalized: CompletionCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A racing write during final verification must not produce an eligible request."""
    original = completion.hashfile
    target = finalized.root / "exaSPIM" / _IMS

    def changing_hash(filename: str, sample_size: int) -> bytes:
        """Change only this test's IMS after the verifier captures its initial stat."""
        if Path(filename) == target:
            target.write_bytes(_DATA + b"racing write")
        return original(filename, sample_size=sample_size)

    monkeypatch.setattr(completion, "hashfile", changing_hash)
    with pytest.raises(completion.UnverifiedAcquisition, match="Empty or changing file"):
        finalized.verify()


def test_duplicate_file_evidence_is_rejected(finalized: CompletionCase) -> None:
    """Even identical repeated evidence is ambiguous rather than silently deduplicated."""
    finalized.run.files.append(finalized.run.files[0])
    with pytest.raises(completion.UnverifiedAcquisition, match="Duplicate output evidence"):
        finalized.verify()


@pytest.mark.parametrize("relative", ["../outside.ims", "exaSPIM/../outside.ims", "/absolute.ims"])
def test_unsafe_evidence_paths_are_rejected(finalized: CompletionCase, relative: str) -> None:
    """Absolute paths and traversal are invalid even before looking for a file."""
    finalized.run.files.append(completion.FileEvidence(relative, 1, b"hash"))
    with pytest.raises(completion.UnverifiedAcquisition, match="Invalid output path"):
        finalized.verify()


@pytest.mark.parametrize("kind", ["internal", "external", "dangling", "parent-escape"])
def test_symlinked_outputs_are_rejected(
    finalized: CompletionCase, tmp_path: Path, kind: str
) -> None:
    """Refuse direct links and directory links escaping the finalized dataset."""
    path = finalized.root / "exaSPIM" / _IMS
    if kind == "parent-escape":
        directory = path.parent
        target = tmp_path / "escaped-images"
        directory.rename(target)
        directory.symlink_to(target, target_is_directory=True)
    else:
        target = finalized.root / "internal-data" if kind == "internal" else tmp_path / "external"
        if kind != "dangling":
            target.write_bytes(_DATA)
        path.unlink()
        path.symlink_to(target)
    with pytest.raises(completion.UnverifiedAcquisition, match="unsafe output"):
        finalized.verify()


@pytest.mark.parametrize(
    "name", ["acquisition.json", "instrument.json", "processing_manifest.json"],
)
@pytest.mark.parametrize("kind", ["missing", "broken-json", "invalid-schema"])
def test_required_metadata_artifacts_are_validated(
    finalized: CompletionCase, name: str, kind: str
) -> None:
    """A file with the right name alone is not valid metadata or a pending manifest."""
    path = finalized.root / name
    if kind == "missing":
        path.unlink()
    else:
        path.write_text("{" if kind == "broken-json" else "{}", encoding="utf-8")
    with pytest.raises(ValueError):
        finalized.verify()


@pytest.mark.parametrize(
    "name,field,value,message",
    [
        ("acquisition.json", "subject_id", "other", "subject"),
        ("acquisition.json", "instrument_id", "other", "Instrument"),
        ("instrument.json", "instrument_id", "other", "Instrument"),
    ],
)
def test_metadata_identity_matches_captured_run(
    finalized: CompletionCase, name: str, field: str, value: str, message: str
) -> None:
    """The two schema-valid documents must describe this subject and the same instrument."""
    payload = finalized.payload(name)
    payload[field] = value
    if field == "subject_id":
        payload["specimen_id"] = value
    finalized.write_payload(payload, name)
    with pytest.raises(completion.UnverifiedAcquisition, match=message):
        finalized.verify()


def test_metadata_missing_instrument_identity_is_rejected(finalized: CompletionCase) -> None:
    """The schema itself rejects an acquisition with streams but no instrument identity."""
    payload = finalized.payload()
    payload["instrument_id"] = ""
    finalized.write_payload(payload)
    with pytest.raises(ValueError, match="instrument_id is required"):
        finalized.verify()


@pytest.mark.parametrize(
    "field",
    ["acquisition_start_time", "acquisition_end_time"],
)
def test_metadata_naive_timestamps_are_rejected(finalized: CompletionCase, field: str) -> None:
    """Timezone-free metadata must not be treated as an unambiguous run boundary."""
    payload = finalized.payload()
    payload[field] = _FIXED_DT.replace(tzinfo=None).isoformat()
    finalized.write_payload(payload)
    with pytest.raises(ValueError):
        finalized.verify()


def test_metadata_end_before_start_is_rejected(finalized: CompletionCase) -> None:
    """Acquisition metadata cannot end before it starts."""
    payload = finalized.payload()
    payload["acquisition_end_time"] = (_FIXED_DT - timedelta(seconds=1)).isoformat()
    finalized.write_payload(payload)
    with pytest.raises(ValueError):
        finalized.verify()


@pytest.mark.parametrize("field,offset", [("started_at", -61), ("started_at", 61),
                                         ("finished_at", 61)])
def test_metadata_timestamps_must_describe_this_run(
    finalized: CompletionCase, field: str, offset: int
) -> None:
    """Reject stale metadata beyond the documented sixty-second tolerance."""
    setattr(finalized.run, field, _FIXED_DT + timedelta(seconds=offset))
    with pytest.raises(completion.UnverifiedAcquisition, match="timestamps"):
        finalized.verify()


@pytest.mark.parametrize("offset", [-60, 0, 60])
def test_timestamp_tolerance_includes_boundary(finalized: CompletionCase, offset: int) -> None:
    """Small boundary differences do not invalidate otherwise matching metadata."""
    finalized.run.started_at = _FIXED_DT + timedelta(seconds=offset)
    finalized.run.finished_at = _FIXED_DT + timedelta(seconds=60)
    assert finalized.verify().subject_id == "123"


@pytest.mark.parametrize("prefix", ["", "exaSPIM/"])
def test_metadata_accepts_finalizer_filename_forms(finalized: CompletionCase, prefix: str) -> None:
    """Both supported relative forms identify the same acquired IMS filename."""
    payload = finalized.payload()
    payload["data_streams"][0]["configurations"][0]["images"][0]["file_name"] = prefix + _IMS
    finalized.write_payload(payload)
    assert finalized.verify().source == finalized.root / "exaSPIM"


@pytest.mark.parametrize(
    "filename", [f"nested/{_IMS}", f"derivatives/{_IMS}", f"../{_IMS}", f"/{_IMS}",
                 "wrong.ims", f"{_NAME}.tiff"],
)
def test_metadata_image_paths_and_names_must_match(
    finalized: CompletionCase, filename: str,
) -> None:
    """Metadata may not point to another folder or replace a planned image name."""
    payload = finalized.payload()
    payload["data_streams"][0]["configurations"][0]["images"][0]["file_name"] = filename
    finalized.write_payload(payload)
    with pytest.raises(ValueError):
        finalized.verify()


@pytest.mark.parametrize("kind", ["missing", "duplicate", "duplicate-stream"])
def test_metadata_requires_exact_image_coverage(finalized: CompletionCase, kind: str) -> None:
    """A set of correct filenames is insufficient when multiplicity is wrong."""
    payload = finalized.payload()
    images = payload["data_streams"][0]["configurations"][0]["images"]
    if kind == "missing":
        images.clear()
    elif kind == "duplicate":
        images.append(dict(images[0]))
    else:
        payload["data_streams"].append(payload["data_streams"][0])
    finalized.write_payload(payload)
    with pytest.raises(ValueError):
        finalized.verify()


@pytest.mark.parametrize("missing_repeat", [False, True])
def test_repeated_tiles_require_matching_metadata_coverage(
    tmp_path: Path, missing_repeat: bool
) -> None:
    """A repeat is distinct expected work, not a duplicate base-tile filename."""
    case = _finalized_case(tmp_path, repeats=2)
    assert len(case.run.expected) == len(case.run.completed) == 2
    if missing_repeat:
        payload = case.payload()
        payload["data_streams"][0]["configurations"][0]["images"].pop()
        case.write_payload(payload)
        with pytest.raises(completion.UnverifiedAcquisition, match="exact acquired IMS"):
            case.verify()
    else:
        assert case.verify().subject_id == "123"


@pytest.mark.parametrize("status", [None, "", "submitted", "complete", "Pending"])
def test_processing_manifest_must_be_pending(finalized: CompletionCase, status: str | None) -> None:
    """Only the finalizer's literal pending status authorizes the next operator question."""
    finalized.write_payload({"dataset_status": {"status": status}}, "processing_manifest.json")
    with pytest.raises(completion.UnverifiedAcquisition, match="not pending"):
        finalized.verify()


@pytest.mark.parametrize("name", ["acquisition_config.yaml", "instrument_config.yaml"])
@pytest.mark.parametrize("kind", ["missing", "empty", "directory", "symlink"])
def test_final_configuration_artifacts_must_be_nonempty_regular_files(
    finalized: CompletionCase, name: str, kind: str
) -> None:
    """Both exact config filenames are required; the verifier never creates or repairs them."""
    path = finalized.root / "derivatives" / name
    path.unlink()
    if kind == "empty":
        path.touch()
    elif kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        path.symlink_to(finalized.root / "acquisition.json")
    with pytest.raises(completion.UnverifiedAcquisition):
        finalized.verify()


@pytest.mark.parametrize("kind", ["missing", "empty", "wrong-extension", "directory", "nested"])
def test_finalization_requires_a_nonempty_top_level_log(
    finalized: CompletionCase, kind: str,
) -> None:
    """A missing run log must fail even when no log was part of source-file evidence."""
    finalized.run.files = [f for f in finalized.run.files if not f.relative_path.endswith(".log")]
    path = finalized.root / "derivatives" / f"{_NAME}.log"
    path.unlink()
    if kind == "empty":
        path.touch()
    elif kind == "wrong-extension":
        path.with_suffix(".txt").write_bytes(b"log")
    elif kind == "directory":
        path.mkdir()
    elif kind == "nested":
        path.parent.joinpath("nested").mkdir()
        path.parent.joinpath("nested", path.name).write_bytes(b"log")
    with pytest.raises(completion.UnverifiedAcquisition, match="Acquisition log is missing"):
        finalized.verify()