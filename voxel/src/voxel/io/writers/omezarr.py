"""OMEZarrWriter adapter wrapping the ome-zarr-writer package.

This module provides an adapter that wraps the external ome-zarr-writer
package, making it conform to the VoxelWriter Protocol used by voxel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from ome_zarr_writer import BufferStage as OZWBufferStage
from ome_zarr_writer import Compression, Dtype, ScaleLevel
from ome_zarr_writer import OMEZarrWriter as _OMEZarrWriter
from ome_zarr_writer import VolumeShape as OZWVolumeShape
from ome_zarr_writer import VoxelSize as OZWVoxelSize
from ome_zarr_writer import WriterConfig as OZWWriterConfig

from .types import BufferStage, BufferStatus, StreamStatus, WriterConfig

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np
    from ome_zarr_writer import StreamStatus as OZWStreamStatus
    from ome_zarr_writer.backends import Backend


class OMEZarrWriter:
    """Adapter wrapping ome-zarr-writer's OMEZarrWriter.

    This class adapts the external ome-zarr-writer package to conform to
    the VoxelWriter Protocol, providing a consistent interface with other
    voxel writers (Imaris, TIFF, BDV).

    The ome-zarr-writer package handles:
    - Ring buffer management with configurable slots
    - Real-time multi-scale pyramid generation (Numba-accelerated)
    - Multiple storage backends (TensorStore, Zarrs, etc.)
    - S3/cloud storage support

    Example:
        ```python
        from voxel.io.writers import OMEZarrWriter, WriterConfig, FrameShape, create_ozw_config
        from ome_zarr_writer.backends.ts import TensorStoreBackend

        cfg = WriterConfig(
            name="experiment_001",
            path="/data/output",
            frame_count=1000,
            frame_shape=FrameShape(2048, 2048),
            batch_size=128,
            max_level=5,
        )

        # Create backend from ome-zarr-writer
        ozw_cfg = create_ozw_config(cfg)
        backend = TensorStoreBackend(ozw_cfg, cfg.path)

        with OMEZarrWriter(cfg, backend) as writer:
            for frame in camera.stream():
                writer.add_frame(frame)
                print(writer.get_status().summary())
        ```
    """

    def __init__(
        self,
        cfg: WriterConfig,
        backend: Backend,
        slots: int = 3,
        status_callback: Callable[[StreamStatus], None] | None = None,
        status_interval: float = 1.0,
    ) -> None:
        """Initialize the OMEZarrWriter adapter.

        Args:
            cfg: Voxel writer configuration
            backend: ome-zarr-writer Backend instance (TensorStore, Zarrs, etc.)
            slots: Number of ring buffer slots (minimum 2)
            status_callback: Optional callback invoked periodically with status
            status_interval: Status callback interval in seconds
        """
        # Import ome-zarr-writer

        self._cfg = cfg
        self._backend = backend

        # Wrap the status callback to convert status types
        wrapped_callback = None
        if status_callback is not None:
            wrapped_callback = lambda ozw_status: status_callback(self._convert_status(ozw_status))

        # Create the underlying ome-zarr-writer instance
        self._writer = _OMEZarrWriter(
            backend=backend,
            slots=slots,
            status_callback=wrapped_callback,
            status_interval=status_interval,
        )

        self._is_running = True

    @property
    def cfg(self) -> WriterConfig:
        """Writer configuration."""
        return self._cfg

    @property
    def is_running(self) -> bool:
        """Whether the writer is actively running."""
        return self._is_running

    @property
    def current_buffer(self):
        """Get the currently active buffer (passthrough to ome-zarr-writer)."""
        return self._writer.current_buffer

    @property
    def latest_frame(self) -> np.ndarray:
        """Get the most recently added frame."""
        return self._writer.latest_frame

    def add_frame(self, frame: np.ndarray) -> None:
        """Add a single 2D frame to the writer.

        Args:
            frame: 2D numpy array with shape matching frame_shape.

        Raises:
            RuntimeError: If writer has been closed.
        """
        if not self._is_running:
            msg = "Cannot add frame: writer has been closed"
            raise RuntimeError(msg)

        self._writer.add_frame(frame)

    def get_status(self) -> StreamStatus:
        """Get a snapshot of the current writer status.

        Returns:
            StreamStatus with progress and performance metrics.
        """
        ozw_status = self._writer.get_status()
        return self._convert_status(ozw_status)

    def wait_all(self) -> None:
        """Wait for all pending write operations to complete."""
        self._writer.wait_all()

    def close(self) -> None:
        """Close the writer and clean up resources."""
        if self._is_running:
            self._writer.close()
            self._is_running = False

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
            f"OMEZarrWriter(name={self._cfg.name!r}, frame_count={self._cfg.frame_count}, running={self._is_running})"
        )

    def _convert_status(self, ozw_status: OZWStreamStatus) -> StreamStatus:
        """Convert ome-zarr-writer StreamStatus to voxel StreamStatus.

        Args:
            ozw_status: Status from ome-zarr-writer

        Returns:
            Voxel StreamStatus instance
        """
        # Convert buffer statuses
        buffers: dict[int, BufferStatus] = {}
        if hasattr(ozw_status, "buffers") and ozw_status.buffers:
            for slot_idx, ozw_buf in ozw_status.buffers.items():
                # Map ome-zarr-writer BufferStage to voxel BufferStage
                stage = self._map_buffer_stage(ozw_buf.stage)
                buffers[slot_idx] = BufferStatus(
                    batch_idx=ozw_buf.batch_idx,
                    stage=stage,
                    filled=ozw_buf.filled,
                    capacity=ozw_buf.capacity,
                )

        return StreamStatus(
            fps=ozw_status.fps,
            fps_inst=ozw_status.fps_inst,
            throughput_gbs=ozw_status.throughput_gbs,
            throughput_gbs_inst=ozw_status.throughput_gbs_inst,
            frames_acquired=ozw_status.frames_acquired,
            total_frames=ozw_status.total_frames,
            frames_remaining=ozw_status.frames_remaining,
            current_batch=ozw_status.current_batch,
            total_batches=ozw_status.total_batches,
            current_slot=ozw_status.current_slot,
            buffers=buffers,
            elapsed_time=ozw_status.elapsed_time,
            estimated_remaining=ozw_status.estimated_remaining,
        )

    def _map_buffer_stage(self, ozw_stage) -> BufferStage:
        """Map ome-zarr-writer BufferStage to voxel BufferStage."""

        mapping = {
            OZWBufferStage.ERROR: BufferStage.ERROR,
            OZWBufferStage.IDLE: BufferStage.IDLE,
            OZWBufferStage.COLLECTING: BufferStage.COLLECTING,
            OZWBufferStage.DOWNSAMPLING: BufferStage.PROCESSING,
            OZWBufferStage.FLUSHING: BufferStage.FLUSHING,
        }
        return mapping.get(ozw_stage, BufferStage.IDLE)


def create_ozw_config(cfg: WriterConfig) -> OZWWriterConfig:
    """Create an ome-zarr-writer WriterConfig from voxel config.

    This is a helper function to create the ome-zarr-writer configuration
    from a voxel WriterConfig.

    Args:
        cfg: Voxel writer configuration

    Returns:
        ome_zarr_writer.WriterConfig instance
    """

    # Map dtype
    dtype_map = {
        "uint8": Dtype.UINT8,
        "uint16": Dtype.UINT16,
    }
    ozw_dtype = dtype_map.get(cfg.dtype.value, Dtype.UINT16)

    # Map compression
    compression_map = {
        "blosc.lz4": Compression.BLOSC_LZ4,
        "blosc.zstd": Compression.BLOSC_ZSTD,
        "gzip": Compression.GZIP,
        "zstd": Compression.ZSTD,
        "none": Compression.NONE,
        None: Compression.BLOSC_LZ4,
    }
    ozw_compression = compression_map.get(cfg.compression, Compression.BLOSC_LZ4)

    # Compute volume shape
    volume_shape = OZWVolumeShape(
        z=cfg.frame_count,
        y=cfg.frame_shape.y,
        x=cfg.frame_shape.x,
    )

    # Use provided shapes or compute defaults
    if cfg.shard_shape is not None:
        shard_shape = OZWVolumeShape(
            z=cfg.shard_shape.z,
            y=cfg.shard_shape.y,
            x=cfg.shard_shape.x,
        )
    else:
        # Default shard shape based on batch size
        shard_shape = OZWVolumeShape(
            z=cfg.batch_size,
            y=min(256, cfg.frame_shape.y),
            x=min(256, cfg.frame_shape.x),
        )

    if cfg.chunk_shape is not None:
        chunk_shape = OZWVolumeShape(
            z=cfg.chunk_shape.z,
            y=cfg.chunk_shape.y,
            x=cfg.chunk_shape.x,
        )
    else:
        # Default chunk shape
        chunk_shape = OZWVolumeShape(
            z=min(64, shard_shape.z),
            y=min(64, shard_shape.y),
            x=min(64, shard_shape.x),
        )

    # Map scale level
    max_level = ScaleLevel(cfg.max_level)

    return OZWWriterConfig(
        name=cfg.name,
        max_level=max_level,
        batch_z_shards=cfg.batch_z_shards,
        volume_shape=volume_shape,
        shard_shape=shard_shape,
        chunk_shape=chunk_shape,
        compression=ozw_compression,
        dtype=ozw_dtype,
        voxel_size=OZWVoxelSize(
            z=cfg.voxel_size.z,
            y=cfg.voxel_size.y,
            x=cfg.voxel_size.x,
        ),
    )
