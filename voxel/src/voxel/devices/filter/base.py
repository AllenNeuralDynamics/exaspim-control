from abc import abstractmethod

from voxel.devices.base import VoxelDevice


class BaseFilter(VoxelDevice):
    """
    Base class for filter devices.
    """

    @abstractmethod
    def enable(self) -> None:
        """
        Enable the filter device.
        """

    @abstractmethod
    def close(self) -> None:
        """
        Close the filter device.
        """
