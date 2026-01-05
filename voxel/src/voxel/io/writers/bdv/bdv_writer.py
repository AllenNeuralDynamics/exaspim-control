"""BdvWriter - Writer for BigDataViewer/BigStitcher N5/HDF5 format.

This module provides a writer for voxel data that outputs to BigDataViewer format,
implementing the VoxelWriter Protocol.
"""

from __future__ import annotations

import time
from enum import StrEnum
from math import ceil
from pathlib import Path
from typing import Self

import numpy as np
from voxel.io.writers.types import BdvWriterConfig, BufferStage, BufferStatus, FrameShape, StreamMetrics, StreamStatus

from .sdk import npy2bdv

CHUNK_SIZE_PX = 64

B3D_QUANT_SIGMA = 1  # quantization step
B3D_COMPRESSION_MODE = 1
B3D_BACKGROUND_OFFSET = 0  # ADU
B3D_GAIN = 2.1845  # ADU/e-
B3D_READ_NOISE = 1.5  # e-

B3D_COMPRESSION_OPTS = (
    int(B3D_QUANT_SIGMA * 1000),
    B3D_COMPRESSION_MODE,
    int(B3D_GAIN),
    int(B3D_BACKGROUND_OFFSET),
    int(B3D_READ_NOISE * 1000),
)


class BdvCompression(StrEnum):
    NONE = "none"
    GZIP = "gzip"
    LZF = "lzf"
    B3D = "b3d"


