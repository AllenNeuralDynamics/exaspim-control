"""Run existing lifecycle methods in isolation without importing microscope SDKs.

Only method ASTs are loaded: production method bodies are executed unchanged with
fake devices. Full engine coverage requires microscope integration testing; these
tests cover the added observations and signal ordering, not the hardware engine.
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Callable
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from exaspim_control.acquisition_completion import RunEvidence

SOURCE = Path(__file__).resolve().parents[1] / "src" / "exaspim_control"


def _method(filename: str, name: str, **namespace: Any) -> Callable:
    """Compile the saved method, not an editor buffer or copied implementation."""
    tree = ast.parse((SOURCE / filename).read_text())
    method = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == name)
    module = ast.Module(body=[method], type_ignores=[])
    # Only trusted repository method ASTs are executed, with fake device dependencies.
    exec(compile(module, str(SOURCE / filename), "exec"), namespace)  # noqa: S102
    return namespace[name]


def test_new_run_resets_success_before_preflight_failure() -> None:
    run = _method("exa_spim_acquisition.py", "run", RunEvidence=RunEvidence)
    previous = RunEvidence()
    previous.finish({})
    acquisition = SimpleNamespace(
        _upload_evidence=previous, stop_engine=Event(),
        _verify_acquisition=Mock(side_effect=ValueError("preflight")),
    )
    with pytest.raises(ValueError, match="preflight"):
        run(acquisition)
    assert acquisition._upload_evidence.run_id != previous.run_id
    assert acquisition._upload_evidence.finished_at is None


def test_stop_observation_is_sticky_after_engine_cleanup() -> None:
    stop = _method("exa_spim_acquisition.py", "stop_acquisition")
    acquisition = SimpleNamespace(
        _upload_evidence=RunEvidence(), stop_engine=Event(), log=Mock(),
    )
    stop(acquisition)
    assert acquisition.stop_engine.is_set()
    acquisition.stop_engine.clear()
    assert acquisition._upload_evidence.cancelled


def _engine() -> tuple[Callable, SimpleNamespace, list[str]]:
    """Minimal single-frame engine fixture; no shared memory or real devices."""
    events = []
    buffer = Mock()
    buffer.close_and_unlink.side_effect = lambda: events.append("buffer-cleanup")
    engine = _method(
        "exa_spim_acquisition.py", "acquisition_engine", Lock=Lock,
        SharedDoubleBuffer=Mock(return_value=buffer), time=Mock(),
        virtual_memory=lambda: SimpleNamespace(used=0),
    )
    writer = Mock(chunk_count_px=1)
    writer._log_queue.empty.return_value = True
    writer.done_reading.is_set.return_value = True
    writer.wait_to_finish.side_effect = lambda: events.append("writer-closed")
    camera = Mock(image_height_px=1, image_width_px=1)
    daq = Mock(co_frequency_hz=1)
    acquisition = SimpleNamespace(
        stop_engine=Event(), camera=camera, writer=writer, daq=daq,
        scanning_stage=Mock(), log=logging.getLogger(__name__),
        instrument=SimpleNamespace(
            channels={"488": {"lasers": ["laser"]}},
            lasers={"laser": SimpleNamespace(id="laser", power_mw=0, temperature_c=0)},
        ),
        _upload_evidence=Mock(),
    )
    acquisition._upload_evidence.record_tile.side_effect = lambda *args: events.append("record")
    return engine, acquisition, events


@pytest.mark.parametrize("state", ["success", "writer-error", "cancelled"])
def test_engine_records_only_closed_successful_tile(state: str) -> None:
    engine, acquisition, events = _engine()
    if state == "cancelled":
        acquisition.stop_engine.set()
    if state == "writer-error":
        acquisition.writer.wait_to_finish.side_effect = RuntimeError("writer")
    arguments = (
        acquisition, {"steps": 1, "channel": "488"}, "tile", acquisition.camera,
        acquisition.daq, acquisition.writer, {}, acquisition.scanning_stage,
    )
    if state == "writer-error":
        with pytest.raises(RuntimeError, match="writer"):
            engine(*arguments)
    else:
        engine(*arguments)
    if state == "success":
        acquisition._upload_evidence.record_tile.assert_called_once_with(
            "tile", 1, acquisition.writer,
        )
        assert events == ["writer-closed", "record", "buffer-cleanup"]
    else:
        acquisition._upload_evidence.record_tile.assert_not_called()


def test_run_observation_order_surrounds_existing_transfer_lifecycle() -> None:
    tree = ast.parse((SOURCE / "exa_spim_acquisition.py").read_text())
    run = next(node for node in ast.walk(tree)
               if isinstance(node, ast.FunctionDef) and node.name == "run")
    calls = {ast.unparse(node.func): node.lineno for node in ast.walk(run)
             if isinstance(node, ast.Call)}
    assert calls["self._set_acquisition_name"] < calls["self._upload_evidence.configure"]
    assert calls["self._upload_evidence.configure"] < calls["self.acquisition_engine"]
    assert calls["self.acquisition_engine"] < calls[
        "file_transfer_threads[tile_num][tile_channel][repeat].start"
    ]
    assert calls["thread.wait_until_finished"] < calls["self._upload_evidence.finish"]
    assert calls["self.indicator_light.disable"] < calls["self._upload_evidence.finish"]
    assert isinstance(run.body[-1], ast.Expr)
    assert ast.unparse(run.body[-1].value.func) == "self._upload_evidence.finish"


def test_gui_connects_completion_and_captures_start_before_worker_starts() -> None:
    tree = ast.parse((SOURCE / "exa_spim_view.py").read_text())
    start = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name == "start_acquisition")
    calls = {ast.unparse(node.func): node.lineno for node in ast.walk(start)
             if isinstance(node, ast.Call)}
    assert calls["self.acquisition_thread.finished.connect"] < calls[
        "self.acquisition_thread.start"
    ]
    assert calls["self.acquisitionStarted.emit"] < calls["self.acquisition_thread.start"]