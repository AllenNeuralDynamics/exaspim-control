from abc import abstractmethod
from enum import StrEnum
from typing import Literal, cast

import numpy as np
from ome_zarr_writer.types import Dtype, SchemaModel, Vec2D
from pydantic import BaseModel
from voxel.device import deliminated_float, describe, enumerated_int, enumerated_string
from voxel.device.props.deliminated import DeliminatedInt
from voxel.interfaces.spim import DeviceType, SpimDevice


class TriggerMode(StrEnum):
    OFF = "off"
    ON = "on"


class TriggerPolarity(StrEnum):
    RISING_EDGE = "rising"
    FALLING_EDGE = "falling"


class StreamInfo(SchemaModel):
    frame_index: int
    input_buffer_size: int
    output_buffer_size: int
    dropped_frames: int
    frame_rate_fps: float
    data_rate_mbs: float
    payload_mbs: float | None = None


PixelFormat = Literal["MONO8", "MONO10", "MONO12", "MONO14", "MONO16"]

PIXEL_FMT_TO_DTYPE: dict[PixelFormat, Dtype] = {
    "MONO8": Dtype.UINT8,
    "MONO10": Dtype.UINT16,
    "MONO12": Dtype.UINT16,
    "MONO14": Dtype.UINT16,
    "MONO16": Dtype.UINT16,
}

BINNING_OPTIONS = [1, 2, 4, 8]


class FrameRegion(BaseModel):
    """Frame region with constraints embedded in each dimension.

    Each dimension (x, y, width, height) is a DeliminatedInt that carries
    its current value along with min/max/step constraints.

    Values are in frame coordinates (post-binning), not sensor coordinates.
    """

    x: DeliminatedInt
    y: DeliminatedInt
    width: DeliminatedInt
    height: DeliminatedInt

    model_config = {"arbitrary_types_allowed": True}


