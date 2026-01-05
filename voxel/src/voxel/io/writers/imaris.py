"""ImarisWriter - Writer for Imaris .ims files.

This module provides a writer for voxel data that outputs to Imaris .ims format,
implementing the VoxelWriter Protocol using composition.
"""

from __future__ import annotations

import multiprocessing as mp
from datetime import UTC, datetime
from enum import Enum
from math import ceil
from pathlib import Path
from typing import Self

import numpy as np
from ome_types.model import PixelType
from PyImarisWriter import PyImarisWriter as imaris  # noqa: N813

from .engine import BufferManager, WriterProcess
from .types import FrameShape, StreamMetrics, StreamStatus, VolumeShape, WriterConfig


class ImarisCompression(Enum):
    """Compression algorithms supported by Imaris writer."""

    LZ4SHUFFLE = imaris.eCompressionAlgorithmShuffleLZ4
    NONE = imaris.eCompressionAlgorithmNone


class ImarisProgressChecker(imaris.CallbackClass):
    """Adapter to map VoxelWriter progress to ImarisWriter progress callback."""

    def __init__(self, writer: ImarisWriter) -> None:
        self.writer = writer

    def RecordProgress(self, progress: float, total_bytes_written: int) -> None:  # noqa: N802
        """Called by ImarisWriter SDK to report progress."""
        self.writer._imaris_progress = progress


