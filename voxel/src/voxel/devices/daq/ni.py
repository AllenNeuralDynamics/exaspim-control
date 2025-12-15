from enum import StrEnum

import numpy as np
from nidaqmx.constants import AcquisitionType as NiAcqType, Level as NiLevel
from nidaqmx.errors import DaqError
from nidaqmx.system import System as NiSystem
from nidaqmx.system.device import Device as NiDevice
from nidaqmx.task import Task as NiTask
from nidaqmx.task.channels import AOChannel as NiAOChannel

from .base import AcqSampleMode, AOChannelInst, DaqTaskInst, PinInfo, TaskStatus, VoxelDAQ
from .quantity import VoltageRange


class AOChannelWrapper:
    """Wrapper for analog output channel instances in Voxel NiDAQ."""

    def __init__(self, inst: NiAOChannel) -> None:
        self._inst = inst

    @property
    def name(self) -> str:
        return self._inst.name


class NiDAQTaskWrapper(DaqTaskInst):
    def __init__(self, name: str) -> None:
        self._inst = NiTask(name)
        self._status = TaskStatus.IDLE

    @property
    def name(self) -> str:
        return self._inst.name

    @property
    def status(self) -> TaskStatus:
        return self._status

    def write(self, data: np.ndarray) -> int:
        """Write data to the DAQ task."""
        return self._inst.write(data)

    def start(self) -> None:
        """Start the DAQ task."""
        self._inst.start()
        self._status = TaskStatus.RUNNING

    def stop(self) -> None:
        """Stop the DAQ task."""
        self._inst.stop()
        self._status = TaskStatus.IDLE

    def wait_until_done(self, timeout: float) -> None:
        """Wait until the task is done or the timeout is reached."""
        self._inst.wait_until_done(timeout=timeout)

    def close(self) -> None:
        """Close the DAQ task."""
        self._inst.close()
        self._status = TaskStatus.IDLE

    def add_ao_channel(self, path: str, name: str) -> "AOChannelInst":
        """Add an analog output voltage channel."""
        channel_inst = self._inst.ao_channels.add_ao_voltage_chan(path, name)
        return AOChannelWrapper(channel_inst)

    def get_channel_names(self) -> list[str]:
        """Get the names of the channels in the task."""
        try:
            return self._inst.channels.channel_names if self._inst.channels else []
        except DaqError:
            return []

    def cfg_samp_clk_timing(self, rate: float, sample_mode: "AcqSampleMode", samps_per_chan: int) -> None:
        """Configure sample clock timing."""
        ni_sample_mode = NiAcqType.FINITE if sample_mode == AcqSampleMode.FINITE else NiAcqType.CONTINUOUS
        self._inst.timing.cfg_samp_clk_timing(rate=rate, sample_mode=ni_sample_mode, samps_per_chan=samps_per_chan)

    def cfg_dig_edge_start_trig(self, trigger_source: str, *, retriggerable: bool) -> None:
        """Configure digital edge start trigger."""
        self._inst.triggers.start_trigger.cfg_dig_edge_start_trig(trigger_source=trigger_source)
        self._inst.triggers.start_trigger.retriggerable = retriggerable


class _NiCOTaskWrapper(DaqTaskInst):
    """Wrapper for counter output tasks (simpler than AO tasks)."""

    def __init__(self, task: NiTask) -> None:
        self._inst = task
        self._status = TaskStatus.IDLE

    @property
    def name(self) -> str:
        return self._inst.name

    @property
    def status(self) -> TaskStatus:
        return self._status

    def write(self, data: np.ndarray) -> int:
        """CO tasks don't support write - raise error."""
        raise NotImplementedError("Counter output tasks do not support write operations")

    def start(self) -> None:
        self._inst.start()
        self._status = TaskStatus.RUNNING

    def stop(self) -> None:
        self._inst.stop()
        self._status = TaskStatus.IDLE

    def wait_until_done(self, timeout: float) -> None:
        self._inst.wait_until_done(timeout=timeout)

    def close(self) -> None:
        self._inst.close()
        self._status = TaskStatus.IDLE

    def add_ao_channel(self, path: str, name: str) -> "AOChannelInst":
        raise NotImplementedError("Counter output tasks do not support AO channels")

    def get_channel_names(self) -> list[str]:
        try:
            return self._inst.channels.channel_names if self._inst.channels else []
        except DaqError:
            return []

    def cfg_samp_clk_timing(self, rate: float, sample_mode: "AcqSampleMode", samps_per_chan: int) -> None:
        raise NotImplementedError("Counter output tasks use implicit timing")

    def cfg_dig_edge_start_trig(self, trigger_source: str, *, retriggerable: bool) -> None:
        self._inst.triggers.start_trigger.cfg_dig_edge_start_trig(trigger_source=trigger_source)
        self._inst.triggers.start_trigger.retriggerable = retriggerable


