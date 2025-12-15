from collections.abc import Mapping
from typing import final

from voxel.devices.daq.base import VoxelDAQ
from voxel.devices.filterwheel.base import VoxelFilterWheel

# These can be made configurable through the device's 'init' block in YAML
PULSE_VOLTAGE_V = 5.0
PULSE_DURATION_S = 0.05  # 50ms


@final
class DAQFilterWheel(VoxelFilterWheel):
    """
    A FilterWheel that sends a trigger pulse via a VoxelDAQ device to switch filters.
    """

    def __init__(self, uid: str, slots: Mapping[int, str | None], daq: VoxelDAQ, ports: dict[str, str]):
        super().__init__(uid=uid, slots=slots)
        self._daq = daq
        self._ports = ports
        self._position: int = min(slots.keys())
        self._is_moving: bool = False

        self.home()

        # first_filter = next(iter(self.filters.keys()))
        # self._set_filter(first_filter)
        # self._filter: str = first_filter

    @property
    def position(self) -> int:
        return self._position

    @property
    def is_moving(self) -> bool:
        return self._is_moving

    def move(self, slot: int, *, wait: bool = False, timeout: float | None = None) -> None:
        if slot not in self._slots:
            msg = f"Invalid slot passed: {slot}: Valid: {self._slots.keys()}"
            raise ValueError(msg)
        if (label := self._slots.get(slot)) and (daq_port := self._ports.get(label)):
            try:
                # Use the high-level pulse method on the DAQ interface
                self._daq.pulse(pin=daq_port, duration_s=PULSE_DURATION_S, voltage_v=PULSE_VOLTAGE_V)
                self._position = slot
                self.log.info(f"Successfully set filter to '{label}'.")
            except Exception:
                self.log.exception(f"Failed to switch filter to '{label}'.")
                raise
        if wait:
            self.await_movement(timeout)

    def await_movement(self, timeout: float | None = None) -> None:
        self.log.warning("No waiting. timeout was: %s", timeout)

    def halt(self) -> None:
        self.log.warning("Halt not implemented for %s", self.__class__)

    # @property
    # def filter(self) -> str:
    #     """Get the current filter name."""
    #     return self._filter

    # @filter.setter
    # def filter(self, filter_name: str) -> None:
    #     """Set the filter by sending a pulse on the corresponding DAQ port."""
    #     if filter_name not in self.filters:
    #         msg = f"Filter '{filter_name}' is not a valid option."
    #         raise ValueError(msg)

    #     if filter_name == self._filter:
    #         return

    #     self._set_filter(filter_name=filter_name)

    # def _set_filter(self, filter_name: str) -> None:
    #     self.log.info(f"Switching filter to '{filter_name}'...")

    #     port_to_pulse = self.filters[filter_name]

    #     try:
    #         # Use the high-level pulse method on the DAQ interface
    #         self._daq.pulse(pin=port_to_pulse, duration_s=PULSE_DURATION_S, voltage_v=PULSE_VOLTAGE_V)
    #         self._filter = filter_name
    #         self.log.info(f"Successfully set filter to '{filter_name}'.")
    #     except Exception:
    #         self.log.error(f"Failed to switch filter to '{filter_name}'.", exc_info=True)
    #         raise

    def close(self) -> None:
        """Close the filter wheel device."""
        self.log.info(f"Closing filter wheel {self.uid}.")