class ImarisWriter:
    """Writer for voxel data that outputs to Imaris .ims format.

    Implements the VoxelWriter Protocol using composition with
    BufferManager and WriterProcess components.

    Example:
        ```python
        from voxel.io.writers import ImarisWriter, WriterConfig, FrameShape

        cfg = WriterConfig(
            name="experiment_001",
            path="/data/output",
            frame_count=1000,
            frame_shape=FrameShape(2048, 2048),
            batch_size=128,
            compression="lz4shuffle",
        )

        with ImarisWriter(cfg, thread_count=8) as writer:
            for frame in camera.stream():
                writer.add_frame(frame)
                print(writer.get_status().summary())
        ```
    """

    # Class constants
    DEFAULT_THREAD_COUNT = mp.cpu_count()
    DEFAULT_XY_BLOCK_SIZE = 256

    def __init__(self, cfg: WriterConfig, *, thread_count: int | None = None) -> None:
        """Initialize the ImarisWriter.

        Args:
            cfg: Writer configuration specifying output path, dimensions, etc.
            thread_count: Number of writer threads (None = auto, uses cpu_count)
        """
        from voxel.utils.log import VoxelLogging

        self._cfg = cfg
        self.log = VoxelLogging.get_logger(obj=self)
        self._log_queue = VoxelLogging.get_queue()

        # Map compression string to enum
        compression_map = {
            "lz4shuffle": ImarisCompression.LZ4SHUFFLE,
            "none": ImarisCompression.NONE,
        }
        self._compression = compression_map.get(
            cfg.compression.lower() if cfg.compression else "lz4shuffle",
            ImarisCompression.LZ4SHUFFLE,
        )

        # Derive xy_block_size from chunk_shape if provided, else default
        self._xy_block_size = cfg.chunk_shape.y if cfg.chunk_shape else self.DEFAULT_XY_BLOCK_SIZE
        self._thread_count = thread_count or self.DEFAULT_THREAD_COUNT

        # Imaris-specific state
        self._block_size = VolumeShape(
            z=cfg.batch_size,
            y=self._xy_block_size,
            x=self._xy_block_size,
        )
        self._output_file = Path(cfg.path) / f"{cfg.name}.ims"
        self._imaris_progress = 0.0
        self._z_blocks_written = 0

        # Imaris SDK objects (initialized in subprocess)
        self._image_converter: imaris.ImageConverter | None = None
        self._blocks_per_batch: imaris.ImageSize | None = None
        self._callback_class = ImarisProgressChecker(self)

        # Setup output directory
        output_dir = Path(cfg.path)
        if not output_dir.exists():
            output_dir.mkdir(parents=True, exist_ok=True)
            self.log.warning("Created output directory: %s", output_dir)

        # Compose components
        self._buffer = BufferManager(
            batch_size=cfg.batch_size,
            frame_shape=cfg.frame_shape,
            dtype="uint16",
        )

        self._process = WriterProcess(
            name=f"ImarisWriter-{cfg.name}",
            processor=self,  # ImarisWriter implements BatchProcessor
            buffer_mgr=self._buffer,
            frame_count=cfg.frame_count,
            log_queue=self._log_queue,
        )

        # Performance tracking
        self._metrics: StreamMetrics | None = None

        # Start the writer
        self._start()

    @property
    def cfg(self) -> WriterConfig:
        """Writer configuration."""
        return self._cfg

    @property
    def is_running(self) -> bool:
        """Whether the writer is actively running."""
        return self._process.is_running

    @property
    def pixel_type(self) -> PixelType:
        """Pixel type for the written data."""
        return PixelType.UINT16

    @property
    def frames_added(self) -> int:
        """Number of frames added to the writer."""
        return self._process.frames_added

    @property
    def frames_processed(self) -> int:
        """Number of frames processed (written)."""
        return self._process.frames_processed

    @property
    def batch_count(self) -> int:
        """Number of batches processed."""
        return self._process.batch_count

    def _start(self) -> None:
        """Start the writer subprocess."""
        frame_bytes = self._cfg.frame_shape.y * self._cfg.frame_shape.x * 2
        self._metrics = StreamMetrics(frame_bytes)

        self._process.start()

        self.log.info(
            "Started ImarisWriter: %s frames, batch_size=%d, output=%s",
            self._cfg.frame_count,
            self._cfg.batch_size,
            self._output_file,
        )

    def add_frame(self, frame: np.ndarray) -> None:
        """Add a single 2D frame to the writer.

        Args:
            frame: 2D numpy array with shape matching frame_shape.

        Raises:
            RuntimeError: If writer is not running or has been closed.
        """
        if not self.is_running:
            msg = "Cannot add frame: writer is not running"
            raise RuntimeError(msg)

        self._buffer.add_frame(frame)
        self._process.frames_added += 1

        if self._metrics:
            self._metrics.tick()

        is_last_frame = self.frames_added == self._cfg.frame_count
        buffer_full = self._buffer.is_full

        if buffer_full or is_last_frame:
            self._process.signal_batch_ready()

        if is_last_frame:
            self.log.info("Added last frame %d. Waiting for processing...", self.frames_added)
            self._process.wait_all()

    def get_status(self) -> StreamStatus:
        """Get a snapshot of the current writer status.

        Returns:
            StreamStatus with progress and performance metrics.
        """
        frames_remaining = self._cfg.frame_count - self.frames_added

        # Estimate remaining time
        estimated_remaining = None
        if self._metrics and self._metrics.fps > 0 and frames_remaining > 0:
            estimated_remaining = frames_remaining / self._metrics.fps

        # Buffer status
        buffers = {i: self._buffer.get_buffer_status(i, self.batch_count) for i in range(2)}

        return StreamStatus(
            fps=self._metrics.fps if self._metrics else 0.0,
            fps_inst=self._metrics.fps_inst if self._metrics else 0.0,
            throughput_gbs=self._process.avg_rate_gbs,
            throughput_gbs_inst=self._process.avg_rate_gbs,
            frames_acquired=self.frames_added,
            total_frames=self._cfg.frame_count,
            frames_remaining=frames_remaining,
            current_batch=self.batch_count,
            total_batches=self._cfg.num_batches,
            current_slot=self._buffer.write_buffer_idx,
            buffers=buffers,
            elapsed_time=self._process.elapsed_time,
            estimated_remaining=estimated_remaining,
        )

    def wait_all(self) -> None:
        """Wait for all pending write operations to complete."""
        self._process.wait_all()

    def close(self) -> None:
        """Close the writer and clean up resources."""
        if not self.is_running:
            return

        self._process.stop()
        self._buffer.close()

        self.log.info(
            "Closed ImarisWriter. Frames: %d/%d, Avg: %.2f GB/s",
            self.frames_processed,
            self._cfg.frame_count,
            self._process.avg_rate_gbs,
        )

    def __enter__(self) -> Self:
        """Enter context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit context manager, ensuring close() is called."""
        self.close()

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"ImarisWriter("
            f"name={self._cfg.name!r}, "
            f"frames={self.frames_added}/{self._cfg.frame_count}, "
            f"running={self.is_running})"
        )

    # =========================================================================
    # BatchProcessor Protocol implementation (called in subprocess)
    # =========================================================================

    def initialize(self) -> None:
        """Initialize Imaris SDK in subprocess."""
        if self._output_file.exists():
            self._output_file.unlink()

        opts = imaris.Options()
        opts.mEnableLogProgress = True
        opts.mNumberOfThreads = self._thread_count
        opts.mCompressionAlgorithmType = self._compression.value

        dimension_sequence = imaris.DimensionSequence("x", "y", "z", "c", "t")

        block_size = imaris.ImageSize(
            x=self._block_size.x,
            y=self._block_size.y,
            z=self._block_size.z,
            c=1,
            t=1,
        )

        batch_size = imaris.ImageSize(
            x=self._cfg.frame_shape.x,
            y=self._cfg.frame_shape.y,
            z=self._cfg.batch_size,
            c=1,
            t=1,
        )

        self._blocks_per_batch = batch_size / block_size

        # Pad Z to full batches
        image_size = imaris.ImageSize(
            x=self._cfg.frame_shape.x,
            y=self._cfg.frame_shape.y,
            z=ceil(self._cfg.frame_count / self._cfg.batch_size) * self._cfg.batch_size,
            c=1,
            t=1,
        )

        sample_size = imaris.ImageSize(x=1, y=1, z=1, c=1, t=1)

        self._image_converter = imaris.ImageConverter(
            datatype=self.pixel_type.numpy_dtype,
            image_size=image_size,
            sample_size=sample_size,
            dimension_sequence=dimension_sequence,
            block_size=block_size,
            output_filename=str(self._output_file),
            options=opts,
            application_name=f"ImarisWriter[{self._cfg.name}]",
            application_version="2.0",
            progress_callback_class=self._callback_class,
        )

        self._z_blocks_written = 0
        self.log.info("Initialized Imaris SDK. Output: %s", self._output_file)

    def process_batch(self, batch_data: np.ndarray, batch_idx: int) -> None:
        """Process a batch by dividing into blocks and writing to Imaris."""
        if not self._image_converter:
            msg = "ImageConverter not initialized"
            raise RuntimeError(msg)

        block_index = imaris.ImageSize(x=0, y=0, z=0, c=0, t=0)

        for z in range(self._blocks_per_batch.z):
            z0 = z * self._block_size.z
            zf = min(z0 + self._block_size.z, batch_data.shape[0])
            block_index.z = z + self._z_blocks_written

            for y in range(self._blocks_per_batch.y):
                y0 = y * self._block_size.y
                yf = y0 + self._block_size.y
                block_index.y = y

                for x in range(self._blocks_per_batch.x):
                    x0 = x * self._block_size.x
                    xf = x0 + self._block_size.x
                    block_index.x = x

                    # Extract and transpose block
                    block_data = batch_data[z0:zf, y0:yf, x0:xf].copy()
                    block_data = np.transpose(block_data, (2, 1, 0))  # XYZ order

                    # Pad Z if needed
                    if block_data.shape[2] < self._block_size.z:
                        block_data = np.pad(
                            block_data,
                            ((0, 0), (0, 0), (0, self._block_size.z - block_data.shape[2])),
                            mode="constant",
                        )

                    if self._image_converter.NeedCopyBlock(block_index):
                        self._image_converter.CopyBlock(block_data, block_index)

        self._z_blocks_written += self._blocks_per_batch.z

        self.log.info(
            "Batch %d/%d: %d frames written",
            batch_idx,
            self._cfg.num_batches,
            batch_data.shape[0],
        )

    def finalize(self) -> None:
        """Finalize Imaris file with metadata."""
        try:
            if not self._image_converter:
                return

            image_extents = imaris.ImageExtents(
                minX=self._cfg.position.x,
                minY=self._cfg.position.y,
                minZ=self._cfg.position.z,
                maxX=self._cfg.position.x + self._cfg.voxel_size.x * self._cfg.frame_shape.x,
                maxY=self._cfg.position.y + self._cfg.voxel_size.y * self._cfg.frame_shape.y,
                maxZ=self._cfg.position.z + self._cfg.voxel_size.z * self._cfg.frame_count,
            )

            parameters = imaris.Parameters()
            parameters.set_channel_name(self._cfg.channel_idx, self._cfg.channel_name)

            color_infos = [imaris.ColorInfo()]
            color_infos[0].set_base_color(imaris.Color(1.0, 1.0, 1.0, 1.0))

            self._image_converter.Finish(
                image_extents=image_extents,
                parameters=parameters,
                time_infos=[datetime.now(UTC)],
                color_infos=color_infos,
                adjust_color_range=False,
            )
            self._image_converter.Destroy()
            self._image_converter = None

            self.log.info(
                "Finalized: %d frames, %.2f GB/s avg",
                self._process.frames_processed,
                self._process.avg_rate_gbs,
            )
        except Exception:
            self.log.exception("Failed to finalize ImarisWriter")


# =============================================================================
# Test function
# =============================================================================


def test_imaris_writer() -> None:
    """Test the ImarisWriter with sample data."""
    from voxel.utils.log import VoxelLogging

    from .types import Dtype

    VoxelLogging.setup(level="DEBUG")

    cfg = WriterConfig(
        name=f"test_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}",
        path="test_output",
        frame_count=256,
        frame_shape=FrameShape(512, 512),
        batch_size=64,
        dtype=Dtype.UINT16,
        compression="lz4shuffle",
    )

    with ImarisWriter(cfg) as writer:
        for i in range(cfg.frame_count):
            frame = np.random.randint(0, 65535, (512, 512), dtype=np.uint16)
            writer.add_frame(frame)

            if i % 50 == 0:
                print(writer.get_status().summary())

    print(f"Saved to: {cfg.path}/{cfg.name}.ims")


if __name__ == "__main__":
    test_imaris_writer()
