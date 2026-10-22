"""Test the optional upload boundary without Qt, hardware, network, or real cleanup.

Actual controller threading and the hardware worker are intentionally not imported here.
Finalization uses temporary directories; copy and recursive deletion are always intercepted.
"""

from __future__ import annotations

import builtins
import json
import sys
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock, call

import pytest
from test_metadata_launch import (
    _FIXED_DT,
    _build_metadata_launch,
    _expected_acquisition,
)

from exaspim_control import metadata_launch as metadata
from exaspim_control.acquisition_completion import (
    AcquisitionEvidence,
    FileEvidence,
    RunEvidence,
)
from exaspim_control.upload_submission import SubmissionSettings

_IMS = "tile_000000_ch_CH639.ims"


@pytest.fixture
def import_attempts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record optional imports and prevent accidental Qt/hardware imports in these tests."""
    original = builtins.__import__
    attempts: list[str] = []

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        """Allow a deliberately injected prompt module, but never the real controller."""
        if name == "exaspim_control.upload_prompt":
            attempts.append(name)
            module = sys.modules.get(name)
            if module is None or not getattr(module, "_test_controller", False):
                raise AssertionError("Real prompt controller must not be imported")
        if name.split(".")[0] in {"qtpy", "PyQt5", "PyQt6", "PySide2", "PySide6", "voxel", "view"}:
            attempts.append(name)
            raise AssertionError("Qt and hardware imports are outside this test")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    return attempts


def _record(root: Path) -> RunEvidence:
    """Build mutable live evidence without a real writer, transfer, or metadata parser."""
    return RunEvidence(
        run_id="run-captured", started_at=_FIXED_DT, finished_at=_FIXED_DT,
        subject_id="123", dataset_roots=(root,), expected={_IMS: 8}, completed={_IMS: 8},
        files=[FileEvidence(f"exaSPIM/{_IMS}", 12, b"captured-hash")],
    )


@pytest.mark.parametrize("kind", ["absent", "none", "wrong-type"])
def test_offer_without_run_record_never_reads_settings_or_imports_qt(
    kind: str, monkeypatch: pytest.MonkeyPatch, import_attempts: list[str]
) -> None:
    """Legacy or invalid acquisitions return before settings or GUI construction."""
    launch = _build_metadata_launch()
    launch.acquisition = SimpleNamespace()
    if kind != "absent":
        launch.acquisition._upload_evidence = None if kind == "none" else object()
    settings = Mock(side_effect=AssertionError("Settings are unnecessary without evidence"))
    monkeypatch.setattr(SubmissionSettings, "from_environment", settings)
    launch._offer_upload()
    settings.assert_not_called()
    assert launch._upload_prompt is None and not import_attempts


@pytest.mark.parametrize("enabled", [None, "0", "true", " 1"])
def test_offer_default_or_disabled_never_snapshots_or_imports_qt(
    tmp_path: Path, enabled: str | None, monkeypatch: pytest.MonkeyPatch,
    import_attempts: list[str],
) -> None:
    """Submission is opt-in even when acquisition evidence is available."""
    launch = _build_metadata_launch()
    run = _record(tmp_path)
    launch.acquisition._upload_evidence = run
    if enabled is None:
        monkeypatch.delenv("EXASPIM_UPLOAD_ENABLED", raising=False)
    else:
        monkeypatch.setenv("EXASPIM_UPLOAD_ENABLED", enabled)
    snapshot = Mock(wraps=run.snapshot)
    monkeypatch.setattr(run, "snapshot", snapshot)
    launch._offer_upload()
    snapshot.assert_not_called()
    assert launch._upload_prompt is None and not import_attempts


def test_offer_injected_controller_receives_one_immutable_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, import_attempts: list[str]
) -> None:
    """Capture once, passing detached values rather than the live acquisition or recorder."""
    launch = _build_metadata_launch()
    run = _record(tmp_path)
    launch.acquisition._upload_evidence = run
    snapshot = Mock(wraps=run.snapshot)
    monkeypatch.setattr(run, "snapshot", snapshot)
    monkeypatch.setenv("EXASPIM_UPLOAD_ENABLED", "1")
    controller = Mock()
    launch._upload_prompt = controller
    launch._offer_upload()
    snapshot.assert_called_once_with()
    controller.offer.assert_called_once()
    captured = controller.offer.call_args.args[0]
    assert isinstance(captured, AcquisitionEvidence)
    assert captured.run_id == "run-captured" and captured.subject_id == "123"
    run.subject_id = "edited in GUI"
    run.expected.clear()
    run.completed.clear()
    run.files.clear()
    assert captured.subject_id == "123" and captured.expected == ((_IMS, 8),)
    assert captured.completed == ((_IMS, 8),) and len(captured.files) == 1
    with pytest.raises(FrozenInstanceError):
        captured.subject_id = "not mutable"
    assert not import_attempts


def test_offer_lazily_constructs_and_reuses_fake_controller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, import_attempts: list[str]
) -> None:
    """Only enabled acquisition evidence constructs the cached controller, once."""
    launch = _build_metadata_launch()
    run = _record(tmp_path)
    launch.acquisition._upload_evidence = run
    settings = SubmissionSettings(enabled=True, path_map=((str(tmp_path), "/allen/x/y"),))
    monkeypatch.setattr(SubmissionSettings, "from_environment", Mock(return_value=settings))
    snapshot = Mock(wraps=run.snapshot)
    monkeypatch.setattr(run, "snapshot", snapshot)
    controller = Mock()
    factory = Mock(return_value=controller)
    module = ModuleType("exaspim_control.upload_prompt")
    module.UploadPromptController = factory
    module._test_controller = True
    monkeypatch.setitem(sys.modules, module.__name__, module)
    launch._offer_upload()
    launch._offer_upload()
    factory.assert_called_once_with(launch.acquisition_view, settings)
    assert launch._upload_prompt is controller
    assert snapshot.call_count == controller.offer.call_count == 2
    assert all(isinstance(c.args[0], AcquisitionEvidence) for c in controller.offer.call_args_list)
    assert import_attempts == [module.__name__]


@pytest.mark.parametrize("phase", ["settings", "construct", "snapshot", "offer"])
def test_offer_errors_are_suppressed_without_retry(
    tmp_path: Path, phase: str, monkeypatch: pytest.MonkeyPatch,
    import_attempts: list[str], caplog: pytest.LogCaptureFixture,
) -> None:
    """Optional evidence/settings/controller failures cannot alter acquisition cleanup."""
    launch = _build_metadata_launch()
    run = _record(tmp_path)
    launch.acquisition._upload_evidence = run
    controller = Mock()
    launch._upload_prompt = controller
    failure = RuntimeError("optional upload failure")
    settings = Mock(return_value=SubmissionSettings(enabled=True))
    snapshot = Mock(wraps=run.snapshot)
    monkeypatch.setattr(SubmissionSettings, "from_environment", settings)
    monkeypatch.setattr(run, "snapshot", snapshot)
    if phase == "settings":
        settings.side_effect = failure
    elif phase == "construct":
        launch._upload_prompt = None
        module = ModuleType("exaspim_control.upload_prompt")
        module.UploadPromptController = Mock(side_effect=failure)
        module._test_controller = True
        monkeypatch.setitem(sys.modules, module.__name__, module)
    elif phase == "snapshot":
        snapshot.side_effect = failure
    else:
        controller.offer.side_effect = failure
    launch._offer_upload()
    assert "Unable to offer upload; no submission was started" in caplog.text
    assert "optional upload failure" in caplog.text
    assert snapshot.call_count == (phase in {"snapshot", "offer"})
    assert controller.offer.call_count == (phase == "offer")
    assert import_attempts == (["exaspim_control.upload_prompt"] if phase == "construct" else [])


@dataclass
class FinalizationCase:
    """Hold finalizer doubles and temporary directories, including a protected local sentinel."""

    launch: metadata.MetadataLaunch
    root: Path
    local: Path
    acquisition_model: MagicMock
    instrument_model: MagicMock
    copy: Mock
    cleanup: Mock
    offer: Mock
    events: list[str]


@pytest.fixture
def finalization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FinalizationCase:
    """Use real layout operations but replace parsing, file copying, and recursive deletion."""
    root = tmp_path / "vast" / "dataset"
    local = tmp_path / "local" / "dataset"
    root.mkdir(parents=True)
    local.mkdir(parents=True)
    (local / "keep.txt").write_text("never delete", encoding="utf-8")
    for name in (_IMS, "overview.tiff", "acquisition_config.yaml", "instrument_config.yaml",
                 "session.log", "notes.txt"):
        (root / name).write_text("temporary artifact", encoding="utf-8")
    (root / "volume.zarr").mkdir()
    (root / "volume.zarr" / "chunk").write_bytes(b"chunk")
    launch = _build_metadata_launch()
    launch.log_filename = "session.log"
    launch.acquisition.file_transfers = {"camera": {"CH639": SimpleNamespace(
        external_path=root.parent, acquisition_name=root.name, local_path=local.parent,
    )}}
    events: list[str] = []
    acquisition_model = MagicMock(coordinate_system=_expected_acquisition().coordinate_system)
    instrument_model = MagicMock()

    def write_acquisition(output_directory: str, prefix: str | None) -> None:
        """Stand in for serialization while preserving the real finalizer's filenames."""
        events.append("acquisition")
        name = "acquisition.json" if prefix is None else f"{prefix}_acquisition.json"
        (Path(output_directory) / name).write_text("{}", encoding="utf-8")

    def write_instrument(output_directory: str, prefix: str | None) -> None:
        """Stand in for serialization independently of the known parse_metadata baseline."""
        events.append("instrument")
        name = "instrument.json" if prefix is None else f"{prefix}_instrument.json"
        (Path(output_directory) / name).write_text("{}", encoding="utf-8")

    acquisition_model.write_standard_file.side_effect = write_acquisition
    instrument_model.write_standard_file.side_effect = write_instrument
    monkeypatch.setattr(launch, "parse_metadata", Mock(return_value=acquisition_model))
    monkeypatch.setattr(launch, "parse_instrument", Mock(return_value=instrument_model))
    copy = Mock(side_effect=lambda *args: events.append("copy"))
    cleanup = Mock(side_effect=lambda *args: events.append("cleanup"))
    offer = Mock(side_effect=lambda: events.append("offer"))
    monkeypatch.setattr(metadata.shutil, "copy", copy)
    monkeypatch.setattr(metadata.shutil, "rmtree", cleanup)
    monkeypatch.setattr(launch, "_offer_upload", offer)
    return FinalizationCase(
        launch, root, local, acquisition_model, instrument_model, copy, cleanup, offer, events,
    )


