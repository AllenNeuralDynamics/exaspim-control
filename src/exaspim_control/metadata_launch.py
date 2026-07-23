import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import json
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
from aind_data_schema.components.coordinates import (
    Axis,
    CoordinateSystem,
    Scale,
    Translation,
)
from aind_data_schema.components.wrappers import AssetPath
from aind_data_schema.core.acquisition import Acquisition, DataStream
from aind_data_schema.core.instrument import Instrument
from aind_data_schema_models.coordinates import AxisName, Direction, Origin
from aind_data_schema_models.devices import ImmersionMedium
from aind_data_schema_models.modalities import Modality
from aind_data_schema_models.units import PowerUnit, SizeUnit

from exaspim_control.instrument_metadata import build_instrument as _build_instrument

if TYPE_CHECKING:  # pragma: no cover - type-only imports avoid voxel/view at runtime
    from exaspim_control.exa_spim_acquisition import ExASPIMAcquisition
    from exaspim_control.exa_spim_instrument import ExASPIM
    from exaspim_control.exa_spim_view import ExASPIMAcquisitionView, ExASPIMInstrumentView


# Map GUI strings (as produced by the existing ``aind_metadata_class.py`` mappings) to
# ``aind_data_schema_models.coordinates.Direction`` enum values. Keys cover both the human
# spelling ("Anterior to Posterior") and the underscore form ("Anterior_to_posterior"), so
# either upstream variant works.
_DIRECTION_MAP: dict[str, Direction] = {
    "Anterior to Posterior": Direction.AP,
    "Anterior_to_posterior": Direction.AP,
    "Posterior to Anterior": Direction.PA,
    "Posterior_to_anterior": Direction.PA,
    "Inferior to Superior": Direction.IS,
    "Inferior_to_superior": Direction.IS,
    "Superior to Inferior": Direction.SI,
    "Superior_to_inferior": Direction.SI,
    "Left to Right": Direction.LR,
    "Left_to_right": Direction.LR,
    "Right to Left": Direction.RL,
    "Right_to_left": Direction.RL,
}

_DEFAULT_ACQUISITION_TYPE = "ExASPIM"


def _to_direction(value: Any) -> Direction | None:
    """Return a ``Direction`` for either a GUI string or an existing enum value."""
    if value is None:
        return None
    if isinstance(value, Direction):
        return value
    return _DIRECTION_MAP.get(str(value)) or Direction(str(value))


def _build_coordinate_system(metadata: Any, *, system_name: str = "ExASPIM-XYZ") -> CoordinateSystem:
    """Build the v2 :class:`CoordinateSystem` for an Acquisition from anatomical-direction metadata.

    Preserves the original ExASPIM v0.x convention: the X axis pulls from
    ``y_anatomical_direction`` and the Y axis from ``x_anatomical_direction``.
    """
    return CoordinateSystem(
        name=system_name,
        origin=Origin.ORIGIN,
        axes=[
            Axis(name=AxisName.X, direction=_to_direction(getattr(metadata, "y_anatomical_direction", None))),
            Axis(name=AxisName.Y, direction=_to_direction(getattr(metadata, "x_anatomical_direction", None))),
            Axis(name=AxisName.Z, direction=_to_direction(getattr(metadata, "z_anatomical_direction", None))),
        ],
        axis_unit=SizeUnit.UM,
    )