class NiDaqModel(StrEnum):
    """Enumeration of supported NI DAQ models."""

    NI6738 = "PCIe-6738"
    NI6739 = "PCIe-6739"
    OTHER = "other"


class NiDaq(VoxelDAQ):
    def __init__(self, uid: str, dev: str) -> None:
        self._name = dev
        self.system = NiSystem.local()
        self._inst, self.model = self._connect(name=self._name)

        self.channel_map: dict[str, PinInfo] = {}
        self.assigned_channels: set[str] = set()

        self._initialize_channel_mappings()
        super().__init__(uid)

    def __repr__(self) -> str:
        return f"DAQ Device - Uid: {self.uid} - Name: {self._name} - Model: {self.model}"

    def _connect(self, name: str) -> tuple[NiDevice, NiDaqModel]:
        """Connect to DAQ device."""
        try:
            nidaq = NiDevice(name)
            nidaq.reset_device()
            if "6738" in nidaq.product_type:
                model = NiDaqModel.NI6738
            elif "6739" in nidaq.product_type:
                model = NiDaqModel.NI6739
            else:
                model = NiDaqModel.OTHER
                self.log.warning(f"Daq Device: {nidaq.product_type} might not be fully supported.")
        except DaqError as e:
            err_msg = f"Unable to connect to DAQ device {name}: {e}"
            raise RuntimeError(err_msg) from e
        else:
            return nidaq, model

    def _initialize_channel_mappings(self) -> None:
        """Initialize comprehensive channel mappings."""
        # task_name is a placeholder here, it will be updated on assignment
        placeholder_task = "unassigned"

        # Handle counter channels
        for co_path in self._inst.co_physical_chans.channel_names:
            co_name = co_path.split("/")[-1].upper()
            self.channel_map[co_name] = PinInfo(pin=co_name, path=co_path, task_name=placeholder_task)

        # Handle analog channels
        for ao_path in self._inst.ao_physical_chans.channel_names:
            ao_name = ao_path.split("/")[-1].upper()
            self.channel_map[ao_name] = PinInfo(pin=ao_name, path=ao_path, task_name=placeholder_task)

        # Handle digital channels and PFI
        def generate_dio_names(dio_path: str) -> tuple[str, str | None]:
            dio_path_parts = dio_path.upper().split("/")
            port_num = int(dio_path_parts[-2].replace("PORT", ""))
            line_num = int(dio_path_parts[-1].replace("LINE", ""))
            pfi_name = f"PFI{(port_num - 1) * 8 + line_num}" if port_num > 0 else None
            line_name = f"P{port_num}.{line_num}"
            return line_name, pfi_name

        for dio_path in self._inst.do_lines.channel_names:
            dio_name, pfi_name = generate_dio_names(dio_path)

            info = PinInfo(pin=dio_name, path=dio_path, pfi=pfi_name, task_name=placeholder_task)

            self.channel_map[dio_name] = info
            if pfi_name:
                self.channel_map[pfi_name] = self.channel_map[dio_name]

    def _create_task_inst(self, task_name: str) -> "DaqTaskInst":
        """Create a new NiDAQTaskWrapper instance."""
        return NiDAQTaskWrapper(task_name)

    def get_pfi_path(self, pin: str | PinInfo) -> str:
        """Get the PFI path for a given pin."""
        info = self.channel_map.get(pin.upper()) if isinstance(pin, str) else pin
        if info and info.pfi:
            return f"/{self._name}/{info.pfi}"
        err_msg = f"Pin {pin} does not have a PFI path or is not valid."
        raise ValueError(err_msg)

    @property
    def device_name(self) -> str:
        """Get the NI-DAQmx device name."""
        return self._name

    @property
    def ao_voltage_range(self) -> "VoltageRange":
        """Get the analog output voltage range."""
        try:
            v_range = self._inst.ao_voltage_rngs
            v_min = v_range[0]
            vmax = v_range[1]
        except (DaqError, ImportError):
            v_min = -5.0
            vmax = 5.0
            self.log.warning("Failed to retrieve voltage range, using default -5V to 5V.")
        return VoltageRange(min=v_min, max=vmax)

    @property
    def available_pins(self) -> list[str]:
        """Get list of available (unassigned) pin names."""
        available = []
        for pin_name, info in self.channel_map.items():
            if info.path not in self.assigned_channels:
                available.append(pin_name)
        return sorted(set(available))

    @property
    def assigned_pins(self) -> dict[str, PinInfo]:
        """Get dictionary of currently assigned pins (name -> info)."""
        assigned = {}
        for info in self.channel_map.values():
            # Use the primary pin name (from PinInfo) as key
            if info.path in self.assigned_channels and info.pin not in assigned:
                assigned[info.pin] = info
        return assigned

    def assign_pin(self, task_name: str, pin: str) -> PinInfo:
        """Assign a pin and return its physical name and PFI name (if applicable).

        Args:
            pin (str): The pin name to assign.

        Returns:
            PinInfo: A ChannelInfo object containing the channel information.

        Raises:
            ValueError: If the pin name is not valid or already assigned.

        """
        pin = pin.upper()
        if pin not in self.channel_map:
            err = f"Pin {pin} is not a valid pin name"
            raise ValueError(err)

        info = self.channel_map[pin]
        # Check if it's assigned to another task
        if info.path in self.assigned_channels and info.task_name != task_name:
            names = [n for n in (info.pin, info.pfi) if n]
            other_str = f" (also known as {', '.join(names)})" if names else ""
            err_msg = f"Pin {pin}{other_str} is already assigned to task '{info.task_name}'"
            raise ValueError(err_msg)

        # Create a new PinInfo with the correct task_name
        new_info = info.model_copy(update={"task_name": task_name})
        self.channel_map[pin] = new_info
        if new_info.pfi:
            self.channel_map[new_info.pfi] = new_info

        self.assigned_channels.add(new_info.path)
        return new_info

    def release_pin(self, pin: PinInfo) -> bool:
        """Release a previously assigned pin."""
        if pin.path in self.assigned_channels:
            self.assigned_channels.remove(pin.path)

            # Reset task_name to placeholder
            unassigned_info = pin.model_copy(update={"task_name": "unassigned"})
            self.channel_map[pin.pin] = unassigned_info
            if pin.pfi:
                self.channel_map[pin.pfi] = unassigned_info
            return True
        return False

    def release_pins_for_task(self, task_name: str) -> None:
        """Release all pins that were assigned to a specific task."""
        # Find all pins assigned to this task
        pins_to_release = [info for info in self.channel_map.values() if info.task_name == task_name]
        for pin_info in pins_to_release:
            self.release_pin(pin_info)

    def _discover_pins(self) -> frozenset[str]:
        """Use nidaqmx to find all physical channels on the device.
        We only return the terminal name (e.g., 'ao0'), not the full path ('Dev3/ao0').
        """
        # This can be a comprehensive list of all channel types
        ao_pins = {ch.name.split("/")[-1] for ch in self._inst.ao_physical_chans}
        do_pins = {ch.name.split("/")[-1] for ch in self._inst.do_lines}
        di_pins = {ch.name.split("/")[-1] for ch in self._inst.di_lines}
        pfi_pins = {f"pfi{i}" for i in range(16)}  # Example for PFI lines

        return frozenset(ao_pins | do_pins | di_pins | pfi_pins)

    def create_co_pulse_task(
        self,
        task_name: str,
        counter: str,
        frequency_hz: float,
        duty_cycle: float = 0.5,
        pulses: int | None = None,
        output_pin: str | None = None,
    ) -> str:
        """Create a counter output pulse task (one-shot create + configure).

        Args:
            task_name: Unique name for the task
            counter: Counter channel to use (e.g., "ctr0")
            frequency_hz: Pulse frequency in Hz
            duty_cycle: Duty cycle (0.0 to 1.0), default 0.5
            pulses: Number of pulses to generate, None for continuous
            output_pin: Pin name to route the pulse output to (e.g., "PFI0")

        Returns:
            The task name
        """
        if task_name in self._tasks:
            msg = f"Task '{task_name}' already exists"
            raise ValueError(msg)

        # Assign the counter pin
        counter_pin_info = self.assign_pin(task_name, counter)

        # Create NI task directly (not using wrapper since CO channels differ)
        ni_task = NiTask(task_name)

        try:
            # Add counter output pulse channel
            co_chan = ni_task.co_channels.add_co_pulse_chan_freq(
                counter=counter_pin_info.path,
                freq=frequency_hz,
                duty_cycle=duty_cycle,
                idle_state=NiLevel.LOW,
            )

            # Route output to specified pin if provided
            if output_pin:
                output_terminal = self.get_pfi_path(output_pin)
                co_chan.co_pulse_term = output_terminal
                self.log.debug(f"Routed CO output to {output_terminal}")

            # Configure timing
            if pulses is None:
                # Continuous mode
                ni_task.timing.cfg_implicit_timing(sample_mode=NiAcqType.CONTINUOUS)
            else:
                # Finite mode
                ni_task.timing.cfg_implicit_timing(
                    sample_mode=NiAcqType.FINITE,
                    samps_per_chan=pulses,
                )

            # Wrap in a simple task holder
            wrapper = _NiCOTaskWrapper(ni_task)
            self._tasks[task_name] = wrapper
            self._task_pins[task_name] = [counter_pin_info]

            self.log.info(f"Created CO pulse task '{task_name}': {frequency_hz}Hz, duty={duty_cycle}")
            return task_name

        except DaqError as e:
            ni_task.close()
            self.release_pin(counter_pin_info)
            err_msg = f"Failed to create CO pulse task '{task_name}': {e}"
            raise RuntimeError(err_msg) from e

    def close(self):
        for task in self._tasks.values():
            task.stop()
            task.close()
