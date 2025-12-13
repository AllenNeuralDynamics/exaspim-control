from voxel.devices.daq.base import VoxelDAQ
from voxel.devices.filterwheel.base import BaseFilterWheel

# These can be made configurable through the device's 'init' block in YAML
PULSE_VOLTAGE_V = 5.0
PULSE_DURATION_S = 0.05  # 50ms


class DAQFilterWheel(BaseFilterWheel):
    """
    A FilterWheel that sends a trigger pulse via a VoxelDAQ device to switch filters.
    """

    def __init__(self, uid: str, filters: dict[str, str], daq: VoxelDAQ):
        """
        Args:
            uid: Unique identifier for this filter wheel.
            filters: A dictionary mapping filter names to the DAQ port to be pulsed.
            daq: An instance of a configured VoxelDAQ device.
        """
        super().__init__(uid=uid)
        self.daq = daq
        self.filters = filters
        first_filter = next(iter(self.filters.keys()))
        self._set_filter(first_filter)
        self._filter: str = first_filter

    @property
    def filter(self) -> str:
        """Get the current filter name."""
        return self._filter

    @filter.setter
    def filter(self, filter_name: str) -> None:
        """Set the filter by sending a pulse on the corresponding DAQ port."""
        if filter_name not in self.filters:
            msg = f"Filter '{filter_name}' is not a valid option."
            raise ValueError(msg)

        if filter_name == self._filter:
            return

        self._set_filter(filter_name=filter_name)

    def _set_filter(self, filter_name: str) -> None:
        self.log.info(f"Switching filter to '{filter_name}'...")

        port_to_pulse = self.filters[filter_name]

        try:
            # Use the high-level pulse method on the DAQ interface
            self.daq.pulse(pin=port_to_pulse, duration_s=PULSE_DURATION_S, voltage_v=PULSE_VOLTAGE_V)
            self._filter = filter_name
            self.log.info(f"Successfully set filter to '{filter_name}'.")
        except Exception:
            self.log.error(f"Failed to switch filter to '{filter_name}'.", exc_info=True)
            raise

    def close(self) -> None:
        """Close the filter wheel device."""
        self.log.info(f"Closing filter wheel {self.uid}.")
