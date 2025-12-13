from enum import StrEnum

import numpy as np
from nidaqmx.constants import AcquisitionType as NiAcqType
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
        return self._inst.channels.channel_names if self._inst.channels else []

    def cfg_samp_clk_timing(self, rate: float, sample_mode: "AcqSampleMode", samps_per_chan: int) -> None:
        """Configure sample clock timing."""
        ni_sample_mode = NiAcqType.FINITE if sample_mode == AcqSampleMode.FINITE else NiAcqType.CONTINUOUS
        self._inst.timing.cfg_samp_clk_timing(rate=rate, sample_mode=ni_sample_mode, samps_per_chan=samps_per_chan)

    def cfg_dig_edge_start_trig(self, trigger_source: str, *, retriggerable: bool) -> None:
        """Configure digital edge start trigger."""
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
        return f"DAQ Device - Uid: {self._uid} - Name: {self._name} - Model: {self.model}"

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

    def pulse(self, pin: str, duration_s: float, voltage_v: float, sample_rate_hz: int = 10000) -> None:
        """Generates a simple finite pulse on a single pin."""
        task_name = f"pulse_{pin}_{self.uid}"
        pin_info = None
        try:
            # 1. Assign pin
            pin_info = self.assign_pin(task_name=task_name, pin=pin)

            # 2. Create and configure task
            self.create_task(task_name)
            self.add_ao_channel(task_name, pin_info.path, f"{pin}_channel")

            num_samples = int(duration_s * sample_rate_hz)

            self.cfg_samp_clk_timing(
                task_name,
                rate=sample_rate_hz,
                sample_mode=AcqSampleMode.FINITE,
                samps_per_chan=num_samples,
            )

            # 3. Write data
            pulse_data = np.full(num_samples, voltage_v)
            self.write(task_name, [pulse_data.tolist()])

            # 4. Start and wait for completion
            task = self._tasks[task_name]
            self.start_task(task_name)
            task.wait_until_done(timeout=duration_s + 1.0)

        finally:
            # 5. Clean up
            if pin_info is not None:
                self.close_task(task_name)

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

    def close(self):
        for task in self._tasks.values():
            task.stop()
            task.close()