class SpimCamera(SpimDevice):
    __DEVICE_TYPE__ = DeviceType.CAMERA

    trigger_mode: TriggerMode = TriggerMode.OFF
    trigger_polarity: TriggerPolarity = TriggerPolarity.RISING_EDGE

    @property
    @abstractmethod
    @describe(label="Sensor Size", units="px", desc="The size of the camera sensor in pixels.")
    def sensor_size_px(self) -> Vec2D[int]:
        """Get the size of the camera sensor in pixels."""

    @property
    @abstractmethod
    @describe(label="Pixel Size", units="µm", desc="The size of the camera pixel in microns.")
    def pixel_size_um(self) -> Vec2D[float]:
        """Get the size of the camera pixel in microns."""

    @enumerated_string(options=list(PIXEL_FMT_TO_DTYPE.keys()))
    @abstractmethod
    def pixel_format(self) -> PixelFormat:
        """Get the pixel format of the camera."""

    @pixel_format.setter
    @abstractmethod
    def pixel_format(self, pixel_format: str) -> None:
        """Set the pixel format of the camera."""

    @property
    @describe(label="Pixel Type", desc="The numpy dtype of pixels based on format.")
    def pixel_type(self) -> Dtype:
        """Get the pixel type of the camera."""
        return PIXEL_FMT_TO_DTYPE[cast(PixelFormat, str(self.pixel_format))]

    @enumerated_int(options=BINNING_OPTIONS)
    @abstractmethod
    def binning(self) -> int:
        """Get the binning mode of the camera. Integer value, e.g. 2 is 2x2 binning."""

    @binning.setter
    @abstractmethod
    def binning(self, binning: int) -> None:
        """Set the binning mode of the camera. Integer value, e.g. 2 is 2x2 binning."""

    @deliminated_float()
    @abstractmethod
    def exposure_time_ms(self) -> float:
        """Get the exposure time of the camera in ms."""

    @exposure_time_ms.setter
    @abstractmethod
    def exposure_time_ms(self, exposure_time_ms: float) -> None:
        """Set the exposure time of the camera in ms."""

    @deliminated_float()
    @abstractmethod
    def frame_rate_hz(self) -> float:
        """Get the frame rate of the camera in Hz."""

    @frame_rate_hz.setter
    @abstractmethod
    def frame_rate_hz(self, value: float) -> None:
        """Set the frame rate of the camera in Hz."""

    @property
    @abstractmethod
    @describe(label="Frame Region", desc="Current frame region with embedded constraints.")
    def frame_region(self) -> FrameRegion:
        """Get current frame region with embedded constraints.

        Values are in frame coordinates (post-binning), not sensor coordinates.
        The camera's Width/Height already reflects hardware binning.
        """

    @abstractmethod
    def update_frame_region(
        self,
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        """Update frame region. Only provided values are changed.

        Values are in frame coordinates (post-binning).

        :param x: New X offset (optional)
        :param y: New Y offset (optional)
        :param width: New width (optional)
        :param height: New height (optional)
        """

    @property
    @describe(label="Frame Size", units="px", desc="The image size in pixels.")
    def frame_size_px(self) -> Vec2D[int]:
        """Get the image size in pixels."""
        r = self.frame_region
        return Vec2D(int(r.width), int(r.height))

    @property
    @describe(label="Frame Size", units="MB", desc="The size of one frame in megabytes.")
    def frame_size_mb(self) -> float:
        """Get the size of the camera image in MB."""
        return (self.frame_size_px.x * self.frame_size_px.y * self.pixel_type.itemsize) / 1_000_000

    @property
    @describe(label="Frame Area", units="mm", desc="The physical area being captured in millimeters.")
    def frame_area_mm(self) -> Vec2D[float]:
        """Get the physical area being captured in millimeters."""
        return Vec2D(
            self.frame_size_px.x * self.binning * self.pixel_size_um.x / 1000,
            self.frame_size_px.y * self.binning * self.pixel_size_um.y / 1000,
        )

    @property
    @abstractmethod
    @describe(label="Stream Info", desc="Acquisition state info or None if not streaming.", stream=True)
    def stream_info(self) -> StreamInfo | None:
        """Return a dictionary of the acquisition state or None if not acquiring.

        - Frame Index - frame number of the acquisition
        - Input Buffer Size - number of free frames in buffer
        - Output Buffer Size - number of frames to grab from buffer
        - Dropped Frames - number of dropped frames
        - Data Rate [MB/s] - data rate of acquisition
        - Frame Rate [fps] - frames per second of acquisition
        """

    @abstractmethod
    def _configure_trigger_mode(self, mode: TriggerMode) -> None:
        """Configure the trigger mode of the camera."""

    @abstractmethod
    def _configure_trigger_polarity(self, polarity: TriggerPolarity) -> None:
        """Configure the trigger polarity of the camera."""

    @abstractmethod
    def _prepare_for_capture(self) -> None:
        """Prepare the camera to acquire images. Initializes the camera buffer."""

    @describe(label="Prepare", desc="Prepare camera for acquisition with trigger settings.")
    def prepare(self, trigger_mode: TriggerMode | None = None, trigger_polarity: TriggerPolarity | None = None):
        self.trigger_mode = trigger_mode if trigger_mode is not None else self.trigger_mode
        self.trigger_polarity = trigger_polarity if trigger_polarity is not None else self.trigger_polarity
        self._configure_trigger_mode(self.trigger_mode)
        self._configure_trigger_polarity(self.trigger_polarity)
        self._prepare_for_capture()

    @abstractmethod
    @describe(label="Start", desc="Start acquiring frames from the camera.")
    def start(self, frame_count: int | None = None) -> None:
        """Start the camera to acquire a certain number of frames.

        If frame number is not specified, acquires infinitely until stopped.
        Initializes the camera buffer.

        Arguments:
            frame_count: The number of frames to acquire. If None, acquires indefinitely until stopped.
        """

    @abstractmethod
    @describe(label="Grab Frame", desc="Grab a single frame from the camera buffer.")
    def grab_frame(self) -> np.ndarray:
        """Grab a frame from the camera buffer.

        If binning is via software, the GPU binned
        image is computed and returned.

        Returns:
            The camera frame of size (height, width).

        Raises:
            RuntimeError: If the camera is not started.
        """

    @abstractmethod
    @describe(label="Stop", desc="Stop the camera acquisition.")
    def stop(self) -> None:
        """Stop the camera."""