class BdvWriter:
    """Writer for voxel data that outputs to BigDataViewer N5 format.

    Implements the VoxelWriter Protocol with synchronous I/O through
    the npy2bdv SDK. Supports multi-tile and multi-channel datasets
    with affine transformations for deskewing.

    Example:
        ```python
        from voxel.io.writers import BdvWriter, BdvWriterConfig, FrameShape

        cfg = BdvWriterConfig(
            name="experiment_001",
            path="/data/output",
            frame_count=1000,
            frame_shape=FrameShape(2048, 2048),
            batch_size=64,
            theta_deg=30.0,  # shearing angle for deskew
        )

        with BdvWriter(cfg) as writer:
            for frame in camera.stream():
                writer.add_frame(frame)
                print(writer.get_status().summary())
        ```
    """

    def __init__(self, cfg: BdvWriterConfig) -> None:
        """Initialize the BdvWriter.

        Args:
            cfg: Writer configuration specifying output path, dimensions, etc.
        """
        from voxel.utils.log import VoxelLogging

        self._cfg = cfg
        self.log = VoxelLogging.get_logger(obj=self)

        self._theta_deg = cfg.theta_deg
        self._output_file = Path(cfg.path) / f"{cfg.name}.n5"

        # Map compression string to enum
        self._compression: BdvCompression = BdvCompression.NONE
        if cfg.compression:
            try:
                self._compression = BdvCompression(cfg.compression.lower())
            except ValueError:
                self.log.warning("Invalid compression %s, using 'none'", cfg.compression)

        # Multi-tile/channel tracking
        self._tiles_set: set[tuple[float, float, float]] = set()
        self._channels_set: set[str] = set()
        self._tile_idx = 0
        self._tile_shape_dict: dict[tuple[int, int], tuple[int, int, int]] = {}

        # Affine transformation matrices
        self._affine_deskew_dict: dict[tuple[int, int], np.ndarray] = {}
        self._affine_scale_dict: dict[tuple[int, int], np.ndarray] = {}
        self._affine_shift_dict: dict[tuple[int, int], np.ndarray] = {}

        # Frame buffer for batch collection
        self._batch_buffer: np.ndarray | None = None
        self._frames_in_buffer = 0
        self._frames_added = 0
        self._batch_count = 0

        # npy2bdv SDK instance
        self._npy2bdv: npy2bdv.BdvWriter | None = None

        # Performance tracking
        self._start_time = 0.0
        self._metrics: StreamMetrics | None = None

        # State
        self._is_running = False

        # Setup output directory
        output_dir = Path(cfg.path)
        if not output_dir.exists():
            output_dir.mkdir(parents=True, exist_ok=True)
            self.log.warning("Created output directory: %s", output_dir)

        # Configure and start
        self._configure()
        self._start()

    @property
    def cfg(self) -> BdvWriterConfig:
        """Writer configuration."""
        return self._cfg

    @property
    def is_running(self) -> bool:
        """Whether the writer is actively running."""
        return self._is_running

    @property
    def compression(self) -> str | None:
        """Get the compression codec."""
        if self._compression == BdvCompression.NONE:
            return None
        return str(self._compression.value)

    @property
    def batch_size(self) -> int:
        """Frames per batch (chunk size for BDV)."""
        return CHUNK_SIZE_PX

    @property
    def frames_added(self) -> int:
        """Number of frames added to the writer."""
        return self._frames_added

    @property
    def frames_processed(self) -> int:
        """Number of frames processed (written)."""
        return self._batch_count * self.batch_size

    @property
    def batch_count(self) -> int:
        """Number of batches processed."""
        return self._batch_count

    def _configure(self) -> None:
        """Configure writer metadata from config."""
        position_tuple = (
            self._cfg.position.x,
            self._cfg.position.y,
            self._cfg.position.z,
        )
        self._tiles_set.add(position_tuple)
        self._channels_set.add(self._cfg.channel_name)

        dict_key = (len(self._tiles_set), self._cfg.channel_idx)

        if dict_key in self._tile_shape_dict:
            msg = f"Duplicate tile/channel configuration: {dict_key}"
            raise ValueError(msg)

        self._tile_shape_dict[dict_key] = (
            self._cfg.frame_count,
            self._cfg.frame_shape.y,
            self._cfg.frame_shape.x,
        )

        # Adjust y voxel size for theta
        adjusted_voxel_y = self._cfg.voxel_size.y * np.cos(self._theta_deg * np.pi / 180.0)

        # Shearing based on theta and y/z pixel sizes
        shear = -np.tan(self._theta_deg * np.pi / 180.0) * adjusted_voxel_y / self._cfg.voxel_size.z
        self._affine_deskew_dict[dict_key] = np.array(
            ([1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, shear, 1.0, 0.0]),
        )

        scale_x = self._cfg.voxel_size.x / adjusted_voxel_y
        scale_y = 1.0
        scale_z = self._cfg.voxel_size.z / adjusted_voxel_y
        self._affine_scale_dict[dict_key] = np.array(
            ([scale_x, 0.0, 0.0, 0.0], [0.0, scale_y, 0.0, 0.0], [0.0, 0.0, scale_z, 0.0]),
        )

        shift_x = scale_x * (self._cfg.position.x / self._cfg.voxel_size.x)
        shift_y = scale_y * (self._cfg.position.y / adjusted_voxel_y)
        shift_z = scale_z * (self._cfg.position.z / self._cfg.voxel_size.z)
        self._affine_shift_dict[dict_key] = np.array(
            ([1.0, 0.0, 0.0, shift_x], [0.0, 1.0, 0.0, shift_y], [0.0, 0.0, 1.0, shift_z]),
        )

    def _start(self) -> None:
        """Start the writer and initialize npy2bdv."""
        frame_bytes = self._cfg.frame_shape.y * self._cfg.frame_shape.x * 2
        self._metrics = StreamMetrics(frame_bytes)
        self._start_time = time.perf_counter()

        # Pyramid subsampling factors (xyz order)
        subsamp = (
            (1, 1, 1),
            (2, 2, 2),
            (4, 4, 4),
        )
        # Chunk size (xyz order)
        blockdim = (
            (4, 256, 256),
            (4, 256, 256),
            (4, 256, 256),
        )

        compression_arg = None if self._compression == BdvCompression.NONE else self._compression.value
        compression_opts = B3D_COMPRESSION_OPTS if self._compression == BdvCompression.B3D else None

        self._npy2bdv = npy2bdv.BdvWriter(
            filename=str(self._output_file),
            subsamp=subsamp,
            blockdim=blockdim,
            compression=compression_arg,
            compression_opts=compression_opts,
            ntiles=len(self._tiles_set),
            nchannels=len(self._channels_set),
            overwrite=False,
        )

        # Pad Z to full batches for virtual stack
        image_size_z = ceil(self._cfg.frame_count / CHUNK_SIZE_PX) * CHUNK_SIZE_PX

        for key in self._tile_shape_dict:
            append_tile, append_channel = key
            self._npy2bdv.append_view(
                stack=None,
                virtual_stack_dim=(
                    image_size_z,
                    self._cfg.frame_shape.y,
                    self._cfg.frame_shape.x,
                ),
                tile=append_tile,
                channel=append_channel,
                voxel_size_xyz=(
                    self._cfg.voxel_size.x,
                    self._cfg.voxel_size.y,
                    self._cfg.voxel_size.z,
                ),
                voxel_units="um",
            )

        # Allocate batch buffer
        self._batch_buffer = np.zeros(
            (self.batch_size, self._cfg.frame_shape.y, self._cfg.frame_shape.x),
            dtype=np.uint16,
        )
        self._frames_in_buffer = 0

        self._is_running = True
        self.log.info(
            "Started BdvWriter: %d frames, batch_size=%d, output=%s",
            self._cfg.frame_count,
            self.batch_size,
            self._output_file,
        )

    def add_frame(self, frame: np.ndarray) -> None:
        """Add a single 2D frame to the writer.

        Args:
            frame: 2D numpy array with shape matching frame_shape.

        Raises:
            RuntimeError: If writer is not running or has been closed.
        """
        if not self._is_running:
            msg = "Cannot add frame: writer is not running"
            raise RuntimeError(msg)

        if self._batch_buffer is None:
            msg = "Batch buffer not initialized"
            raise RuntimeError(msg)

        # Add frame to buffer
        self._batch_buffer[self._frames_in_buffer] = frame
        self._frames_in_buffer += 1
        self._frames_added += 1

        if self._metrics:
            self._metrics.tick()

        is_last_frame = self._frames_added == self._cfg.frame_count
        buffer_full = self._frames_in_buffer >= self.batch_size

        if buffer_full or is_last_frame:
            self._process_batch()

        if is_last_frame:
            self.log.info("Added last frame %d. Finalizing...", self._frames_added)

    def _process_batch(self) -> None:
        """Process and write the current batch."""
        if not self._npy2bdv or self._batch_buffer is None:
            return

        if self._frames_in_buffer == 0:
            return

        # Get actual data (may be partial batch)
        batch_data = self._batch_buffer[: self._frames_in_buffer]

        self._npy2bdv.append_substack(
            substack=batch_data,
            z_start=self._batch_count * self.batch_size,
            tile=self._tile_idx,
            channel=self._cfg.channel_idx,
        )

        self._batch_count += 1
        self._frames_in_buffer = 0

        self.log.info(
            "Batch %d/%d: %d frames written",
            self._batch_count,
            self._cfg.num_batches,
            batch_data.shape[0],
        )

    def get_status(self) -> StreamStatus:
        """Get a snapshot of the current writer status.

        Returns:
            StreamStatus with progress and performance metrics.
        """
        frames_remaining = self._cfg.frame_count - self._frames_added

        # Estimate remaining time
        estimated_remaining = None
        if self._metrics and self._metrics.fps > 0 and frames_remaining > 0:
            estimated_remaining = frames_remaining / self._metrics.fps

        # Buffer status
        buffers = {
            0: BufferStatus(
                batch_idx=self._batch_count,
                stage=BufferStage.COLLECTING if self._is_running else BufferStage.IDLE,
                filled=self._frames_in_buffer,
                capacity=self.batch_size,
            ),
        }

        elapsed = time.perf_counter() - self._start_time if self._start_time > 0 else 0.0

        return StreamStatus(
            fps=self._metrics.fps if self._metrics else 0.0,
            fps_inst=self._metrics.fps_inst if self._metrics else 0.0,
            throughput_gbs=0.0,  # Not tracked for synchronous writes
            throughput_gbs_inst=0.0,
            frames_acquired=self._frames_added,
            total_frames=self._cfg.frame_count,
            frames_remaining=frames_remaining,
            current_batch=self._batch_count,
            total_batches=self._cfg.num_batches,
            current_slot=0,
            buffers=buffers,
            elapsed_time=elapsed,
            estimated_remaining=estimated_remaining,
        )

    def wait_all(self) -> None:
        """Wait for all pending write operations to complete.

        For BdvWriter, this is a no-op since writes are synchronous.
        """

    def close(self) -> None:
        """Close the writer and clean up resources."""
        if not self._is_running:
            return

        # Process any remaining frames
        if self._frames_in_buffer > 0:
            self._process_batch()

        # Finalize the file
        self._finalize()

        self._is_running = False
        self._batch_buffer = None

        self.log.info(
            "Closed BdvWriter. Frames: %d/%d",
            self._frames_added,
            self._cfg.frame_count,
        )

    def _finalize(self) -> None:
        """Finalize the N5 file with XML metadata."""
        if not self._npy2bdv:
            return

        try:
            # Write XML metadata
            self._npy2bdv.write_xml()

            # Append affine transformations
            for append_tile, append_channel in self._affine_deskew_dict:
                self._npy2bdv.append_affine(
                    m_affine=self._affine_deskew_dict[(append_tile, append_channel)],
                    name_affine="deskew",
                    tile=append_tile,
                    channel=append_channel,
                )

            for append_tile, append_channel in self._affine_scale_dict:
                self._npy2bdv.append_affine(
                    m_affine=self._affine_scale_dict[(append_tile, append_channel)],
                    name_affine="scale",
                    tile=append_tile,
                    channel=append_channel,
                )

            for append_tile, append_channel in self._affine_shift_dict:
                self._npy2bdv.append_affine(
                    m_affine=self._affine_shift_dict[(append_tile, append_channel)],
                    name_affine="shift",
                    tile=append_tile,
                    channel=append_channel,
                )

            self._npy2bdv.close()
            self._npy2bdv = None
            self._tile_idx += 1

            self.log.info("Finalized: %d frames to %s", self._cfg.frame_count, self._output_file)

        except Exception:
            self.log.exception("Failed to finalize BdvWriter")

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
            f"BdvWriter("
            f"name={self._cfg.name!r}, "
            f"frames={self._frames_added}/{self._cfg.frame_count}, "
            f"running={self._is_running})"
        )


# =============================================================================
# Test function
# =============================================================================


def test_bdv_writer() -> None:
    """Test the BdvWriter with sample data."""
    from datetime import UTC, datetime

    from voxel.utils.log import VoxelLogging

    VoxelLogging.setup(level="DEBUG")

    cfg = BdvWriterConfig(
        name=f"test_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}",
        path="test_output",
        frame_count=128,
        frame_shape=FrameShape(512, 512),
        batch_size=64,
        theta_deg=30.0,
    )

    with BdvWriter(cfg) as writer:
        for i in range(cfg.frame_count):
            frame = np.random.randint(0, 65535, (512, 512), dtype=np.uint16)
            writer.add_frame(frame)

            if i % 25 == 0:
                print(writer.get_status().summary())

    print(f"Saved to: {cfg.path}/{cfg.name}.n5")


if __name__ == "__main__":
    test_bdv_writer()
