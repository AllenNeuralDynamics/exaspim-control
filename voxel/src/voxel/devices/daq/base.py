from abc import abstractmethod

from voxel.devices.base import VoxelDevice


class BaseDAQ(VoxelDevice):
    """Base class for DAQ devices."""

    @abstractmethod
    def add_task(self, task_type: str, pulse_count: int | None = None) -> None:
        """
        Add a task to the DAQ.

        :param task_type: Type of the task ('ao', 'co', 'do')
        :type task_type: str
        :param pulse_count: Number of pulses for the task, defaults to None
        :type pulse_count: int, optional
        """

    @abstractmethod
    def generate_waveforms(self, task_type: str, wavelength: str) -> None:
        """
        Generate waveforms for the task.

        :param task_type: Type of the task ('ao', 'do')
        :type task_type: str
        :param wavelength: Wavelength for the waveform
        :type wavelength: str
        """

    @abstractmethod
    def write_ao_waveforms(self) -> None:
        """
        Write analog output waveforms to the DAQ.
        """

    @abstractmethod
    def write_do_waveforms(self) -> None:
        """
        Write digital output waveforms to the DAQ.
        """

    @abstractmethod
    def plot_waveforms_to_pdf(self) -> None:
        """
        Plot waveforms and optionally save to a PDF.
        """

    @abstractmethod
    def start(self) -> None:
        """
        Start all tasks.
        """

    @abstractmethod
    def stop(self) -> None:
        """
        Stop all tasks.
        """

    @abstractmethod
    def close(self) -> None:
        """
        Close all tasks.
        """

    @abstractmethod
    def restart(self) -> None:
        """
        Restart all tasks.
        """

    @abstractmethod
    def wait_until_done_all(self, timeout: float = 1.0) -> None:
        """
        Wait until all tasks are done.

        :param timeout: Timeout in seconds, defaults to 1.0
        :type timeout: float, optional
        """

    @abstractmethod
    def is_finished_all(self) -> bool:
        """
        Check if all tasks are finished.

        :return: True if all tasks are finished, False otherwise
        :rtype: bool
        """
