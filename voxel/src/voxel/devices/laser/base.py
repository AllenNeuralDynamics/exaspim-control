from abc import abstractmethod

from voxel.devices.base import VoxelDevice


class BaseLaser(VoxelDevice):
    """Base class for all voxel laser devices."""

    @abstractmethod
    def enable(self) -> None:
        """
        Turn on the laser.
        """

    @abstractmethod
    def disable(self) -> None:
        """
        Turn off the laser.
        """

    @property
    @abstractmethod
    def wavelength(self) -> int:
        """
        Get the wavelength of the laser.

        :return: Wavelength of the laser
        :rtype: int
        """

    @property
    @abstractmethod
    def power_setpoint_mw(self) -> float:
        """
        The power setpoint is the target power that the laser is trying to achieve.

        :return: The power setpoint in mW.
        :rtype: float
        """

    @power_setpoint_mw.setter
    @abstractmethod
    def power_setpoint_mw(self, value: float) -> None:
        """
        Set the power setpoint for the laser in mW.

        :param value: The power setpoint in mW.
        :type value: float
        """

    @property
    @abstractmethod
    def power_mw(self) -> float:
        """
        Get the actual power of the laser in mW.

        :return: The power in mW.
        :rtype: float
        """

    @property
    @abstractmethod
    def temperature_c(self) -> float | None:
        """
        Get the main temperature of the laser in degrees Celsius.

        :return: The temperature in degrees Celsius.
        :rtype: float
        """
