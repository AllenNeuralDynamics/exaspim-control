"""VoxelWriter Protocol definition.

This module defines the VoxelWriter Protocol - the contract that all
voxel writer implementations must satisfy. This uses Python's Protocol
(structural subtyping) rather than ABC (nominal subtyping), allowing
any class with the right methods to be used as a VoxelWriter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

if TYPE_CHECKING:
    import numpy as np

    from .types import StreamStatus, WriterConfig


@runtime_checkable
class VoxelWriter(Protocol):
    """Protocol defining the contract for all voxel writers.

    Any class implementing these methods and properties can be used
    wherever a VoxelWriter is expected, without explicit inheritance.

    Lifecycle:
        1. Create writer with configuration: `writer = SomeWriter(config)`
        2. Use as context manager: `with writer:`
        3. Add frames: `writer.add_frame(frame)`
        4. Monitor progress: `status = writer.get_status()`
        5. Close (automatic with context manager, or explicit: `writer.close()`)

    Example:
        ```python
        config = WriterConfig(
            name="experiment_001",
            path="/data/output",
            frame_count=1000,
            frame_shape=FrameShape(2048, 2048),
            batch_size=128,
            dtype=Dtype.UINT16,
            compression="lz4shuffle",
        )

        with ImarisWriter(config, thread_count=8) as writer:
            for frame in camera.stream():
                writer.add_frame(frame)
                print(writer.get_status().summary())
        ```
    """

    @property
    def cfg(self) -> WriterConfig:
        """Writer configuration.

        Returns:
            The WriterConfig (or subclass) used to configure this writer.
        """
        ...

    @property
    def is_running(self) -> bool:
        """Whether the writer is actively running.

        Returns:
            True if the writer is accepting frames, False otherwise.
        """
        ...

    def add_frame(self, frame: np.ndarray) -> None:
        """Add a single 2D frame to the writer.

        The frame is buffered and written asynchronously. When the buffer
        is full, it is flushed and the next batch begins.

        Args:
            frame: 2D numpy array with shape (height, width) matching
                   the configured frame_shape.

        Raises:
            ValueError: If frame shape doesn't match configuration.
            RuntimeError: If writer is not running or has been closed.
        """
        ...

    def get_status(self) -> StreamStatus:
        """Get a snapshot of the current writer status.

        Returns:
            StreamStatus containing progress, performance metrics,
            and buffer states.
        """
        ...

    def wait_all(self) -> None:
        """Wait for all pending write operations to complete.

        Blocks until all buffered data has been written to storage.
        This is automatically called by close().
        """
        ...

    def close(self) -> None:
        """Close the writer and clean up resources.

        Flushes any remaining buffered data, waits for writes to complete,
        and releases all resources. After calling close(), the writer
        cannot be reused.

        This is automatically called when exiting a context manager.
        """
        ...

    def __enter__(self) -> Self:
        """Enter context manager.

        Returns:
            The writer instance.
        """
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit context manager, ensuring close() is called.

        Args:
            exc_type: Exception type if an exception occurred.
            exc_val: Exception value if an exception occurred.
            exc_tb: Exception traceback if an exception occurred.
        """
        ...
