from abc import abstractmethod

from voxel.devices.base import VoxelDevice


class BaseAOTF(VoxelDevice):
    """
    Base class for Acousto-Optic Tunable Filter (AOTF) devices.
    """

    @abstractmethod
    def enable_all(self) -> None:
        """
        Enable all channels of the AOTF.
        """

    @abstractmethod
    def disable_all(self) -> None:
        """
        Disable all channels of the AOTF.
        """

    @property
    @abstractmethod
    def frequency_hz(self) -> dict[int, float]:
        """
        Get the frequency in Hz for the AOTF.

        :return: The frequency in Hz.
        :rtype: dict
        """

    @frequency_hz.setter
    @abstractmethod
    def frequency_hz(self, frequency_hz: dict[int, float]) -> None:
        """
        Set the frequency in Hz for a specific channel of the AOTF.

        :param frequency_hz: The frequency in Hz.
        :type frequency_hz: dict
        """

    @property
    @abstractmethod
    def power_dbm(self) -> dict[int, float]:
        """
        Get the power in dBm for the AOTF.

        :return: The power in dBm.
        :rtype: dict
        """

    @power_dbm.setter
    @abstractmethod
    def power_dbm(self, power_dbm: dict[int, float]) -> None:
        """
        Set the power in dBm for a specific channel of the AOTF.

        :param power_dbm: The power in dBm.
        :type power_dbm: dict
        """

    @property
    @abstractmethod
    def blanking_mode(self) -> str:
        """
        Get the blanking mode of the AOTF.

        :return: The blanking mode.
        :rtype: str
        """

    @blanking_mode.setter
    @abstractmethod
    def blanking_mode(self, mode: str) -> None:
        """
        Set the blanking mode of the AOTF.

        :param mode: The blanking mode.
        :type mode: str
        """

    @property
    @abstractmethod
    def input_mode(self) -> dict[int, str]:
        """
        Get the input mode of the AOTF.

        :return: The input mode.
        :rtype: dict
        """

    @input_mode.setter
    @abstractmethod
    def input_mode(self, modes: dict[int, str]) -> None:
        """
        Set the input mode of the AOTF.

        :param modes: The input modes.
        :type modes: dict
        """
