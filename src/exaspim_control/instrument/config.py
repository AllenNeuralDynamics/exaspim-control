import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from ruyaml import YAML
from voxel.device import BuildConfig

from exaspim_control.instrument.frame_task import FrameTaskConfig

_yaml = YAML()

logger = logging.getLogger("config")


class GlobalsConfig(BaseModel):
    camera_rotation_deg: Literal[0, 90, 180, 270, 360, -270, -180, -90, -0] = 90
    unit: str
    default_overlap: float
    default_tile_order: str
    objective_magnification: float = 1.0
    illumination_labels: list[str] = Field(default_factory=lambda: ["primary"])

    @property
    def illumination_count(self) -> int:
        """Number of illumination paths available."""
        return len(self.illumination_labels)


class InstrumentInfo(BaseModel):
    instrument_uid: str
    instrument_type: str
    instrument_version: float


class StageConfig(BaseModel):
    x: str
    y: str
    z: str


class ProfileConfig(BaseModel):
    camera: str
    laser: str
    filters: dict[str, str] = Field(default_factory=dict)
    focusing_axes: list[str] = Field(default_factory=list)
    ao_task_parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)


class Vec3D(BaseModel):
    x: float
    y: float
    z: float


class ConfigError(Exception):
    def __init__(self, errors: list[str] | str):
        if isinstance(errors, str):
            errors = [errors]
        self.errors = errors
        super().__init__("\n".join(errors))


class InstrumentConfig(BaseModel):
    info: InstrumentInfo
    globals: GlobalsConfig
    devices: dict[str, BuildConfig]
    writers: dict[str, BuildConfig] = Field(default_factory=dict)
    transfers: dict[str, BuildConfig] = Field(default_factory=dict)
    widgets: dict[str, BuildConfig] = Field(default_factory=dict)
    profiles: dict[str, ProfileConfig]
    frame_task: FrameTaskConfig
    stage: StageConfig
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

    def get_channel_frame_task_config(self, channel_name: str) -> FrameTaskConfig:
        """Get the frame task config for a specific channel, with parameters merged."""
        if channel_name not in self.profiles:
            msg = f"Channel '{channel_name}' not found in configuration."
            raise ValueError(msg)

        channel_frame_task_config = self.frame_task.model_copy(deep=True)
        overrides_waveforms = self.profiles[channel_name].ao_task_parameters

        for wave_name, override_wave_params in overrides_waveforms.items():
            if wave_name in channel_frame_task_config.waveforms:
                for param_name, param_value in override_wave_params.items():
                    if hasattr(channel_frame_task_config.waveforms[wave_name], param_name):
                        setattr(channel_frame_task_config.waveforms[wave_name], param_name, param_value)
                    else:
                        logger.warning("Invalid channel frame_task_waveform override")

        return channel_frame_task_config

    @field_validator("profiles")
    @classmethod
    def channels_must_not_be_empty(cls, v):
        if not v:
            raise ValueError("at least one channel is required")
        return v

    @model_validator(mode="after")
    def channel_devices_must_exist(self):
        devices = self.devices
        for channel_name, channel in self.profiles.items():
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
    def from_yaml(cls, config_path: Path) -> "InstrumentConfig":
        config_path = Path(config_path)
        with config_path.open("r") as f:
            raw_dict = _yaml.load(f)

        # Filter out YAML anchor definitions
        # config_dict = {k: v for k, v in raw_dict.items() if not k.startswith("_")}
        config_dict = raw_dict  # let's leave them in

        # Add config_path to the dictionary before validation
        config_dict["config_path"] = config_path

        return cls.model_validate(config_dict)
