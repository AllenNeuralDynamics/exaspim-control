"""Writer engine components for buffered, multiprocessing-based writers.

This module provides reusable components for building high-throughput writers
using composition rather than inheritance.

Components:
    BufferManager: Manages SharedDoubleBuffer lifecycle and frame buffering
    WriterProcess: Manages subprocess lifecycle and batch processing loop
"""

from __future__ import annotations

import time
from multiprocessing import Event, Process, Value
from multiprocessing.shared_memory import SharedMemory
from typing import Protocol

import numpy as np

from .types import BufferStage, BufferStatus, FrameShape


class SharedDoubleBuffer:
    """
    A single-producer-single-consumer multi-process double buffer\n
    implemented as a numpy ndarray.

    Args:
        shape: shape of the buffer
        dtype: data type of the buffer

    .. code-block: python

        dbl_buf = SharedDoubleBuffer((8, 320, 240), 'uint16')

        dbl_buf.write_mem[0][:,:] = np.zeros((320, 240), dtype='uint16')
        dbl_buf.write_mem[1][:,:] = np.zeros((320, 240), dtype='uint16')
        dbl_buf.write_mem[2][:,:] = np.zeros((320, 240), dtype='uint16')

        # When finished, switch buffers.
        # Note, user must apply flow control scheme to ensure another
        # process is done using the read_buf before we switch it.
        dbl_buf.toggle_buffers() # read_buf and write_buf have switched places.
    """

    def __init__(self, shape: tuple[int, ...], dtype: str) -> None:
        """
        Initialize the SharedDoubleBuffer.

        :param shape: Shape of the buffer
        :type shape: tuple
        :param dtype: Data type of the buffer
        :type dtype: str
        """
        # overflow errors without casting for large datasets
        nbytes = int(np.prod(shape, dtype=np.int64) * np.dtype(dtype).itemsize)
        self.mem_blocks = [
            SharedMemory(create=True, size=nbytes),
            SharedMemory(create=True, size=nbytes),
        ]
        # attach numpy array references to shared memory.
        self.read_buf = np.ndarray(shape, dtype=dtype, buffer=self.mem_blocks[0].buf)
        self.write_buf = np.ndarray(shape, dtype=dtype, buffer=self.mem_blocks[1].buf)
        # attach references to the names of the memory locations.
        self.read_buf_mem_name = self.mem_blocks[0].name
        self.write_buf_mem_name = self.mem_blocks[1].name
        # save values for querying later.
        self.dtype = dtype
        self.shape = shape
        self.nbytes = nbytes
        # create flag to indicate if data has been read out from the read buf.
        self.is_read = Event()
        self.is_read.clear()
        # initialize buffer index
        self.buffer_index = -1

    def toggle_buffers(self) -> None:
        """
        Switch read and write references and the locations of their shared\n
        memory.
        """
        # reset buffer index
        self.buffer_index = -1
        # toggle who acts as read buf and write buf.
        tmp = self.read_buf
        self.read_buf = self.write_buf
        self.write_buf = tmp
        # do the same thing with the shared memory location names
        tmp = self.read_buf_mem_name
        self.read_buf_mem_name = self.write_buf_mem_name
        self.write_buf_mem_name = tmp

    def add_image(self, image: np.ndarray) -> None:
        """Add an image into the buffer at the correct index."""
        self.write_buf[self.buffer_index + 1] = image
        self.buffer_index += 1

    def get_last_image(self) -> np.ndarray:
        """
        Get the last image from the buffer.

        :return: Last image from the buffer
        :rtype: numpy.ndarray
        """
        if self.buffer_index == -1:
            # buffer just switched, grab last image from read buffer
            return self.read_buf[-1]
        # return the image from the write buffer
        return self.write_buf[self.buffer_index]

    def close_and_unlink(self) -> None:
        """Shared memory cleanup; call when done using this object."""
        for mem in self.mem_blocks:
            mem.close()
            mem.unlink()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Cleanup called automatically if opened using a `with` statement."""
        self.close_and_unlink()


class BatchProcessor(Protocol):
    """Protocol for batch processing callbacks."""

    def initialize(self) -> None:
        """Initialize format-specific writer (called in subprocess)."""
        ...

    def process_batch(self, batch_data: np.ndarray, batch_idx: int) -> None:
        """Process a batch of frames (called in subprocess)."""
        ...

    def finalize(self) -> None:
        """Finalize and cleanup (called in subprocess)."""
        ...


class BufferManager:
    """Manages SharedDoubleBuffer lifecycle and frame buffering.

    This component encapsulates:
    - Buffer allocation and cleanup
    - Frame addition with automatic buffer switching
    - Buffer state tracking

    Example:
        ```python
        buffer_mgr = BufferManager(
            batch_size=128,
            frame_shape=FrameShape(2048, 2048),
            dtype="uint16",
        )

        buffer_mgr.add_frame(frame)

        if buffer_mgr.should_switch:
            buffer_mgr.switch_buffers()

        buffer_mgr.close()
        ```
    """

    def __init__(
        self,
        batch_size: int,
        frame_shape: FrameShape,
        dtype: str = "uint16",
    ) -> None:
        """Initialize the buffer manager.

        Args:
            batch_size: Number of frames per batch
            frame_shape: Shape of each frame (y, x)
            dtype: Data type for buffer
        """

        self._batch_size = batch_size
        self._frame_shape = frame_shape
        self._dtype = dtype
        self._frames_in_buffer = 0

        batch_shape = (batch_size, frame_shape.y, frame_shape.x)
        self._buffer = SharedDoubleBuffer(batch_shape, dtype)

    @property
    def batch_size(self) -> int:
        """Number of frames per batch."""
        return self._batch_size

    @property
    def frames_in_buffer(self) -> int:
        """Number of frames currently in the write buffer."""
        return self._buffer.num_frames.value

    @property
    def write_buffer_idx(self) -> int:
        """Index of the current write buffer."""
        return self._buffer.write_mem_block_idx.value

    @property
    def read_buffer_idx(self) -> int:
        """Index of the current read buffer."""
        return self._buffer.read_mem_block_idx.value

    @property
    def is_full(self) -> bool:
        """Whether the current write buffer is full."""
        return self.frames_in_buffer >= self._batch_size

    def add_frame(self, frame: np.ndarray) -> None:
        """Add a frame to the write buffer.

        Args:
            frame: 2D numpy array to add
        """
        self._buffer.add_frame(frame)

    def switch_buffers(self) -> None:
        """Toggle read/write buffers."""
        self._buffer.toggle_buffers()

    def reset_frame_count(self) -> None:
        """Reset the frame count for the current buffer."""
        self._buffer.num_frames.value = 0

    def get_read_batch(self) -> np.ndarray:
        """Get the current read buffer as a numpy array.

        Returns:
            Numpy array view of the read buffer with actual frame count
        """
        mem_block = self._buffer.mem_blocks[self.read_buffer_idx]
        shape = (self._buffer.num_frames.value, *self._buffer.shape[1:])
        return np.ndarray(shape, dtype=self._dtype, buffer=mem_block.buf)

    def get_buffer_status(self, slot_idx: int, current_batch: int) -> BufferStatus:
        """Get status for a specific buffer slot.

        Args:
            slot_idx: Buffer slot index (0 or 1)
            current_batch: Current batch number

        Returns:
            BufferStatus for the slot
        """
        is_write = slot_idx == self.write_buffer_idx
        return BufferStatus(
            batch_idx=current_batch if is_write else max(0, current_batch - 1),
            stage=BufferStage.COLLECTING if is_write else BufferStage.IDLE,
            filled=self.frames_in_buffer if is_write else 0,
            capacity=self._batch_size,
        )

    def close(self) -> None:
        """Close and cleanup the buffer."""
        if self._buffer:
            self._buffer.close_and_unlink()


class WriterProcess:
    """Manages subprocess lifecycle for batch processing.

    This component encapsulates:
    - Subprocess creation and management
    - Synchronization events (running, needs_processing)
    - Batch processing loop with metrics
    - Graceful shutdown

    Example:
        ```python
        process = WriterProcess(
            name="MyWriter",
            processor=my_batch_processor,
            buffer_mgr=buffer_mgr,
        )

        process.start()

        # Signal batch ready
        process.signal_batch_ready()

        # Wait and stop
        process.wait_all()
        process.stop()
        ```
    """

    def __init__(
        self,
        name: str,
        processor: BatchProcessor,
        buffer_mgr: BufferManager,
        frame_count: int,
        log_queue=None,
    ) -> None:
        """Initialize the writer process manager.

        Args:
            name: Process name for identification
            processor: BatchProcessor implementation with initialize/process/finalize
            buffer_mgr: BufferManager instance to read batches from
            frame_count: Total expected frame count
            log_queue: Optional logging queue for subprocess
        """
        self._name = name
        self._processor = processor
        self._buffer_mgr = buffer_mgr
        self._frame_count = frame_count
        self._log_queue = log_queue

        # Synchronization primitives (shared between processes)
        self._is_running = Event()
        self._needs_processing = Event()

        # Metrics (shared between processes)
        self._frames_added = Value("i", 0)
        self._frames_processed = Value("i", 0)
        self._batch_count = Value("i", 0)
        self._avg_rate = Value("d", 0.0)
        self._avg_fps = Value("d", 0.0)

        # Process handle
        self._proc: Process | None = None
        self._start_time = 0.0

    @property
    def is_running(self) -> bool:
        """Whether the subprocess is running."""
        return self._is_running.is_set()

    @property
    def frames_added(self) -> int:
        """Number of frames added."""
        return self._frames_added.value

    @frames_added.setter
    def frames_added(self, value: int) -> None:
        self._frames_added.value = value

    @property
    def frames_processed(self) -> int:
        """Number of frames processed."""
        return self._frames_processed.value

    @property
    def batch_count(self) -> int:
        """Number of batches processed."""
        return self._batch_count.value

    @property
    def avg_rate_gbs(self) -> float:
        """Average write rate in GB/s."""
        return self._avg_rate.value

    @property
    def avg_fps(self) -> float:
        """Average frames per second."""
        return self._avg_fps.value

    @property
    def elapsed_time(self) -> float:
        """Elapsed time since start."""
        if self._start_time == 0:
            return 0.0
        return time.perf_counter() - self._start_time

    def start(self) -> None:
        """Start the writer subprocess."""
        self._start_time = time.perf_counter()
        self._is_running.set()
        self._needs_processing.clear()
        self._frames_added.value = 0
        self._frames_processed.value = 0
        self._batch_count.value = 0
        self._avg_rate.value = 0.0
        self._avg_fps.value = 0.0

        self._proc = Process(name=self._name, target=self._run_loop)
        self._proc.start()

    def signal_batch_ready(self) -> None:
        """Signal that a batch is ready for processing.

        Blocks until any previous processing is complete, then signals.
        """
        # Wait for previous processing to complete
        while self._needs_processing.is_set():
            time.sleep(0.001)

        # Switch buffers and signal
        self._buffer_mgr.switch_buffers()
        self._needs_processing.set()

    def wait_processing_started(self) -> None:
        """Wait for the subprocess to start processing current batch."""
        while not self._needs_processing.is_set():
            time.sleep(0.001)

    def wait_all(self) -> None:
        """Wait for all pending batches to be processed."""
        while self._needs_processing.is_set() or self.frames_added > self.frames_processed:
            time.sleep(0.1)

    def stop(self) -> None:
        """Stop the subprocess and wait for it to finish."""
        self.wait_all()
        self._is_running.clear()

        if self._proc and self._proc.is_alive():
            self._proc.join(timeout=30)
            if self._proc.is_alive():
                self._proc.terminate()

    def _run_loop(self) -> None:
        """Main subprocess loop (runs in separate process)."""
        from voxel.utils.log import VoxelLogging

        # Redirect logging if queue provided
        if self._log_queue:
            import logging

            logger = logging.getLogger(self._name)
            VoxelLogging.redirect([logger], self._log_queue)

        # Initialize format-specific writer
        self._processor.initialize()

        # Main processing loop
        while self._is_running.is_set():
            if self._needs_processing.is_set():
                batch_data = self._buffer_mgr.get_read_batch()
                self._process_batch_timed(batch_data)
                self._needs_processing.clear()
                self._buffer_mgr.reset_frame_count()
            else:
                time.sleep(0.05)

        # Finalize
        self._processor.finalize()

    def _process_batch_timed(self, batch_data: np.ndarray) -> None:
        """Process a batch with timing and metrics."""
        batch_start = time.perf_counter()

        self._batch_count.value += 1
        self._processor.process_batch(batch_data, self._batch_count.value)

        batch_end = time.perf_counter()
        self._frames_processed.value += batch_data.shape[0]

        # Calculate metrics
        time_taken = batch_end - batch_start
        if time_taken > 0:
            data_size_gb = batch_data.nbytes / (1024 * 1024 * 1024)
            rate_gbs = data_size_gb / time_taken
            rate_fps = batch_data.shape[0] / time_taken

            # Update rolling averages
            n = self._batch_count.value
            self._avg_rate.value = (self._avg_rate.value * (n - 1) + rate_gbs) / n
            self._avg_fps.value = (self._avg_fps.value * (n - 1) + rate_fps) / n
