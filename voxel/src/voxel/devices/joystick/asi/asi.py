import logging

from tigerasi.device_codes import JoystickInput, JoystickPolarity
from tigerasi.tiger_controller import TigerController

from voxel.devices.joystick.base import BaseJoystick

JOYSTICK_AXES = {
    "joystick_x": JoystickInput.JOYSTICK_X,
    "joystick_y": JoystickInput.JOYSTICK_Y,
    "wheel_z": JoystickInput.Z_WHEEL,
    "wheel_f": JoystickInput.F_WHEEL,
    "None": JoystickInput.NONE,
}

POLARITIES = {
    "inverted": JoystickPolarity.INVERTED,
    "default": JoystickPolarity.DEFAULT,
}

INSTRUMENT_AXES = []


class ASIJoystick(BaseJoystick):
    """
    Joystick class for handling ASI joystick devices.
    """

    def __init__(
        self,
        tigerbox: TigerController,
        axis_mapping: dict[str, str],
        joystick_mapping: dict[str, dict[str, str]] | None = None,
    ) -> None:
        """
        Initialize the Joystick object.

        :param tigerbox: TigerController object
        :type tigerbox: TigerController
        :param axis_mapping: Axis mapping dictionary
        :type axis_mapping: dict
        :param joystick_mapping: Joystick mapping dictionary, defaults to None
        :type joystick_mapping: dict, optional
        :raises ValueError: If an invalid joystick ID or polarity is provided
        """
        self.log = logging.getLogger(__name__ + "." + self.__class__.__name__)

        self.tigerbox = tigerbox
        self._joystick_mapping = (
            joystick_mapping
            if joystick_mapping is not None
            else {
                "joystick_x": {"instrument_axis": "x", "polarity": "default"},
                "joystick_y": {"instrument_axis": "y", "polarity": "default"},
                "wheel_z": {"instrument_axis": "z", "polarity": "default"},
                "wheel_f": {"instrument_axis": "w", "polarity": "default"},
            }
        )
        self.axis_mapping = axis_mapping
        for key in self.axis_mapping:
            INSTRUMENT_AXES.append(key)
        self._stage_axes = {
            v: k
            for k, v in self.axis_mapping.items()
            if k.upper() in self.tigerbox.axes and v.upper() in self.tigerbox.axes
        }
        for axis in self.tigerbox.axes:
            if axis.lower() not in self._stage_axes:
                self._stage_axes[axis.lower()] = axis.lower()
                self.axis_mapping[axis.lower()] = axis.lower()
        # grab the instrument to hardware axis mapping for the joystick device
        for joystick_id, joystick_dict in self.joystick_mapping.items():
            # check that the joystick ids are valid
            if joystick_id not in JOYSTICK_AXES:
                msg = f"{joystick_id} must be in {JOYSTICK_AXES.keys()}"
                raise ValueError(msg)
            # check that the polarities are valid
            joystick_polarity = joystick_dict["polarity"]
            if joystick_polarity not in POLARITIES:
                msg = f"{joystick_polarity} must be in {POLARITIES.keys()}"
                raise ValueError(msg)
            instrument_axis = joystick_dict["instrument_axis"]
            hardware_axis = self.axis_mapping[instrument_axis]
            # check that the axes are valid
            if hardware_axis not in self._stage_axes:
                msg = f"instrument axis = {instrument_axis}, hardware_axis = {hardware_axis} is not a valid axis."
                raise ValueError(msg)

    @property
    def stage_axes(self) -> dict[str, str]:
        """
        Get the stage axes controlled by the joystick.

        :return: Stage axes
        :rtype: dict
        """
        return self._stage_axes

    @property
    def joystick_mapping(self) -> dict[str, dict[str, str]]:
        """
        Get the joystick mapping.

        :return: Joystick mapping
        :rtype: dict
        """
        return self._joystick_mapping

    @joystick_mapping.setter
    def joystick_mapping(self, joystick_mapping: dict[str, dict[str, str]]) -> None:
        """
        Set the joystick mapping.

        :param joystick_mapping: Joystick mapping dictionary
        :type joystick_mapping: dict
        :raises ValueError: If an invalid joystick ID or polarity is provided
        """
        for joystick_id, joystick_dict in joystick_mapping.items():
            # check that the joystick ids are valid
            if joystick_id not in JOYSTICK_AXES:
                msg = f"{joystick_id} must be in {JOYSTICK_AXES.keys()}"
                raise ValueError(msg)
            # check that the polarities are valid
            joystick_polarity = joystick_dict["polarity"]
            if joystick_polarity not in POLARITIES:
                msg = f"{joystick_polarity} must be in {POLARITIES.keys()}"
                raise ValueError(msg)

            instrument_axis = joystick_dict["instrument_axis"]
            hardware_axis = self.axis_mapping[instrument_axis]
            # check that the axes are valid
            if hardware_axis not in self._stage_axes:
                msg = f"instrument axis = {instrument_axis}, hardware_axis = {hardware_axis} is not a valid axis."
                raise ValueError(msg)
        self._joystick_mapping = joystick_mapping

    def close(self) -> None:
        """
        Close the joystick device.
        """
        self.tigerbox.close()