def test_external_finalization_offers_only_after_successful_tail(
    finalization: FinalizationCase,
) -> None:
    """The hook sees metadata, pending status, and final layout after existing cleanup."""
    case = finalization

    def observe_tail() -> None:
        """Assert ordering at the hook itself, not merely after the finalizer returns."""
        assert case.events == ["acquisition", "instrument", "copy", "cleanup"]
        assert (case.root / "acquisition.json").is_file()
        assert (case.root / "instrument.json").is_file()
        manifest = json.loads((case.root / "processing_manifest.json").read_text(encoding="utf-8"))
        assert manifest["dataset_status"]["status"] == "pending"
        assert manifest["dataset_status"]["status_date"]
        assert manifest["dataset_status"]["status_time"]
        assert {p.name for p in (case.root / "exaSPIM").iterdir()} == {_IMS, "volume.zarr"}
        assert {p.name for p in (case.root / "derivatives").iterdir()} == {
            "overview.tiff", "session.log", "acquisition_config.yaml", "instrument_config.yaml",
        }
        assert (case.root / "notes.txt").is_file()
        assert (case.root / "exaSPIM" / "volume.zarr" / "chunk").read_bytes() == b"chunk"
        case.cleanup.assert_called_once_with(str(case.local))
        case.events.append("offer")

    case.offer.side_effect = observe_tail
    case.launch.finalize_acquisition()
    case.offer.assert_called_once_with()
    assert case.events[-1] == "offer"
    case.acquisition_model.write_standard_file.assert_called_once_with(
        output_directory=str(case.root), prefix=None,
    )
    case.instrument_model.write_standard_file.assert_called_once_with(
        output_directory=str(case.root), prefix=None,
    )
    case.launch.parse_instrument.assert_called_once_with(
        coordinate_system=case.acquisition_model.coordinate_system,
    )
    case.copy.assert_called_once_with("session.log", str(case.root / "session.log"))
    assert (case.local / "keep.txt").read_text(encoding="utf-8") == "never delete"


