"""Exercise submission using temporary datasets and fake children only; never run the CLI."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from unittest.mock import Mock, call

import pytest

from exaspim_control import upload_submission as upload


@dataclass
class SubmissionCase:
    """Collect one isolated dataset and a subprocess double."""

    request: upload.UploadRequest
    settings: upload.SubmissionSettings
    process: Mock
    popen: Mock

    @property
    def receipt(self) -> Path:
        """Return the case's duplicate guard."""
        return upload.receipt_path(self.request)

    @property
    def log(self) -> Path:
        """Return the case's diagnostic log."""
        return self.receipt.with_name("upload_submission.log")

    def submit(self) -> upload.SubmissionResult:
        """Invoke only the helper, with subprocess creation already mocked."""
        return upload.submit_upload(self.request, self.settings)

    def payload(self) -> dict[str, Any]:
        """Read the persisted receipt for assertions."""
        return json.loads(self.receipt.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove operator settings and forbid real children even outside dataset fixtures."""
    for key in (
        "EXASPIM_UPLOAD_ENABLED", "EXASPIM_UPLOAD_PATH_MAP", "EXASPIM_UPLOAD_PYTHON",
        "EXASPIM_UPLOAD_SCRIPT", "EXASPIM_UPLOAD_CWD",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(upload.sys, "platform", "linux")
    monkeypatch.setattr(upload.subprocess, "Popen", Mock(side_effect=AssertionError("Real child")))


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SubmissionCase:
    """Build small canonical fixtures; interpreter and script are never executed."""
    root = tmp_path.resolve() / "vast"
    dataset = root / "exaSPIM_123456_2026-09-10_12-30-45"
    source = dataset / "exaSPIM"
    source.mkdir(parents=True)
    (dataset / "derivatives").mkdir()
    (source / "tile_000000.ims").write_bytes(b"fake imaris data")
    repository = tmp_path / "external repo"
    repository.mkdir()
    interpreter = repository / "dummy python"
    interpreter.write_text("not an executable program", encoding="utf-8")
    interpreter.chmod(0o700)
    script = repository / "dummy script.py"
    script.write_text("not Python; must never execute", encoding="utf-8")
    process = Mock(returncode=None)
    process.wait.return_value = 0
    popen = Mock(return_value=process)
    monkeypatch.setattr(upload.subprocess, "Popen", popen)
    return SubmissionCase(
        request=upload.UploadRequest("run-123", dataset, "123456"),
        settings=upload.SubmissionSettings(
            enabled=True, path_map=((str(root), "/allen/aind/stage/test"),),
            interpreter=interpreter, script=script,
            working_directory=repository,
        ),
        process=process,
        popen=popen,
    )


def _assert_not_started(case: SubmissionCase, result: upload.SubmissionResult) -> None:
    """Check failed preflight leaves neither a process nor submission artifacts."""
    assert result.status == "failed-to-start"
    case.popen.assert_not_called()
    assert not case.receipt.exists()
    assert not case.log.exists()


def test_defaults_and_environment_defaults() -> None:
    """Default paths are exact and no unconfigured environment can enable submission."""
    settings = upload.SubmissionSettings()
    assert settings == upload.SubmissionSettings.from_environment()
    assert settings.enabled is False
    assert settings.path_map == ()
    assert settings.interpreter == Path(
        "/allen/programs/mindscope/workgroups/omfish/carsonb/rocky_miniconda/envs/"
        "exaspim_transformation/bin/python"
    )
    assert settings.working_directory == Path(
        "/home/carson.berry/allen/aind/scratch/carson.berry/aind-exaspim-data-transformation"
    )
    assert settings.script == settings.working_directory / "docs/examples/test_airflow.py"
    assert settings.project_name == "Single Neuron Reconstructions"
    assert settings.timeout_seconds == 120.0


@pytest.mark.parametrize("value", ["0", "true", "True", "yes", " 1", "1 ", "", "2"])
def test_environment_enable_requires_exact_one(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the literal opt-in value enables the unsafe-until-repaired external CLI."""
    monkeypatch.setenv("EXASPIM_UPLOAD_ENABLED", value)
    assert upload.SubmissionSettings.from_environment().enabled is False


def test_environment_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Honor all configured paths without deriving CWD from the script location."""
    monkeypatch.setenv("EXASPIM_UPLOAD_ENABLED", "1")
    values = {
        "EXASPIM_UPLOAD_PYTHON": tmp_path / "environment/bin/python",
        "EXASPIM_UPLOAD_SCRIPT": tmp_path / "elsewhere/nested/submit.py",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.setenv("EXASPIM_UPLOAD_PATH_MAP", r" D:\data = /allen/aind/stage/x ;;Z:\=/allen/z")
    settings = upload.SubmissionSettings.from_environment()
    assert settings.enabled is True
    assert settings.path_map == ((r"D:\data", "/allen/aind/stage/x"), ("Z:\\", "/allen/z"))
    assert settings.interpreter == values["EXASPIM_UPLOAD_PYTHON"]
    assert settings.script == values["EXASPIM_UPLOAD_SCRIPT"]
    assert settings.working_directory == upload.SubmissionSettings().working_directory
    monkeypatch.setenv("EXASPIM_UPLOAD_CWD", str(tmp_path))
    assert upload.SubmissionSettings.from_environment().working_directory == tmp_path


@pytest.mark.parametrize("value", ["", "  ", ";", " = ; "])
def test_blank_environment_path_map_is_empty(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blank mapping entries are ignored rather than mapping the current directory."""
    monkeypatch.setenv("EXASPIM_UPLOAD_PATH_MAP", value)
    assert upload.SubmissionSettings.from_environment().path_map == ()


@pytest.mark.parametrize(
    ("local", "expected"),
    [
        (r"\\allen\aind\stage\exaSPIM\1x\ds", "/allen/aind/stage/exaSPIM/1x/ds"),
        (r"\\ALLEN\aind\stage\ds", "/allen/aind/stage/ds"),
        (r"\\allen.corp\aind\stage\ds", None),
        (r"\\other\aind\stage\ds", None),
        (r"D:\data\ds", None),
        (r"\\allen\aind", None),
    ],
)
def test_linux_path_translates_allen_unc(local: str, expected: str | None) -> None:
    """Only deep \\\\allen shares translate without configuration."""
    if expected is None:
        with pytest.raises(ValueError):
            upload.linux_path(PureWindowsPath(local))
    else:
        assert upload.linux_path(PureWindowsPath(local)) == PurePosixPath(expected)


def test_linux_path_overrides_win_and_reject_bad_entries() -> None:
    """Explicit mappings take precedence; malformed ones fail closed."""
    local = PureWindowsPath(r"\\allen\aind\stage\ds")
    mapped = ((r"\\ALLEN\aind", "/allen/programs/other"),)
    assert upload.linux_path(local, mapped) == PurePosixPath("/allen/programs/other/stage/ds")
    drive = ((r"D:\data", "/allen/aind/stage"),)
    assert upload.linux_path(PureWindowsPath(r"D:\data\x"), drive) == PurePosixPath(
        "/allen/aind/stage/x"
    )
    for bad in ((("", "/allen/a/b"),), ((r"D:\data", "/tmp/a"),)):
        with pytest.raises(ValueError):
            upload.linux_path(PureWindowsPath(r"D:\data\x"), bad)


def test_linux_path_posix_paths() -> None:
    """POSIX /allen paths pass through; others and traversal are rejected."""
    assert upload.linux_path(PurePosixPath("/allen/a/b/c")) == PurePosixPath("/allen/a/b/c")
    for bad in ("/tmp/a/b/c", "/allen/a/../c/d", "relative/a/b"):
        with pytest.raises(ValueError):
            upload.linux_path(PurePosixPath(bad))


def test_value_objects_and_paths_are_immutable(case: SubmissionCase) -> None:
    """Captured inputs and returned outcomes cannot be retargeted in place."""
    assert case.request.source == case.request.dataset_root / "exaSPIM"
    assert case.receipt == case.request.dataset_root / "derivatives/upload_submission.json"
    for instance, name, value in (
        (case.request, "subject_id", "changed"),
        (case.settings, "enabled", False),
        (upload.SubmissionResult("accepted", "message"), "status", "unknown"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(instance, name, value)


def test_disabled_performs_no_preflight_or_writes(
    case: SubmissionCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default-off returns before even looking at potentially invalid filesystem paths."""
    preflight = Mock(side_effect=AssertionError("Preflight must not run"))
    monkeypatch.setattr(upload, "_preflight", preflight)
    case.settings = replace(case.settings, enabled=False)
    result = case.submit()
    assert result.status == "disabled"
    preflight.assert_not_called()
    case.popen.assert_not_called()
    assert not case.receipt.exists()
    assert not case.log.exists()


def test_accepted_argv_receipt_and_parent_log_closure(case: SubmissionCase) -> None:
    """Pass exact captured arguments, all tiles, and detached file-backed subprocess IO."""
    case.request = replace(case.request, subject_id="subject with spaces; $(ignored)")
    case.settings = replace(case.settings, timeout_seconds=12.5)
    (case.request.source / "nested").mkdir()
    (case.request.source / "nested/tile_000001.ims").write_bytes(b"second tile")
    (case.request.source / "notes.txt").write_text("ignored", encoding="utf-8")
    case.log.write_bytes(b"existing diagnostic\n")

    def spawn(argv: list[str], **kwargs: Any) -> Mock:
        """Observe that the durable consent guard precedes the fake process launch."""
        assert case.payload()["state"] == "submitting"
        assert case.payload()["exit_code"] is None
        assert argv == [
            str(case.settings.interpreter), str(case.settings.script), str(case.request.source),
            "--project-name", "Single Neuron Reconstructions",
            "--subject-id", "subject with spaces; $(ignored)",
        ]
        assert "--single-tile" not in argv
        assert kwargs == {
            "cwd": str(case.settings.working_directory), "shell": False,
            "start_new_session": True, "stdin": subprocess.DEVNULL,
            "stdout": kwargs["stdout"], "stderr": kwargs["stdout"], "close_fds": True,
        }
        assert not kwargs["stdout"].closed
        kwargs["stdout"].write(b"fake stdout and stderr\n")
        assert case.submit().status == "duplicate"
        return case.process

    def wait(timeout: float) -> int:
        """Require the parent's descriptor to close before the synchronous worker wait."""
        assert timeout == 12.5
        assert case.popen.call_args.kwargs["stdout"].closed
        return 0

    case.popen.side_effect = spawn
    case.process.wait.side_effect = wait
    result = case.submit()
    assert result.status == "accepted"
    assert "upload is not complete" in result.message
    assert str(case.log) in result.message
    assert case.log.read_bytes() == b"existing diagnostic\nfake stdout and stderr\n"
    payload = case.payload()
    assert set(payload) == {
        "run_id", "source", "linux_source", "subject_id", "project_name", "timestamp",
        "state", "exit_code",
    }
    assert payload["run_id"] == case.request.run_id
    assert payload["source"] == str(case.request.source)
    assert payload["linux_source"] == (
        "/allen/aind/stage/test/exaSPIM_123456_2026-09-10_12-30-45/exaSPIM"
    )
    assert payload["subject_id"] == case.request.subject_id
    assert payload["project_name"] == case.settings.project_name
    assert payload["state"] == "accepted"
    assert payload["exit_code"] == 0
    assert datetime.fromisoformat(payload["timestamp"]).utcoffset().total_seconds() == 0
    case.popen.assert_called_once()
    case.process.wait.assert_called_once_with(timeout=12.5)
    case.process.terminate.assert_not_called()
    case.process.kill.assert_not_called()
    assert sorted(path.name for path in case.receipt.parent.iterdir()) == [
        "upload_submission.json", "upload_submission.log",
    ]


def test_project_override_is_passed_unchanged(case: SubmissionCase) -> None:
    """Explicit injection supports other project names without shell interpolation."""
    case.settings = replace(case.settings, project_name="Project 'two' ; $literal")
    assert case.submit().status == "accepted"
    assert case.popen.call_args.args[0][4] == case.settings.project_name
    assert case.payload()["project_name"] == case.settings.project_name


def test_unsupported_platform_is_rejected(
    case: SubmissionCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No remote launcher or alternate-platform fallback is attempted."""
    monkeypatch.setattr(upload.sys, "platform", "darwin")
    _assert_not_started(case, case.submit())


def test_windows_launch_uses_detached_creation_flags(
    case: SubmissionCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows children get their own hidden process group instead of a POSIX session."""
    monkeypatch.setattr(upload.sys, "platform", "win32")
    assert case.submit().status == "accepted"
    kwargs = case.popen.call_args.kwargs
    assert "start_new_session" not in kwargs
    assert kwargs["creationflags"] == 0x200 | 0x08000000


@pytest.mark.parametrize("kind", ["unset", "missing-prefix", "bad-target", "other"])
def test_invalid_path_maps(case: SubmissionCase, tmp_path: Path, kind: str) -> None:
    """Datasets that cannot be translated onto an /allen share are never submitted."""
    maps = {
        "unset": (),
        "missing-prefix": (("", "/allen/aind/stage"),),
        "bad-target": ((str(case.request.dataset_root.parent), "/tmp/stage"),),
        "other": ((str(tmp_path / "elsewhere"), "/allen/aind/stage"),),
    }
    case.settings = replace(case.settings, path_map=maps[kind])
    _assert_not_started(case, case.submit())


@pytest.mark.parametrize("kind", ["missing", "relative", "file", "outside", "prefix", "traversal"])
def test_invalid_dataset_paths(case: SubmissionCase, tmp_path: Path, kind: str) -> None:
    """Reject missing paths, lexical prefix collisions, and noncanonical traversal."""
    outside = tmp_path / "outside_2026-09-10_12-30-45"
    outside.mkdir()
    prefix = tmp_path / "vast-other/exaSPIM_123456_2026-09-10_12-30-45"
    prefix.mkdir(parents=True)
    paths = {
        "missing": case.request.dataset_root.parent / "missing_2026-09-10_12-30-45",
        "relative": Path("relative_2026-09-10_12-30-45"),
        "file": case.settings.script,
        "outside": outside,
        "prefix": prefix,
        "traversal": case.request.dataset_root / ".." / case.request.dataset_root.name,
    }
    case.request = replace(case.request, dataset_root=paths[kind])
    _assert_not_started(case, case.submit())


@pytest.mark.parametrize("component", ["root", "dataset", "source", "derivatives"])
def test_symlink_directory_aliases_fail_closed(
    case: SubmissionCase, tmp_path: Path, component: str
) -> None:
    """Do not silently canonicalize the consented path or allow escaping aliases."""
    if component == "root":
        alias = tmp_path / "root-alias"
        alias.symlink_to(case.request.dataset_root.parent, target_is_directory=True)
        case.settings = replace(case.settings, path_map=((str(alias), "/allen/aind/stage/test"),))
    elif component == "dataset":
        alias = case.request.dataset_root.with_name("alias_2026-09-10_12-30-45")
        alias.symlink_to(case.request.dataset_root, target_is_directory=True)
        case.request = replace(case.request, dataset_root=alias)
    else:
        directory = case.request.source if component == "source" else case.receipt.parent
        moved = tmp_path / component
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    _assert_not_started(case, case.submit())


@pytest.mark.parametrize("component", ["exaSPIM", "derivatives"])
@pytest.mark.parametrize("kind", ["missing", "file"])
def test_required_directories_are_not_created(
    case: SubmissionCase, tmp_path: Path, component: str, kind: str
) -> None:
    """Do not repair missing finalization output or create arbitrary dataset layouts."""
    path = case.request.dataset_root / component
    path.rename(tmp_path / component)
    if kind == "file":
        path.write_text("not a directory", encoding="utf-8")
    _assert_not_started(case, case.submit())


@pytest.mark.parametrize("field", ["run_id", "subject_id", "project_name"])
@pytest.mark.parametrize("value", ["", " \t", "embedded\x00value", None, 42])
def test_invalid_identity_values(case: SubmissionCase, field: str, value: Any) -> None:
    """Require explicit, nonblank string identity and project values."""
    if field == "project_name":
        case.settings = replace(case.settings, **{field: value})
    else:
        case.request = replace(case.request, **{field: value})
    _assert_not_started(case, case.submit())


@pytest.mark.parametrize("suffix", ["no-timestamp", "2026-02-30_12-00-00", "2026-09-10_25-00-00"])
def test_invalid_timestamp(case: SubmissionCase, suffix: str) -> None:
    """A real parseable CLI timestamp must occur in this dataset's name."""
    new_root = case.request.dataset_root.with_name(f"exaSPIM_123456_{suffix}")
    case.request.dataset_root.rename(new_root)
    case.request = replace(case.request, dataset_root=new_root)
    _assert_not_started(case, case.submit())


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("inf"), float("nan"), "120"])
def test_invalid_timeout(case: SubmissionCase, timeout: Any) -> None:
    """Do not launch with an invalid or unbounded submission wait."""
    case.settings = replace(case.settings, timeout_seconds=timeout)
    _assert_not_started(case, case.submit())


@pytest.mark.parametrize("kind", ["empty", "zero", "directory", "fifo"])
def test_invalid_ims_inputs(case: SubmissionCase, kind: str) -> None:
    """Require nonempty regular IMS data, not filenames alone."""
    tile = case.request.source / "tile_000000.ims"
    tile.unlink()
    if kind == "zero":
        tile.touch()
    elif kind == "directory":
        tile.mkdir()
    elif kind == "fifo":
        os.mkfifo(tile)
    _assert_not_started(case, case.submit())


@pytest.mark.parametrize("kind", ["file", "directory", "internal", "dangling", "loop"])
def test_source_symlinks_are_rejected(case: SubmissionCase, tmp_path: Path, kind: str) -> None:
    """Reject external escapes, internal aliases, broken links, and loops recursively."""
    external = tmp_path / "other.ims"
    external.write_bytes(b"outside data")
    targets = {
        "file": external,
        "directory": tmp_path,
        "internal": case.request.source / "tile_000000.ims",
        "dangling": tmp_path / "missing.ims",
        "loop": case.request.source / "linked.ims",
    }
    (case.request.source / "linked.ims").symlink_to(targets[kind])
    _assert_not_started(case, case.submit())


def test_unreadable_recursive_directory_fails_closed(
    case: SubmissionCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable subtree must not silently omit potentially acquired tiles."""
    original = upload.os.scandir

    def scandir(path: Any) -> Any:
        """Simulate traversal permission failure only for this temporary source."""
        if Path(path) == case.request.source:
            raise PermissionError("unreadable")
        return original(path)

    monkeypatch.setattr(upload.os, "scandir", scandir)
    _assert_not_started(case, case.submit())


@pytest.mark.parametrize("field", ["interpreter", "script", "working_directory"])
@pytest.mark.parametrize("kind", ["missing", "relative", "wrong-type"])
def test_invalid_launch_paths(case: SubmissionCase, field: str, kind: str) -> None:
    """Require explicit local paths instead of PATH lookup or interpreter fallback."""
    wrong_type = case.settings.script if field == "working_directory" else case.request.source
    paths = {
        "missing": case.request.dataset_root / "missing",
        "relative": Path("relative"),
        "wrong-type": wrong_type,
    }
    case.settings = replace(case.settings, **{field: paths[kind]})
    _assert_not_started(case, case.submit())


@pytest.mark.parametrize("field", ["interpreter", "script"])
def test_missing_launch_permissions(
    case: SubmissionCase, field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate denied permissions reliably even when tests run as root."""
    denied = getattr(case.settings, field)
    original = upload.os.access
    monkeypatch.setattr(
        upload.os, "access", lambda path, mode: path != denied and original(path, mode)
    )
    _assert_not_started(case, case.submit())


def test_invalid_runtime_request_returns_error(case: SubmissionCase) -> None:
    """Malformed injected values cannot leak exceptions into a background controller."""
    case.request = replace(case.request, dataset_root=None)
    result = case.submit()
    assert result.status == "failed-to-start"
    assert "Invalid request" in result.message
    case.popen.assert_not_called()


@pytest.mark.parametrize(
    "content",
    ["", "broken JSON", "null", "[]"] + [
        json.dumps({"state": state})
        for state in ("submitting", "accepted", "unknown", "failed-to-start", "other")
    ],
)
def test_every_existing_receipt_blocks_submission(case: SubmissionCase, content: str) -> None:
    """Never parse, reset, or override a prior attempt, including an incomplete receipt."""
    case.receipt.write_text(content, encoding="utf-8")
    case.settings = replace(case.settings, interpreter=Path("missing"))
    result = case.submit()
    assert result.status == "duplicate"
    assert str(case.log) in result.message
    assert case.receipt.read_text(encoding="utf-8") == content
    assert not case.log.exists()
    case.popen.assert_not_called()


@pytest.mark.parametrize("kind", ["directory", "symlink", "dangling"])
def test_nonregular_receipt_also_blocks(
    case: SubmissionCase, tmp_path: Path, kind: str
) -> None:
    """Existing directories and symlinks must never evade the duplicate guard."""
    if kind == "directory":
        case.receipt.mkdir()
    else:
        target = tmp_path / "other-receipt"
        if kind == "symlink":
            target.write_text("existing", encoding="utf-8")
        case.receipt.symlink_to(target)
    assert case.submit().status == "duplicate"
    case.popen.assert_not_called()
    assert not case.log.exists()


def test_exclusive_receipt_handles_preflight_race(
    case: SubmissionCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A competing process winning after preflight still prevents a second launch."""
    case.receipt.write_text("other process", encoding="utf-8")
    monkeypatch.setattr(upload.os.path, "lexists", lambda path: False)
    assert case.submit().status == "duplicate"
    assert case.receipt.read_text(encoding="utf-8") == "other process"
    case.popen.assert_not_called()


@pytest.mark.parametrize("exit_code", [1, 2, -9])
def test_nonzero_exit_is_unknown_and_never_retried(case: SubmissionCase, exit_code: int) -> None:
    """A CLI can fail after a successful POST, so a nonzero exit is not rejection."""
    case.process.wait.return_value = exit_code
    result = case.submit()
    assert result.status == "unknown"
    assert "may already have submitted" in result.message
    assert str(case.log) in result.message
    assert case.payload()["state"] == "unknown"
    assert case.payload()["exit_code"] == exit_code
    assert case.submit().status == "duplicate"
    case.popen.assert_called_once()


@pytest.mark.parametrize("error", [OSError("secret-token"), ValueError("secret-token")])
def test_spawn_failure_records_failed_to_start(case: SubmissionCase, error: Exception) -> None:
    """Keep the guard on spawn failure and avoid copying arbitrary exception secrets."""
    case.popen.side_effect = error
    result = case.submit()
    assert result.status == "failed-to-start"
    assert "secret-token" not in result.message
    assert str(case.log) in result.message
    assert case.payload()["state"] == "failed-to-start"
    assert case.payload()["exit_code"] is None
    assert case.popen.call_args.kwargs["stdout"].closed
    case.process.wait.assert_not_called()
    assert case.submit().status == "duplicate"
    case.popen.assert_called_once()


@pytest.mark.parametrize("needs_kill", [False, True])
def test_timeout_stops_only_child_and_records_unknown(
    case: SubmissionCase, needs_kill: bool
) -> None:
    """Bound the worker wait, terminate then kill if needed, and always reap the child."""
    expired = subprocess.TimeoutExpired("fake CLI", 120.0)
    code = -9 if needs_kill else -15
    case.process.wait.side_effect = [expired, expired, code] if needs_kill else [expired, code]
    result = case.submit()
    assert result.status == "unknown"
    assert "timed out" in result.message
    assert str(case.log) in result.message
    expected = [call.wait(timeout=120.0), call.terminate(), call.wait(timeout=5.0)]
    if needs_kill:
        expected.extend([call.kill(), call.wait()])
    assert case.process.mock_calls == expected
    assert case.payload()["state"] == "unknown"
    assert case.payload()["exit_code"] == code
    assert case.submit().status == "duplicate"
    case.popen.assert_called_once()


@pytest.mark.parametrize("phase", ["terminate", "kill"])
def test_timeout_exit_race_is_reaped(case: SubmissionCase, phase: str) -> None:
    """The child exiting just before a signal does not remove the need to reap it."""
    expired = subprocess.TimeoutExpired("fake CLI", 120)
    case.process.wait.side_effect = [expired, expired, 0] if phase == "kill" else [expired, 0]
    getattr(case.process, phase).side_effect = ProcessLookupError("already exited")
    assert case.submit().status == "unknown"
    assert case.payload()["exit_code"] == 0


@pytest.mark.parametrize("phase", ["terminate", "kill", "grace-wait", "final-wait"])
def test_timeout_cleanup_errors_are_unknown(case: SubmissionCase, phase: str) -> None:
    """Signal or reaping errors never imply that a remote job was cancelled."""
    expired = subprocess.TimeoutExpired("fake CLI", 120)
    failure = OSError("cleanup failed")
    case.process.wait.side_effect = [expired, expired, failure]
    if phase in ("terminate", "kill"):
        getattr(case.process, phase).side_effect = failure
    elif phase == "grace-wait":
        case.process.wait.side_effect = [expired, failure]
    result = case.submit()
    assert result.status == "unknown"
    assert "cleanup failed" in result.message
    assert case.payload()["state"] == "unknown"
    assert case.payload()["exit_code"] is None


def test_wait_error_returns_unknown(case: SubmissionCase) -> None:
    """Unexpected local monitoring failure cannot be reported as a failed submission."""
    case.process.wait.side_effect = OSError("unavailable")
    result = case.submit()
    assert result.status == "unknown"
    assert "Cannot determine child outcome" in result.message
    assert case.payload()["state"] == "unknown"
    case.process.terminate.assert_not_called()


def test_log_open_failure_does_not_claim_or_spawn(
    case: SubmissionCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unwritable diagnostics must prevent any submission or receipt creation."""
    monkeypatch.setattr(upload.os, "open", Mock(side_effect=PermissionError("denied")))
    _assert_not_started(case, case.submit())


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo"])
def test_unsafe_log_targets_are_rejected(case: SubmissionCase, tmp_path: Path, kind: str) -> None:
    """Never follow a log symlink or block opening a special file."""
    target = tmp_path / "untouched"
    target.write_bytes(b"keep")
    if kind == "symlink":
        case.log.symlink_to(target)
    elif kind == "directory":
        case.log.mkdir()
    else:
        os.mkfifo(case.log)
    assert case.submit().status == "failed-to-start"
    assert not case.receipt.exists()
    assert target.read_bytes() == b"keep"
    case.popen.assert_not_called()


@pytest.mark.parametrize("failure", ["nonregular", "fdopen"])
def test_log_descriptor_is_closed_on_validation_error(
    case: SubmissionCase, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No raw descriptor leaks if wrapping or validating the log fails."""
    close = Mock(wraps=upload.os.close)
    monkeypatch.setattr(upload.os, "close", close)
    if failure == "nonregular":
        monkeypatch.setattr(upload.stat, "S_ISREG", lambda mode: False)
    else:
        monkeypatch.setattr(upload.os, "fdopen", Mock(side_effect=OSError("wrapping failed")))
    assert case.submit().status == "failed-to-start"
    assert not case.receipt.exists()
    close.assert_called_once()
    with pytest.raises(OSError):
        os.fstat(close.call_args.args[0])
    case.popen.assert_not_called()


def test_receipt_open_failure_never_spawns(
    case: SubmissionCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use exclusive creation and stop before spawning if it is denied."""
    original = Path.open

    def open_path(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        """Fail only the exclusive receipt claim, not subsequent assertions."""
        if path == case.receipt and mode == "x":
            raise PermissionError("receipt denied")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_path)
    result = case.submit()
    assert result.status == "failed-to-start"
    assert not case.receipt.exists()
    case.popen.assert_not_called()


@pytest.mark.parametrize("phase", ["dump", "fsync"])
def test_initial_receipt_write_failure_never_spawns(
    case: SubmissionCase, phase: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partially written claim is retained and finalized without launching a child."""
    if phase == "dump":
        original = upload.json.dump

        def dump(payload: Any, stream: Any, **kwargs: Any) -> None:
            """Break the initial write, allowing its atomic failed-to-start update."""
            if Path(stream.name) == case.receipt:
                stream.write("partial")
                raise OSError("initial write failed")
            original(payload, stream, **kwargs)

        monkeypatch.setattr(upload.json, "dump", dump)
    else:
        monkeypatch.setattr(upload.os, "fsync", Mock(side_effect=[OSError("sync failed"), None]))
    assert case.submit().status == "failed-to-start"
    assert case.payload()["state"] == "failed-to-start"
    case.popen.assert_not_called()


def test_log_close_error_after_spawn_is_unknown(
    case: SubmissionCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure closing the parent's descriptor must not imply the child never started."""
    stream = Mock()
    stream.__enter__ = Mock(return_value=stream)
    stream.__exit__ = Mock(side_effect=OSError("close failed"))
    monkeypatch.setattr(upload, "_open_log", Mock(return_value=stream))
    result = case.submit()
    assert result.status == "unknown"
    assert "may have started" in result.message
    assert case.payload()["state"] == "unknown"
    assert case.payload()["exit_code"] == 0
    case.popen.assert_called_once()
    case.process.wait.assert_called_once_with(timeout=120.0)


def test_final_receipt_is_atomically_replaced(
    case: SubmissionCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Readers see the full initial or full final receipt, not an in-place rewrite."""
    original = upload.os.replace
    seen = []

    def replace_receipt(source: Path, destination: Path) -> None:
        """Inspect both files at the only state-changing replacement boundary."""
        assert destination == case.receipt
        assert source != destination
        assert source.parent == destination.parent
        assert source.name.startswith(".upload_submission.json.")
        assert case.payload()["state"] == "submitting"
        final = json.loads(source.read_text(encoding="utf-8"))
        assert final == {**case.payload(), "state": "accepted", "exit_code": 0}
        seen.append(source)
        original(source, destination)

    monkeypatch.setattr(upload.os, "replace", replace_receipt)
    assert case.submit().status == "accepted"
    assert len(seen) == 1
    assert not seen[0].exists()


@pytest.mark.parametrize("phase", ["temporary", "dump", "fsync", "replace"])
def test_final_receipt_write_failure_retains_initial_guard(
    case: SubmissionCase, phase: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If recording acceptance fails, report unknown and never destroy the original guard."""
    if phase == "temporary":
        monkeypatch.setattr(
            upload.tempfile, "NamedTemporaryFile", Mock(side_effect=OSError("temp denied"))
        )
    elif phase == "dump":
        original = upload.json.dump

        def dump(payload: Any, stream: Any, **kwargs: Any) -> None:
            """Only the unique temporary receipt experiences a simulated write failure."""
            if Path(stream.name) != case.receipt:
                stream.write("partial")
                raise OSError("final write failed")
            original(payload, stream, **kwargs)

        monkeypatch.setattr(upload.json, "dump", dump)
    elif phase == "fsync":
        monkeypatch.setattr(upload.os, "fsync", Mock(side_effect=[None, OSError("sync failed")]))
    else:
        monkeypatch.setattr(upload.os, "replace", Mock(side_effect=OSError("replace failed")))
    result = case.submit()
    assert result.status == "unknown"
    assert "submission may have occurred" in result.message
    assert "Final receipt update failed" in result.message
    assert str(case.log) in result.message
    assert case.payload()["state"] == "submitting"
    assert case.payload()["exit_code"] is None
    assert not list(case.receipt.parent.glob(".upload_submission.json.*"))
    assert case.submit().status == "duplicate"
    case.popen.assert_called_once()


def test_failed_temporary_cleanup_does_not_remove_guard_or_data(
    case: SubmissionCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unremovable temporary receipt never causes acquisition data deletion."""
    monkeypatch.setattr(upload.os, "replace", Mock(side_effect=OSError("replace failed")))
    unlink = Mock(side_effect=PermissionError("cleanup denied"))
    monkeypatch.setattr(Path, "unlink", unlink)
    result = case.submit()
    assert result.status == "unknown"
    assert case.payload()["state"] == "submitting"
    assert (case.request.source / "tile_000000.ims").read_bytes() == b"fake imaris data"
    assert len(list(case.receipt.parent.glob(".upload_submission.json.*"))) == 1
    unlink.assert_called_once_with(missing_ok=True)