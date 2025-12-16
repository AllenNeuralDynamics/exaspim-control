from enum import StrEnum
from typing import ClassVar

from voxel.new.device import Device


class DeviceType(StrEnum):
    GENERIC = "generic"
    DAQ = "daq"
    CAMERA = "camera"
    LASER = "laser"
    AOTF = "aotf"
    LINEAR_AXIS = "linear_axis"
    DISCRETE_AXIS = "discrete_axis"


class SpimDevice(Device):
    __DEVICE_TYPE__: ClassVar[DeviceType] = DeviceType.GENERIC  # pyright: ignore[reportIncompatibleVariableOverride]
