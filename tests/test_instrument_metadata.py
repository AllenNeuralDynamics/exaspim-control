"""Tests for :mod:`exaspim_control.instrument_metadata`.

Unit tests exercise the device-mapping dispatch with a mocked ExASPIM instrument loaded
from the canonical ``tests/resources/instrument_config.yaml``. The integration test
writes a real ``instrument.json`` to ``tests/output/`` for manual review.
"""

import json
import unittest
from datetime import date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import yaml

from aind_data_schema.components.devices import (
    Camera,
    DAQDevice,
    Device,
    Laser,
    MotorizedStage,
    Objective,
    ScanningStage,
)
from aind_data_schema.core.instrument import Instrument
from aind_data_schema_models.modalities import Modality
from aind_data_schema_models.organizations import Organization

from exaspim_control.instrument_metadata import (
    _coerce_date,
    _resolve_organization,
    _walk_devices,
    build_instrument,
)


_FIXTURE_YAML = Path(__file__).parent / "resources" / "instrument_config.yaml"


def _load_yaml_config() -> dict[str, Any]:
    """Read the canonical instrument YAML fixture."""
    with open(_FIXTURE_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_metadata(**overrides: Any) -> MagicMock:
    """Build a metadata mock that exposes the attrs ``build_instrument`` needs."""
    meta = MagicMock()
    defaults = {
        "instrument_id": "exaspim-1x",
        "modification_date": date(2024, 6, 1),
        "x_anatomical_direction": "Anterior to Posterior",
        "y_anatomical_direction": "Inferior to Superior",
        "z_anatomical_direction": "Left to Right",
        "location": None,
        "temperature_control": None,
        "notes": None,
    }
    defaults.update(overrides)
    meta.configure_mock(**defaults)
    return meta


def _build_instrument_mock(config: dict[str, Any]) -> MagicMock:
    """Wrap the YAML config in a mocked ExASPIM exposing realistic device dicts.

    Each device dict is keyed by the device name. Live device attrs (``wavelength``,
    ``sensor_width_px``, etc.) are taken from the YAML ``init``/``properties`` blocks
    so the unit tests mirror what the real ExASPIM would expose.
    """
    devices = config["instrument"]["devices"]
    lasers, cameras, scanning, tiling, focusing, daqs, flips, indicators = (
        {},
        {},
        {},
        {},
        {},
        {},
        {},
        {},
    )

    def _device_from(spec: dict[str, Any]) -> MagicMock:
        device = MagicMock()
        init = spec.get("init") or {}
        properties = spec.get("properties") or {}
        # Surface common voxel-style attributes when present.
        for source in (init, properties):
            for key, value in source.items():
                if isinstance(value, (int, float, str, bool)):
                    setattr(device, key, value)
        return device

    for name, spec in devices.items():
        voxel_type = (spec or {}).get("type")
        if voxel_type == "camera":
            cameras[name] = _device_from(spec)
        elif voxel_type == "flip_mount":
            flips[name] = _device_from(spec)
        elif voxel_type == "daq":
            daqs[name] = _device_from(spec)
        elif voxel_type == "indicator_light":
            indicators[name] = _device_from(spec)
        # Sub-devices nested under controllers.
        for sub_name, sub_spec in (spec.get("subdevices") or {}).items():
            sub_type = (sub_spec or {}).get("type")
            if sub_type == "laser":
                lasers[sub_name] = _device_from(sub_spec)
            elif sub_type == "scanning_stage":
                scanning[sub_name] = _device_from(sub_spec)
            elif sub_type == "tiling_stage":
                tiling[sub_name] = _device_from(sub_spec)
            elif sub_type == "focusing_stage":
                focusing[sub_name] = _device_from(sub_spec)

    instrument = MagicMock()
    instrument.config = config
    instrument.lasers = lasers
    instrument.cameras = cameras
    instrument.scanning_stages = scanning
    instrument.tiling_stages = tiling
    instrument.focusing_stages = focusing
    instrument.daqs = daqs
    instrument.flip_mounts = flips
    instrument.indicator_lights = indicators
    return instrument


class WalkDevicesTests(unittest.TestCase):
    """Tests for :func:`_walk_devices`."""

    def test_walks_top_level_and_subdevices(self):
        """Both the top-level device and each entry under ``subdevices`` are yielded."""
        devices = {
            "ctrl": {
                "type": "controller",
                "subdevices": {
                    "L1": {"type": "laser"},
                    "L2": {"type": "laser"},
                },
            },
            "cam": {"type": "camera"},
        }
        names = [name for name, _, _ in _walk_devices(devices)]
        self.assertEqual(names, ["ctrl", "L1", "L2", "cam"])


class ResolveOrganizationTests(unittest.TestCase):
    """Tests for :func:`_resolve_organization`."""

    def test_known_vendor_substring(self):
        """Driver paths containing a known vendor token resolve to the matching Organization."""
        self.assertEqual(
            _resolve_organization("voxel.devices.laser.oxxius.lbx"),
            Organization.from_name("Oxxius"),
        )

    def test_unknown_returns_other(self):
        """Unknown strings fall back to ``Organization.OTHER``."""
        self.assertEqual(_resolve_organization("voxel.devices.misc.acme"), Organization.OTHER)

    def test_empty_returns_other(self):
        """Empty/``None`` inputs fall back to ``Organization.OTHER``."""
        self.assertEqual(_resolve_organization(None), Organization.OTHER)
        self.assertEqual(_resolve_organization(""), Organization.OTHER)


class CoerceDateTests(unittest.TestCase):
    """Tests for :func:`_coerce_date`."""

    def test_passes_through_date(self):
        self.assertEqual(_coerce_date(date(2025, 3, 14)), date(2025, 3, 14))

    def test_datetime_truncates_to_date(self):
        self.assertEqual(_coerce_date(datetime(2025, 3, 14, 12, 0)), date(2025, 3, 14))

    def test_iso_string(self):
        self.assertEqual(_coerce_date("2025-03-14"), date(2025, 3, 14))

    def test_invalid_falls_back_to_today(self):
        self.assertEqual(_coerce_date("not-a-date"), date.today())
        self.assertEqual(_coerce_date(None), date.today())


class BuildInstrumentTests(unittest.TestCase):
    """Tests for :func:`build_instrument` against the canonical YAML fixture."""

    @classmethod
    def setUpClass(cls):
        cls.config = _load_yaml_config()

    def _build(self, **meta_overrides: Any) -> Instrument:
        instrument_mock = _build_instrument_mock(self.config)
        metadata = _build_metadata(**meta_overrides)
        return build_instrument(instrument_mock, metadata)

    def test_instrument_id_from_metadata(self):
        instrument = self._build()
        self.assertEqual(instrument.instrument_id, "exaspim-1x")

    def test_modalities_default_to_spim(self):
        instrument = self._build()
        self.assertEqual(len(instrument.modalities), 1)
        self.assertEqual(instrument.modalities[0].abbreviation, "SPIM")

    def test_walks_subdevices(self):
        """Lasers/stages under controller ``subdevices`` are emitted as top-level components."""
        instrument = self._build()
        names = {c.name for c in instrument.components}
        for laser_name in ("405 nm", "488 nm", "561 nm", "639 nm"):
            self.assertIn(laser_name, names)
        for stage_name in ("z", "x", "y", "theta", "camera"):
            self.assertIn(stage_name, names)

    def test_lasers_have_wavelengths(self):
        instrument = self._build()
        lasers = {c.name: c for c in instrument.components if isinstance(c, Laser)}
        self.assertEqual(
            {name: laser.wavelength for name, laser in lasers.items()},
            {"405 nm": 405, "488 nm": 488, "561 nm": 561, "639 nm": 639},
        )

    def test_camera_sensor_dimensions(self):
        instrument = self._build()
        cameras = [c for c in instrument.components if isinstance(c, Camera)]
        self.assertEqual(len(cameras), 1)
        camera = cameras[0]
        self.assertEqual(camera.name, "vnp-604mx")
        self.assertEqual(camera.sensor_width, 14192)
        self.assertEqual(camera.sensor_height, 10640)

    def test_scanning_vs_tiling_stages_distinguished(self):
        instrument = self._build()
        scanning = [c for c in instrument.components if isinstance(c, ScanningStage)]
        # Tiling and focusing stages are both MotorizedStage; ScanningStage subclasses it,
        # so exclude scanning stages when counting motorized-only entries.
        motorized_only = [
            c for c in instrument.components if isinstance(c, MotorizedStage) and not isinstance(c, ScanningStage)
        ]
        self.assertEqual([s.name for s in scanning], ["z"])
        self.assertEqual({s.name for s in motorized_only}, {"x", "y", "theta", "camera"})

    def test_daq_component_present(self):
        instrument = self._build()
        daqs = [c for c in instrument.components if isinstance(c, DAQDevice)]
        self.assertEqual([d.name for d in daqs], ["pcie-6738"])
        self.assertEqual(daqs[0].manufacturer, Organization.from_name("National Instruments"))

    def test_synthetic_objective_added_when_missing(self):
        """SPIM modality requires Objective; one is synthesized when YAML lacks one."""
        instrument = self._build()
        objectives = [c for c in instrument.components if isinstance(c, Objective)]
        self.assertEqual(len(objectives), 1)
        self.assertEqual(objectives[0].name, "exaspim-objective")
        self.assertIn("Placeholder objective", objectives[0].notes or "")

    def test_unknown_device_type_falls_back_to_generic_device(self):
        """A device with an unrecognised type becomes a generic ``Device`` with a notes line."""
        config = json.loads(json.dumps(self.config))  # deep copy via JSON round-trip
        config["instrument"]["devices"]["future_widget"] = {
            "type": "future_widget",
            "driver": "voxel.devices.future_widget.acme",
            "module": "AcmeFutureWidget",
        }
        instrument_mock = _build_instrument_mock(config)
        instrument = build_instrument(instrument_mock, _build_metadata())
        widget = next(c for c in instrument.components if c.name == "future_widget")
        self.assertEqual(type(widget), Device)  # exact type, not a subclass
        self.assertEqual(widget.notes, "voxel type: future_widget")

    def test_modification_date_defaults_to_today_when_missing(self):
        # Configure the mock so ``modification_date`` is absent but anatomical-direction
        # attrs (required by the coordinate system) are still present.
        spec_attrs = [
            "instrument_id",
            "x_anatomical_direction",
            "y_anatomical_direction",
            "z_anatomical_direction",
        ]
        meta = MagicMock(spec=spec_attrs)
        meta.instrument_id = "exaspim-1x"
        meta.x_anatomical_direction = "Anterior to Posterior"
        meta.y_anatomical_direction = "Inferior to Superior"
        meta.z_anatomical_direction = "Left to Right"
        instrument_mock = _build_instrument_mock(self.config)
        instrument = build_instrument(instrument_mock, meta)
        self.assertEqual(instrument.modification_date, date.today())

    def test_modalities_override(self):
        instrument_mock = _build_instrument_mock(self.config)
        instrument = build_instrument(
            instrument_mock, _build_metadata(), modalities=[Modality.SPIM]
        )
        self.assertEqual([m.abbreviation for m in instrument.modalities], ["SPIM"])

    def test_integration_instrument_json_from_yaml(self):
        """Integration: write a real ``instrument.json`` for manual review.

        Mirrors the acquisition integration test pattern: build → serialize →
        re-validate → write to ``tests/output/`` via ``write_standard_file``.
        """
        instrument = self._build()
        serialized = instrument.model_dump_json()
        deserialized = Instrument.model_validate_json(serialized)

        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(exist_ok=True)
        deserialized.write_standard_file(output_directory=str(output_dir), prefix="test")
        json_file = list(output_dir.glob("*instrument.json"))[-1]

        with open(json_file, "r", encoding="utf-8") as f:
            payload = json.load(f)

        self.assertEqual(payload["object_type"], "Instrument")
        self.assertEqual(payload["schema_version"], "2.2.6")
        self.assertEqual(payload["instrument_id"], "exaspim-1x")
        self.assertEqual(len(payload["modalities"]), 1)
        self.assertEqual(payload["modalities"][0]["abbreviation"], "SPIM")
        # Expected components: 4 lasers, 1 camera, 1 scanning stage, 2 tiling, 2 focusing,
        # 1 daq, 1 flip mount, 1 indicator light, 2 controllers (generic), 1 synthetic objective.
        self.assertGreaterEqual(len(payload["components"]), 15)
        names = {c["name"] for c in payload["components"]}
        for required in ("405 nm", "488 nm", "561 nm", "639 nm", "vnp-604mx", "z", "exaspim-objective"):
            self.assertIn(required, names)
        print(f"\n\u2713 Integration test: instrument.json written to {json_file}")


if __name__ == "__main__":
    unittest.main()
