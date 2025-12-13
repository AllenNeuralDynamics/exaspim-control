import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator
from ruyaml import YAML
from voxel.devices.daq.acq_task import AcqTaskConfig

_yaml = YAML()

logger = logging.getLogger("config")


class BuildConfig(BaseModel):
    target: str
    init: dict[str, Any] = Field(default_factory=dict)
    defaults: dict[str, Any] | None = None


class GlobalsConfig(BaseModel):
    coordinate_plane: tuple[str, str, str]
    camera_rotation_deg: Literal[0, 90, 180, 270, 360, -270, -180, -90, -0] = 90
    unit: str
    default_overlap: float
    default_tile_order: str
    dual_sided: bool


class InstrumentInfo(BaseModel):
    instrument_uid: str
    instrument_type: str
    instrument_version: float


class Metadata(InstrumentInfo):
    subject_id: str | None = None
    experimenter_full_name: list[str] | None = None
    chamber_medium: str = "other"
    chamber_refractive_index: float = 1.33
    x_anatomical_direction: Literal["Anterior_to_posterior", "Posterior_to_anterior"] = "Anterior_to_posterior"
    y_anatomical_direction: Literal["Inferior_to_superior", "Superior_to_inferior"] = "Inferior_to_superior"
    z_anatomical_direction: Literal["Left_to_right", "Right_to_left"] = "Left_to_right"
    date_format: Literal["Year/Month/Day/Hour/Minute/Second"] = "Year/Month/Day/Hour/Minute/Second"
    name_delimitor: Literal["_", "."] = "_"

    @property
    def is_experiment_configured(self) -> bool:
        return self.subject_id is not None and self.experimenter_full_name is not None

    @computed_field
    def experiement_name(self) -> str:
        return f"{self.instrument_type}{self.name_delimitor}{self.subject_id}"


class StageConfig(BaseModel):
    x: str
    y: str
    z: str
    theta: str | None = None


class ChannelConfig(BaseModel):
    camera: str
    laser: str
    filters: dict[str, str] = Field(default_factory=dict)
    focusing_axes: list[str] = Field(default_factory=list)
    ao_task_parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)


class Vec3D(BaseModel):
    x: float
    y: float
    z: float


class TileInfo(BaseModel):
    channel: str
    position: Vec3D
    settings: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ConfigError(Exception):
    def __init__(self, errors: list[str] | str):
        if isinstance(errors, str):
            errors = [errors]
        self.errors = errors
        super().__init__("\n".join(errors))


class ExASPIMConfig(BaseModel):
    metadata: Metadata
    globals: GlobalsConfig
    devices: dict[str, BuildConfig]
    writers: dict[str, BuildConfig] = Field(default_factory=dict)
    transfers: dict[str, BuildConfig] = Field(default_factory=dict)
    widgets: dict[str, BuildConfig] = Field(default_factory=dict)
    channels: dict[str, ChannelConfig]
    acq_task: AcqTaskConfig
    stage: StageConfig
    acquisition: list[TileInfo] | None = None
    config_path: Path | None = Field(default=None, exclude=True)

    def save(self):
        """Save configuration to the current config_path."""
        if self.config_path is None:
            msg = "No config path set. Use save_as() instead."
            raise ValueError(msg)
        self.save_as(self.config_path)

    def save_as(self, config_path: Path):
        """Save configuration to a new path."""
        config_path = Path(config_path)
        with config_path.open("w") as f:
            _yaml.dump(self.dict(exclude_none=True), f)
        self.config_path = config_path

    def get_channel_acq_task_config(self, channel_name: str) -> AcqTaskConfig:
        """Get the acquisition task config for a specific channel, with parameters merged."""
        if channel_name not in self.channels:
            msg = f"Channel '{channel_name}' not found in configuration."
            raise ValueError(msg)

        channel_acq_task_config = self.acq_task.model_copy(deep=True)
        overrides_waveforms = self.channels[channel_name].ao_task_parameters

        for wave_name, override_wave_params in overrides_waveforms.items():
            if wave_name in channel_acq_task_config.waveforms:
                for param_name, param_value in override_wave_params.items():
                    if hasattr(channel_acq_task_config.waveforms[wave_name], param_name):
                        setattr(channel_acq_task_config.waveforms[wave_name], param_name, param_value)
                    else:
                        logger.warning("Invalid channel acq_waveform override")

        return channel_acq_task_config

    @field_validator("channels")
    @classmethod
    def channels_must_not_be_empty(cls, v):
        if not v:
            raise ValueError("at least one channel is required")
        return v

    @model_validator(mode="after")
    def channel_devices_must_exist(self):
        devices = self.devices
        for channel_name, channel in self.channels.items():
            if channel.camera and channel.camera not in devices:
                msg = f"channel '{channel_name}' references unknown camera '{channel.camera}'"
                raise ValueError(msg)
            if channel.laser and channel.laser not in devices:
                msg = f"channel '{channel_name}' references unknown laser '{channel.laser}'"
                raise ValueError(msg)
            for axis in channel.focusing_axes:
                if axis not in devices:
                    msg = f"channel '{channel_name}' references unknown focusing axis '{axis}'"
                    raise ValueError(msg)
            for filter_wheel in channel.filters:
                if filter_wheel not in devices:
                    msg = f"channel '{channel_name}' references unknown filter wheel '{filter_wheel}'"
                    raise ValueError(msg)
        return self

    @classmethod
    def from_yaml(cls, config_path: Path) -> "ExASPIMConfig":
        config_path = Path(config_path)
        with config_path.open("r") as f:
            raw_dict = _yaml.load(f)

        # Filter out YAML anchor definitions
        # config_dict = {k: v for k, v in raw_dict.items() if not k.startswith("_")}
        config_dict = raw_dict  # let's leave them in

        # Add config_path to the dictionary before validation
        config_dict["config_path"] = config_path

        return cls.model_validate(config_dict)
