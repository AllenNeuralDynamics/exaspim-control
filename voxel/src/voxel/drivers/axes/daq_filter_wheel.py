"""DAQ-controlled filter wheel driver.

Uses DAQ analog output pulses to trigger filter wheel position changes.
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, final

from voxel.interfaces.axes import DiscreteAxis
from voxel.interfaces.daq import pulse

if TYPE_CHECKING:
    from voxel.interfaces.daq import SpimDaq


# Default pulse parameters - can be overridden in YAML init block
PULSE_VOLTAGE_V = 5.0
PULSE_DURATION_S = 0.05  # 50ms


@final
class DAQFilterWheel(DiscreteAxis):
    """Filter wheel that uses DAQ analog output pulses to switch positions.

    Each filter position is associated with a DAQ pin. When switching to that
    position, a pulse is sent on the corresponding pin to trigger the filter
    wheel controller.

    Example YAML configuration:
        filter_wheel:
            target: voxel.drivers.axes.daq_filter_wheel.DAQFilterWheel
            init:
                uid: filter_wheel_main
                daq: pcie-6738
                slots:
                    0: "500LP"
                    1: "535/70m"
                    2: "600LP"
                    3: "Empty"
                ports:
                    "500LP": ao7
                    "535/70m": ao11
                    "600LP": ao12
                    "Empty": ao13
    """

    def __init__(
        self,
        uid: str,
        daq: "SpimDaq",
        slots: Mapping[int | str, str | None],
        ports: dict[str, str],
        pulse_voltage_v: float = PULSE_VOLTAGE_V,
        pulse_duration_s: float = PULSE_DURATION_S,
    ) -> None:
        """Initialize the DAQ filter wheel.

        Args:
            uid: Unique identifier for this device.
            daq: DAQ device to use for pulse generation.
            slots: Mapping of slot index to filter label.
                   e.g., {0: "500LP", 1: "535/70m", 2: "600LP"}
            ports: Mapping of filter label to DAQ pin.
                   e.g., {"500LP": "ao7", "535/70m": "ao11"}
            pulse_voltage_v: Voltage level for trigger pulse (default: 5V).
            pulse_duration_s: Duration of trigger pulse in seconds (default: 50ms).
        """
        super().__init__(uid=uid, slots=slots)

        self._daq = daq
        self._ports = ports
        self._pulse_voltage_v = pulse_voltage_v
        self._pulse_duration_s = pulse_duration_s
        self._position: int = min(self._labels.keys())
        self._is_moving: bool = False

        # Validate that all labeled slots have corresponding ports
        for slot_idx, label in self._labels.items():
            if label is not None and label not in self._ports:
                self.log.warning(f"Slot {slot_idx} ({label}) has no DAQ port mapping")

        # Home to initial position
        self.home()

        self.log.info(
            f"Initialized DAQ filter wheel: {len(slots)} slots, "
            f"pulse={self._pulse_voltage_v}V for {self._pulse_duration_s * 1000:.0f}ms"
        )

    @property
    def position(self) -> int:
        """Current slot index (0-based)."""
        return self._position

    @property
    def is_moving(self) -> bool:
        """Whether the filter wheel is currently moving."""
        return self._is_moving

    def move(self, slot: int, *, wait: bool = False, timeout: float | None = None) -> None:
        """Move to a slot by sending a pulse on the corresponding DAQ pin.

        Args:
            slot: Target slot index (0-based).
            wait: If True, block until movement is complete.
            timeout: Maximum time to wait in seconds (only used if wait=True).

        Raises:
            ValueError: If slot is out of range or has no DAQ port mapping.
        """
        if slot < 0 or slot >= self.slot_count:
            msg = f"Invalid slot {slot}: valid range is 0..{self.slot_count - 1}"
            raise ValueError(msg)

        label = self._labels.get(slot)
        if label is None:
            self.log.warning(f"Slot {slot} is unlabeled, skipping pulse")
            self._position = slot
            return

        daq_port = self._ports.get(label)
        if daq_port is None:
            msg = f"No DAQ port mapping for slot {slot} ({label})"
            raise ValueError(msg)

        try:
            self._is_moving = True
            self.log.debug(f"Switching to filter '{label}' via {daq_port}")

            # Use the pulse utility from the new DAQ interface
            pulse(
                self._daq,
                pin=daq_port,
                duration_s=self._pulse_duration_s,
                voltage_v=self._pulse_voltage_v,
            )

            self._position = slot
            self.log.info(f"Successfully set filter to '{label}' (slot {slot})")

        except Exception:
            self.log.exception(f"Failed to switch filter to '{label}'")
            raise

        finally:
            self._is_moving = False

        if wait:
            self.await_movement(timeout)

    def home(self, *, wait: bool = False, timeout: float | None = None) -> None:
        """Home the filter wheel to the first slot.

        Args:
            wait: If True, block until movement is complete.
            timeout: Maximum time to wait in seconds (only used if wait=True).
        """
        first_slot = min(self._labels.keys())
        self.move(first_slot, wait=wait, timeout=timeout)

    def halt(self) -> None:
        """Emergency stop - not applicable for pulse-triggered filter wheels."""
        self.log.warning("Halt not implemented for DAQ filter wheel - moves are instantaneous")
        self._is_moving = False

    def await_movement(self, timeout: float | None = None) -> None:
        """Wait until the filter wheel stops moving.

        Since pulse-triggered moves are effectively instantaneous,
        this returns immediately.

        Args:
            timeout: Maximum time to wait in seconds (ignored).
        """
        # Pulse-triggered filter wheels complete movement during the pulse
        # No additional waiting needed

    def close(self) -> None:
        """Close the filter wheel device."""
        self.log.info(f"Closing filter wheel {self.uid}")
