"""Tests for ``exaspim_control.metadata_launch.MetadataLaunch`` against aind-data-schema v2.x."""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

# ``metadata_launch`` only references ``voxel``/``view`` from ``exa_spim_*`` under TYPE_CHECKING,
# so this module imports cleanly without those siblings installed. If a future change pulls them
# in at runtime, the import below will fail loudly and we can revisit.
from exaspim_control.metadata_launch import MetadataLaunch

from aind_data_schema.components.configs import (
    Channel,
    DetectorConfig,
    DeviceConfig,
    ImageSPIM,
    ImagingConfig,
    Immersion,
    LaserConfig,
    SampleChamberConfig,
    TriggerType,
)
from aind_data_schema.components.coordinates import Axis, CoordinateSystem, Scale, Translation
from aind_data_schema.components.wrappers import AssetPath
from aind_data_schema.core.acquisition import Acquisition, DataStream
from aind_data_schema_models.coordinates import AxisName, Direction, Origin
from aind_data_schema_models.devices import ImmersionMedium
from aind_data_schema_models.modalities import Modality
from aind_data_schema_models.units import PowerUnit, SizeUnit


# Use a fixed timezone-aware timestamp so the test is deterministic regardless of host TZ.
_FIXED_DT = datetime(2022, 12, 27, 8, 26, 49, tzinfo=timezone.utc)


def _build_metadata_launch() -> MetadataLaunch:
    """Build a ``MetadataLaunch`` wired to mocked ExASPIM components."""
    instrument_config = {
        "instrument": {
            "channels": {
                "CH639": {
                    "filters": ["BP639"],
                    "lasers": ["639 nm"],
                    "cameras": ["vp-151mx"],
                }
            }
        }
    }
    mocked_laser = MagicMock(wavelength=639)
    mocked_camera = MagicMock(um_px=0.748)
    mocked_instrument = MagicMock(
        lasers={"639 nm": mocked_laser},
        cameras={"vp-151mx": mocked_camera},
        config=instrument_config,
    )
    mocked_metadata = MagicMock()
    mocked_metadata.configure_mock(
        experimenter_full_name=["Chris P. Bacon"],
        subject_id=123,
        instrument_id="exaspim123",
        chamber_immersion={"medium": "oil", "refractive_index": 1.33},
        x_anatomical_direction="Anterior to Posterior",
        y_anatomical_direction="Inferior to Superior",
        z_anatomical_direction="Left to Right",
        notes=None,
    )
    acquisition_config = {
        "acquisition": {
            "tiles": [
                {
                    "channel": "CH639",
                    "position_mm": {"x": -4.537907199999999, "y": 11.601536, "z": 12.0},
                    "tile_number": 0,
                    "vp-151mx": {"binning": 1},
                    "639 nm": {"power_setpoint_mw": 0.0},
                    "steps": 0,
                    "step_size": 1.0,
                    "prefix": "tile",
                }
            ]
        }
    }
    mocked_acquisition = MagicMock()
    mocked_acquisition.configure_mock(metadata=mocked_metadata, config=acquisition_config)
    mock_signal = MagicMock()
    mock_signal.configure_mock(connect=lambda x: None)
    mocked_acquisition_view = MagicMock()
    mocked_acquisition_view.configure_mock(acquisitionStarted=mock_signal, acquisitionEnded=mock_signal)

    launch = MetadataLaunch(
        instrument=mocked_instrument,
        acquisition=mocked_acquisition,
        instrument_view=MagicMock(),
        acquisition_view=mocked_acquisition_view,
    )
    launch.acquisition_start_time = _FIXED_DT
    launch.acquisition_end_time = _FIXED_DT
    return launch


def _expected_acquisition() -> Acquisition:
    """Construct the expected v2 Acquisition for the mocked inputs."""
    coordinate_system = CoordinateSystem(
        name="ExASPIM-XYZ",
        origin=Origin.ORIGIN,
        axes=[
            # Original v0.x layout swapped X/Y anatomical sources -- preserved in the v2 build.
            Axis(name=AxisName.X, direction=Direction("Inferior_to_superior")),
            Axis(name=AxisName.Y, direction=Direction("Anterior_to_posterior")),
            Axis(name=AxisName.Z, direction=Direction("Left_to_right")),
        ],
        axis_unit=SizeUnit.UM,
    )
    sample_chamber = SampleChamberConfig(
        device_name="sample-chamber",
        chamber_immersion=Immersion(medium=ImmersionMedium("oil"), refractive_index=1.33),
    )
    channel = Channel(
        channel_name="CH639",
        detector=DetectorConfig(device_name="vp-151mx", trigger_type=TriggerType.EXTERNAL),
        light_sources=[
            LaserConfig(device_name="639 nm", wavelength=639, power=0.0, power_unit=PowerUnit.MW)
        ],
        emission_filters=[DeviceConfig(device_name="BP639")],
    )
    image = ImageSPIM(
        channel_name="CH639",
        file_name=AssetPath("tile_000000_ch_CH639.ims"),
        image_to_acquisition_transform=[
            Scale(scale=[0.748, 0.748, 1.0]),
            Translation(translation=[-11.601536, -4.537907199999999, 12.0]),
        ],
    )
    imaging_config = ImagingConfig(
        device_name="ExASPIM",
        coordinate_system=coordinate_system,
        channels=[channel],
        images=[image],
    )
    data_stream = DataStream(
        stream_start_time=_FIXED_DT,
        stream_end_time=_FIXED_DT,
        modalities=[Modality.SPIM],
        active_devices=["ExASPIM", "sample-chamber", "vp-151mx", "639 nm", "BP639"],
        configurations=[imaging_config, sample_chamber],
    )
    return Acquisition(
        subject_id="123",
        specimen_id="123",
        experimenters=["Chris P. Bacon"],
        acquisition_start_time=_FIXED_DT,
        acquisition_end_time=_FIXED_DT,
        acquisition_type="ExASPIM",
        instrument_id="exaspim123",
        notes=None,
        coordinate_system=coordinate_system,
        data_streams=[data_stream],
    )


class MetaDataLaunchTests(unittest.TestCase):
    """Tests for ``MetadataLaunch`` against aind-data-schema v2.x."""

    def test_parse_metadata_returns_v2_acquisition(self):
        """``parse_metadata`` produces an Acquisition equal to the hand-built expected model."""
        launch = _build_metadata_launch()
        actual = launch.parse_metadata()
        expected = _expected_acquisition()

        # Compare structurally via ``model_dump`` to avoid Pydantic instance-identity mismatches.
        self.assertEqual(actual.model_dump(), expected.model_dump())
        self.assertEqual(actual.schema_version, "2.5.2")
        self.assertEqual(actual.acquisition_type, "ExASPIM")

    def test_write_standard_file_round_trip(self):
        """``write_standard_file`` produces a JSON file that round-trips back to an equivalent model."""
        launch = _build_metadata_launch()
        model = launch.parse_metadata()
        with TemporaryDirectory() as tmp:
            model.write_standard_file(output_directory=tmp, prefix="exaspim")
            written = list(Path(tmp).glob("*acquisition.json"))
            self.assertEqual(len(written), 1, f"expected one acquisition.json, got {written}")
            with open(written[0], "r", encoding="utf-8") as f:
                payload = json.load(f)
        self.assertEqual(payload["schema_version"], "2.5.2")
        self.assertEqual(payload["subject_id"], "123")
        self.assertEqual(payload["acquisition_type"], "ExASPIM")
        # Re-parse to validate it survives a v2 model round-trip.
        Acquisition.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
