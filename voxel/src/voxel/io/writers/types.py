"""Core type definitions for voxel writers.

Re-exports shared types from ome-zarr-writer for a unified API.
"""

from __future__ import annotations

from math import ceil
from pathlib import Path

# Re-export types from ome-zarr-writer
from ome_zarr_writer import (
    BufferStage,
    BufferStatus,
    Dtype,
    FrameShape,
    StreamMetrics,
    StreamStatus,
    VolumeShape,
    VoxelSize,
)
from ome_zarr_writer.types import Vec3D
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

# Position is Vec3D[float] - used for physical positioning in multi-tile acquisitions
Position = Vec3D[float]

__all__ = [
    "BufferStage",
    "BufferStatus",
    "Dtype",
    "FrameShape",
    "Position",
    "StreamMetrics",
    "StreamStatus",
    "VolumeShape",
    "VoxelSize",
]


class WriterConfig(BaseModel):
    """Unified configuration for all voxel writers.

    All writers (Imaris, OME-Zarr, OME-TIFF) accept this single config.
    Format-specific runtime options (thread_count, bigtiff) are passed
    to writer constructors, not stored in config.

    Chunking concepts are unified:
    - `chunk_shape`: Smallest storage unit (Imaris blocks, Zarr chunks)
    - `shard_shape`: Groups of chunks (OME-Zarr only)

    Example:
        ```python
        cfg = WriterConfig(
            name="experiment_001",
            path="/data/output",
            frame_count=1000,
            frame_shape=FrameShape(2048, 2048),
            batch_size=128,
            compression="lz4shuffle",
        )

        with ImarisWriter(cfg, thread_count=8) as writer:
            ...
        ```
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Dataset/experiment name")
    path: Path = Field(description="Output directory path")
    frame_count: int = Field(gt=0, description="Total number of frames to write")
    frame_shape: FrameShape = Field(description="Frame dimensions (y, x) in pixels")
    batch_size: int = Field(gt=0, description="Number of frames per batch")
    dtype: Dtype = Field(..., description="Data type for pixel values")
    voxel_size: VoxelSize = Field(
        default_factory=lambda: VoxelSize(1.0, 1.0, 1.0),
        description="Physical voxel size (z, y, x) in micrometers",
    )
    position: Position = Field(
        default_factory=lambda: Position(0.0, 0.0, 0.0),
        description="Volume position (z, y, x) in micrometers",
    )
    channel_name: str = Field(default="Channel0", description="Display name for the channel")
    channel_idx: int = Field(default=0, ge=0, description="Channel index for multi-channel data")
    compression: str | None = Field(default=None, description="Compression codec (format-specific)")
    chunk_shape: VolumeShape | None = Field(
        default=None,
        description="Chunk dimensions (z, y, x). Imaris uses y/x for block size. None = auto",
    )
    shard_shape: VolumeShape | None = Field(
        default=None,
        description="Shard dimensions (z, y, x) for OME-Zarr. None = auto",
    )
    max_level: int = Field(default=5, ge=0, le=7, description="Maximum pyramid level (0-7)")
    batch_z_shards: int = Field(default=1, gt=0, description="Number of z-shards per batch")

    @field_validator("path", mode="before")
    @classmethod
    def _coerce_path(cls, v: str | Path) -> Path:
        return Path(v) if isinstance(v, str) else v

    @computed_field
    @property
    def num_batches(self) -> int:
        """Total number of batches needed."""
        return ceil(self.frame_count / self.batch_size)

    @computed_field
    @property
    def volume_shape(self) -> VolumeShape:
        """Full volume shape (z, y, x)."""
        return VolumeShape(self.frame_count, self.frame_shape.y, self.frame_shape.x)

    @computed_field
    @property
    def has_tail(self) -> bool:
        """Whether the final batch is partial."""
        return self.frame_count % self.batch_size != 0

    @computed_field
    @property
    def tail_size(self) -> int:
        """Size of the final partial batch (0 if no tail)."""
        remainder = self.frame_count % self.batch_size
        return max(0, remainder)

    def get_batch_z_range(self, batch_idx: int) -> tuple[int, int]:
        """Get the z-index range for a given batch.

        Args:
            batch_idx: Zero-based batch index

        Returns:
            Tuple of (z_start, z_end) indices
        """
        z_start = batch_idx * self.batch_size
        z_end = min(z_start + self.batch_size, self.frame_count)
        return z_start, z_end