@pytest.mark.parametrize(
    "phase", ["parse-metadata", "acquisition-write", "parse-instrument", "instrument-write",
              "copy", "manifest", "layout", "rename", "cleanup"],
)
def test_external_finalization_exception_never_reaches_upload_tail(
    finalization: FinalizationCase, phase: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing metadata, filesystem, and cleanup errors propagate without offering upload."""
    case = finalization
    failure = OSError(f"failed during {phase}")
    operations = {
        "parse-metadata": case.launch.parse_metadata,
        "acquisition-write": case.acquisition_model.write_standard_file,
        "parse-instrument": case.launch.parse_instrument,
        "instrument-write": case.instrument_model.write_standard_file,
        "copy": case.copy, "cleanup": case.cleanup,
    }
    if phase in operations:
        operations[phase].side_effect = failure
    elif phase == "manifest":
        monkeypatch.setattr(metadata.json, "dump", Mock(side_effect=failure))
    elif phase == "layout":
        monkeypatch.setattr(metadata.os, "makedirs", Mock(side_effect=failure))
    else:
        monkeypatch.setattr(metadata.os, "rename", Mock(side_effect=failure))
    with pytest.raises(OSError, match=f"failed during {phase}") as caught:
        case.launch.finalize_acquisition()
    assert caught.value is failure
    case.offer.assert_not_called()
    assert (case.local / "keep.txt").read_text(encoding="utf-8") == "never delete"


def test_local_only_finalization_never_offers_or_deletes_local_data(
    finalization: FinalizationCase,
) -> None:
    """The legacy local-only branch still writes prefixed metadata without an upload hook."""
    case = finalization
    case.launch.acquisition.file_transfers = {}
    case.launch.acquisition.writers = {"camera": {"CH639": SimpleNamespace(
        path=case.local.parent, acquisition_name=case.local.name,
    )}}
    for name in (_IMS, "session.log", "acquisition_config.yaml", "instrument_config.yaml"):
        (case.local / name).write_bytes(b"local data")
    case.launch.finalize_acquisition()
    case.offer.assert_not_called()
    case.cleanup.assert_not_called()
    assert case.events == ["acquisition", "instrument", "copy"]
    case.acquisition_model.write_standard_file.assert_has_calls([
        call(output_directory=str(case.local), prefix="exaspim"),
    ])
    case.instrument_model.write_standard_file.assert_called_once_with(
        output_directory=str(case.local), prefix="exaspim",
    )
    assert (case.local / "exaspim_acquisition.json").is_file()
    assert (case.local / "exaspim_instrument.json").is_file()
    assert not (case.local / "processing_manifest.json").exists()
    assert (case.local / "exaSPIM" / _IMS).read_bytes() == b"local data"
    assert (case.local / "derivatives" / "session.log").is_file()
    assert (case.local / "keep.txt").read_text(encoding="utf-8") == "never delete"