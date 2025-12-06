from abc import abstractmethod

from voxel.devices.base import VoxelDevice


class BaseJoystick(VoxelDevice):
    """
    Base class for joystick devices.
    """

    @abstractmethod
    def stage_axes(self) -> list[str]:
        """
        Get the stage axes controlled by the joystick.

        :return: list of stage axes
        :rtype: list
        """

    @abstractmethod
    def joystick_mapping(self) -> dict[str, str]:
        """
        Get the joystick mapping.

        :return: Joystick mapping
        :rtype: dict
        """

    @abstractmethod
    def close(self) -> None:
        """
        Close the joystick device.
        """