def _ensure_aware(value: Any) -> datetime:
    """Coerce ``value`` (string or datetime) into a timezone-aware datetime."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.astimezone()
    return value


def _build_immersion(spec: Any) -> Immersion | None:
    """Build an ``Immersion`` from a ``{"medium": ..., "refractive_index": ...}`` payload."""
    if spec is None:
        return None
    if isinstance(spec, Immersion):
        return spec
    medium = spec["medium"] if isinstance(spec, dict) else getattr(spec, "medium")
    refractive_index = spec["refractive_index"] if isinstance(spec, dict) else getattr(spec, "refractive_index")
    if not isinstance(medium, ImmersionMedium):
        medium = ImmersionMedium(medium)
    return Immersion(medium=medium, refractive_index=refractive_index)


class MetadataLaunch:
    """Class for handling metadata launch for ExASPIM."""

    def __init__(
        self,
        instrument: "ExASPIM",
        acquisition: "ExASPIMAcquisition",
        instrument_view: "ExASPIMInstrumentView",
        acquisition_view: "ExASPIMAcquisitionView",
        log_filename: str = None,
    ):
        """
        Initialize the MetadataLaunch object.

        :param instrument: ExASPIM instrument object
        :type instrument: ExASPIM
        :param acquisition: ExASPIM acquisition object
        :type acquisition: ExASPIMAcquisition
        :param instrument_view: ExASPIM instrument view object
        :type instrument_view: ExASPIMInstrumentView
        :param acquisition_view: ExASPIM acquisition view object
        :type acquisition_view: ExASPIMAcquisitionView
        :param log_filename: Log filename, defaults to None
        :type log_filename: str, optional
        """
        # logger
        self.log = logging.getLogger(__name__ + "." + self.__class__.__name__)
        # instrument
        self.instrument = instrument
        # acquisition
        self.acquisition = acquisition
        # guis
        self.instrument_view = instrument_view
        self.acquisition_view = acquisition_view
        # log filename
        self.log_filename = log_filename
        # start and finish the acquisition - populated by the acquisitionStarted/Ended signals.
        # ``parse_metadata`` later coerces them to timezone-aware datetimes for v2 Acquisition.
        self.acquisition_start_time = None
        self.acquisition_end_time = None
        self.acquisition_view.acquisitionStarted.connect(lambda value: setattr(self, "acquisition_start_time", value))
        self.acquisition_view.acquisitionEnded.connect(
            lambda: setattr(self, "acquisition_end_time", datetime.now().astimezone())
        )
        self.acquisition_view.acquisitionEnded.connect(self.finalize_acquisition)

    def finalize_acquisition(self) -> None:
        """
        Finalize the acquisition process.
        """
        self.log.info("Finalizing acquisition")
        # create and save acquisition.json
        if getattr(self.acquisition, "file_transfers", {}) != {}:  # save to external paths
            for device_name, transfer_dict in getattr(self.acquisition, "file_transfers", {}).items():
                for transfer in transfer_dict.values():
                    save_to = str(Path(transfer.external_path, transfer.acquisition_name))
                    acquisition_model = self.parse_metadata()
                    acquisition_model.write_standard_file(output_directory=save_to, prefix=None)
                    instrument_model = self.parse_instrument(
                        coordinate_system=acquisition_model.coordinate_system
                    )
                    instrument_model.write_standard_file(output_directory=save_to, prefix=None)
                    # move the log file
                    self.log.info(f"copying {self.log_filename} to {save_to}")
                    shutil.copy(
                        self.log_filename,
                        str(Path(save_to, self.log_filename)),
                    )
            # create and save processing_manifest.json
            status = "pending"
            status_time = datetime.now()
            processing_manifest = {
                "dataset_status": {
                    "status": status,
                    "status_date": f"{status_time.year:02d}-{status_time.month:02d}-{status_time.day:02d}",
                    "status_time": f"{status_time.hour:02d}-{status_time.minute:02d}-{status_time.second:02d}"
                }
            }
            with open(Path(save_to, "processing_manifest.json"), "w", encoding="utf-8") as f:
                json.dump(processing_manifest, f, indent=4, ensure_ascii=False)
            # re-arrange external directory
            os.makedirs(Path(save_to, "exaSPIM"))
            os.makedirs(Path(save_to, "derivatives"))
            for file in os.listdir(save_to):
                if file.endswith(".ims") or file.endswith(".zarr"):
                    os.rename(str(Path(save_to, file)), str(Path(save_to, "exaSPIM", file)))
                if file.endswith(".tiff") or file.endswith(".log") or file.endswith(".yaml"):
                    os.rename(str(Path(save_to, file)), str(Path(save_to, "derivatives", file)))
            # delete local directory
            self.log.info(f"deleting {str(Path(transfer.local_path, transfer.acquisition_name))}")
            shutil.rmtree(str(Path(transfer.local_path, transfer.acquisition_name)))
        else:  # no transfers so save locally
            for device_name, writer_dict in self.acquisition.writers.items():
                for writer in writer_dict.values():
                    save_to = str(Path(writer.path, writer.acquisition_name))
                    acquisition_model = self.parse_metadata()
                    acquisition_model.write_standard_file(output_directory=save_to, prefix="exaspim")
                    instrument_model = self.parse_instrument(
                        coordinate_system=acquisition_model.coordinate_system
                    )
                    instrument_model.write_standard_file(output_directory=save_to, prefix="exaspim")
                    # move the log file
                    self.log.info(f"copying {self.log_filename} to {save_to}")
                    shutil.copy(
                        self.log_filename,
                        str(Path(save_to, self.log_filename)),
                    )
            # re-arrange external directory
            os.makedirs(Path(save_to, "exaSPIM"))
            os.makedirs(Path(save_to, "derivatives"))
            for file in os.listdir(save_to):
                if file.endswith(".ims") or file.endswith(".zarr"):
                    os.rename(str(Path(save_to, file)), str(Path(save_to, "exaSPIM", file)))
                if file.endswith(".tiff") or file.endswith(".log") or file.endswith(".yaml"):
                    os.rename(str(Path(save_to, file)), str(Path(save_to, "derivatives", file)))

    def parse_metadata(self) -> Acquisition:
        """
        Build an aind-data-schema v2 ``Acquisition`` from the live instrument and acquisition state.

        Returns
        -------
        Acquisition
            A populated v2 Acquisition with one SPIM ``DataStream`` containing an
            ``ImagingConfig`` (channels + per-tile ``ImageSPIM``) and a ``SampleChamberConfig``.
        """
        meta = self.acquisition.metadata
        subject_id = str(getattr(meta, "subject_id", ""))
        instrument_id = self.instrument.config["instrument"]["id"] or ""
        experimenters = [str(getattr(meta, "experimenter_full_name", "") or "")]
        acquisition_type = _DEFAULT_ACQUISITION_TYPE
        notes = getattr(meta, "notes", None)

        start_time = _ensure_aware(self.acquisition_start_time)
        end_time = _ensure_aware(self.acquisition_end_time)

        # Shared helper keeps the Acquisition and Instrument coordinate systems in sync.
        coordinate_system = _build_coordinate_system(meta, system_name=f"{acquisition_type}-XYZ")

        chamber_immersion = _build_immersion(getattr(meta, "chamber_immersion", None))
        sample_chamber = SampleChamberConfig(
            device_name="sample-chamber",
            chamber_immersion=chamber_immersion,
        )

        channels_cfg = self.instrument.config["instrument"]["channels"]
        images: list[ImageSPIM] = []
        channel_models: dict[str, Channel] = {}
        active_devices: list[str] = [acquisition_type, sample_chamber.device_name]

        for tile in self.acquisition.config["acquisition"]["tiles"]:
            tile_ch = tile["channel"]
            laser_name = channels_cfg[tile_ch]["lasers"][0]
            camera_name = channels_cfg[tile_ch]["cameras"][0]
            excitation_wavelength = self.instrument.lasers[laser_name].wavelength
            camera = self.instrument.cameras[camera_name]
            binning = tile[camera_name]["binning"]
            voxel_size_x_um = camera.um_px * binning
            voxel_size_y_um = camera.um_px * binning
            voxel_size_z_um = tile["step_size"]
            tile_x_mm = tile["position_mm"]["x"]
            tile_y_mm = tile["position_mm"]["y"]
            tile_z_mm = tile["position_mm"]["z"]

            if tile_ch not in channel_models:
                filter_names = list(channels_cfg[tile_ch].get("filters", []) or [])
                # Anything beyond lasers/cameras/filters becomes "additional devices" for the channel.
                additional_names: list[str] = []
                for key, value in channels_cfg[tile_ch].items():
                    if key in ("lasers", "cameras", "filters"):
                        continue
                    if isinstance(value, (list, tuple)):
                        additional_names.extend(str(v) for v in value)
                    else:
                        additional_names.append(str(value))

                channel_models[tile_ch] = Channel(
                    channel_name=tile_ch,
                    detector=DetectorConfig(device_name=camera_name, trigger_type=TriggerType.EXTERNAL),
                    light_sources=[
                        LaserConfig(
                            device_name=laser_name,
                            wavelength=excitation_wavelength,
                            power=tile[laser_name]["power_setpoint_mw"],
                            power_unit=PowerUnit.MW,
                        )
                    ],
                    emission_filters=[DeviceConfig(device_name=name) for name in filter_names] or None,
                    additional_device_names=(
                        [DeviceConfig(device_name=name) for name in additional_names] or None
                    ),
                )
                active_devices.extend([camera_name, laser_name, *filter_names, *additional_names])

            images.append(
                ImageSPIM(
                    channel_name=tile_ch,
                    file_name=AssetPath(f"{tile['prefix']}_{tile['tile_number']:06}_ch_{tile_ch}.ims"),
                    image_to_acquisition_transform=[
                        Scale(scale=[voxel_size_x_um, voxel_size_y_um, voxel_size_z_um]),
                        Translation(translation=[-tile_y_mm, tile_x_mm, tile_z_mm]),
                    ],
                )
            )

        imaging_config = ImagingConfig(
            device_name=acquisition_type,
            coordinate_system=coordinate_system,
            channels=list(channel_models.values()),
            images=images,
        )

        data_stream = DataStream(
            stream_start_time=start_time,
            stream_end_time=end_time,
            modalities=[Modality.SPIM],
            active_devices=list(dict.fromkeys(active_devices)),  # preserve order, drop dupes
            configurations=[imaging_config, sample_chamber],
        )

        return Acquisition(
            subject_id=subject_id,
            specimen_id=subject_id,
            experimenters=experimenters,
            acquisition_start_time=start_time,
            acquisition_end_time=end_time,
            acquisition_type=acquisition_type,
            instrument_id=instrument_id,
            notes=notes,
            coordinate_system=coordinate_system,
            data_streams=[data_stream],
        )

    def parse_instrument(self, *, coordinate_system=None) -> Instrument:
        """Build an aind-data-schema v2 :class:`Instrument` from the live instrument state.

        Parameters
        ----------
        coordinate_system : CoordinateSystem, optional
            Reuse the coordinate system from the matching :class:`Acquisition` so the two
            JSON files agree. Built from metadata if not supplied.

        Returns
        -------
        Instrument
            A populated v2 :class:`Instrument` model ready for ``write_standard_file``.
        """
        return _build_instrument(
            self.instrument,
            self.acquisition.metadata,
            coordinate_system=coordinate_system,
        )
