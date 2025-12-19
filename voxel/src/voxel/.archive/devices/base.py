"""Base class for all voxel devices."""

import logging
from abc import ABC, abstractmethod


class VoxelDevice(ABC):
    """Base class for all voxel devices."""

    def __init__(self, uid: str) -> None:
        self.uid = uid
        self.log = logging.getLogger(f"{self.__class__.__name__}[{self.uid}]")

    @abstractmethod
    def close(self) -> None:
        """
        Close the device.
        """

    def __str__(self) -> str:
        """
        Return a string representation of the device.

        :return: String representation of the device
        :rtype: str
        """
        return f"{self.__class__.__name__}[{self.uid}]"
