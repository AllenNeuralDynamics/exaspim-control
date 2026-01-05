"""OMETiffWriter - Writer for OME-TIFF files.

This module provides a writer for voxel data that outputs to OME-TIFF format,
implementing the VoxelWriter Protocol using composition.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self

import numpy as np
import tifffile as tf
from ome_types.model import OME, Channel, Image, Pixels, Pixels_DimensionOrder, PixelType, UnitsLength

from .engine import BufferManager, WriterProcess
from .types import FrameShape, StreamMetrics, StreamStatus, WriterConfig

COMPRESSION_METHODS = {None, "deflate", "lzw", "zstd", "lzma"}


class OMETiffWriter:
    """Writer for voxel data that outputs to OME-TIFF format.

    Implements the VoxelWriter Protocol using composition with
    BufferManager and WriterProcess components.

    Example:
        ```python
        from voxel.io.writers import OMETiffWriter, WriterConfig, FrameShape

        cfg = WriterConfig(
            name="experiment_001",
            path="/data/output",
            frame_count=1000,
            frame_shape=FrameShape(2048, 2048),
            batch_size=64,
            compression="zstd",
        )

        with OMETiffWriter(cfg, bigtiff=True) as writer:
            for frame in camera.stream():
                writer.add_frame(frame)
                print(writer.get_status().summary())
        ```
    """

    def __init__(self, cfg: WriterConfig, *, bigtiff: bool = True) -> None:
        """Initialize the OMETiffWriter.

        Args:
            cfg: Writer configuration specifying output path, dimensions, etc.
            bigtiff: Use BigTIFF format for large files (default True)
        """
        from voxel.utils.log import VoxelLogging

        self._cfg = cfg
        self.log = VoxelLogging.get_logger(obj=self)
        self._log_queue = VoxelLogging.get_queue()

        self._compression = cfg.compression if cfg.compression in COMPRESSION_METHODS else None
        self._bigtiff = bigtiff

        # Output path
        self._output_file = Path(cfg.path) / f"{cfg.name}.ome.tiff"
        self._pages_written = 0

        # TIFF writer (initialized in subprocess)
        self._tiff_writer: tf.TiffWriter | None = None

        # OME metadata (generated before subprocess starts)
        self._ome_xml: str = ""

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
            name=f"OMETiffWriter-{cfg.name}",
            processor=self,  # OMETiffWriter implements BatchProcessor
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
    def compression(self) -> str | None:
        """Compression method."""
        return self._compression

    @property
    def axes(self) -> str:
        """Dimension axes string."""
        return "ZYX"

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

        # Generate OME metadata before starting subprocess
        self._ome_xml = self._generate_ome_xml()

        self._process.start()

        self.log.info(
            "Started OMETiffWriter: %s frames, batch_size=%d, output=%s",
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
            "Closed OMETiffWriter. Frames: %d/%d, Avg: %.2f GB/s",
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
            f"OMETiffWriter("
            f"name={self._cfg.name!r}, "
            f"frames={self.frames_added}/{self._cfg.frame_count}, "
            f"running={self.is_running})"
        )

    # =========================================================================
    # BatchProcessor Protocol implementation (called in subprocess)
    # =========================================================================

    def initialize(self) -> None:
        """Initialize TIFF writer in subprocess."""
        if self._output_file.exists():
            self._output_file.unlink()

        self._tiff_writer = tf.TiffWriter(self._output_file, bigtiff=self._bigtiff)
        self._pages_written = 0
        self.log.info("Initialized TiffWriter. Output: %s", self._output_file)

    def process_batch(self, batch_data: np.ndarray, batch_idx: int) -> None:
        """Process a batch by writing to TIFF file."""
        if not self._tiff_writer:
            msg = "TiffWriter not initialized"
            raise RuntimeError(msg)

        # Include OME-XML in first batch only
        description = self._ome_xml if batch_idx == 1 else None

        self._tiff_writer.write(
            batch_data,
            photometric="minisblack",
            metadata={"axes": self.axes},
            description=description,
            contiguous=self._compression is None,
            compression=self._compression,
        )
        self._pages_written += batch_data.shape[0]

        # Get current file size
        file_size_mb = self._output_file.stat().st_size / (1024 * 1024)

        self.log.info(
            "Batch %d/%d: %d frames, file=%.1f MB",
            batch_idx,
            self._cfg.num_batches,
            batch_data.shape[0],
            file_size_mb,
        )

    def finalize(self) -> None:
        """Finalize TIFF file."""
        try:
            if self._tiff_writer:
                self._tiff_writer.close()
                self._tiff_writer = None

            self.log.info(
                "Finalized: %d frames, %.2f GB/s avg",
                self._process.frames_processed,
                self._process.avg_rate_gbs,
            )
        except Exception:
            self.log.exception("Failed to finalize OMETiffWriter")

    # =========================================================================
    # Helper methods
    # =========================================================================

    def _generate_ome_xml(self) -> str:
        """Generate OME-XML metadata."""
        channels = [
            Channel(
                id=f"Channel:0:{self._cfg.channel_idx}",
                name=self._cfg.channel_name,
                samples_per_pixel=1,
            ),
        ]

        pixels = Pixels(
            id="Pixels:0",
            dimension_order=Pixels_DimensionOrder.XYZCT,
            type=self.pixel_type,
            size_x=self._cfg.frame_shape.x,
            size_y=self._cfg.frame_shape.y,
            size_z=self._cfg.frame_count,
            size_c=1,
            size_t=1,
            physical_size_x=self._cfg.voxel_size.x,
            physical_size_y=self._cfg.voxel_size.y,
            physical_size_z=self._cfg.voxel_size.z,
            physical_size_x_unit=UnitsLength.MICROMETER,
            physical_size_y_unit=UnitsLength.MICROMETER,
            physical_size_z_unit=UnitsLength.MICROMETER,
            channels=channels,
        )

        image = Image(
            id="Image:0",
            name=self._cfg.name,
            pixels=pixels,
        )

        ome = OME(images=[image])
        return ome.to_xml().encode("ascii", "xmlcharrefreplace").decode("ascii")


# =============================================================================
# Test function
# =============================================================================


def test_ometiff_writer() -> None:
    """Test the OMETiffWriter with sample data."""
    from datetime import UTC, datetime

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
        compression="zstd",
    )

    with OMETiffWriter(cfg, bigtiff=True) as writer:
        for i in range(cfg.frame_count):
            frame = np.random.randint(0, 65535, (512, 512), dtype=np.uint16)
            writer.add_frame(frame)

            if i % 50 == 0:
                print(writer.get_status().summary())

    print(f"Saved to: {cfg.path}/{cfg.name}.ome.tiff")


if __name__ == "__main__":
    test_ometiff_writer()
