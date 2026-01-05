"""Voxel Writers - Unified API for volumetric data output.

This module provides a Protocol-based API for writing voxel data to various
formats (OME-Zarr, Imaris, OME-TIFF). All writers implement the VoxelWriter
Protocol for a consistent interface.

Example:
    ```python
    from voxel.io.writers import (
        WriterConfig,
        ImarisWriter,
        OMETiffWriter,
        OMEZarrWriter,
        FrameShape,
        Dtype,
    )

    # All writers use the same unified config
    cfg = WriterConfig(
        name="experiment_001",
        path="/data/output",
        frame_count=1000,
        frame_shape=FrameShape(2048, 2048),
        batch_size=128,
        dtype=Dtype.UINT16,
        compression="lz4shuffle",
    )

    # Format-specific runtime options are constructor args
    with ImarisWriter(cfg, thread_count=8) as writer:
        for frame in camera.stream():
            writer.add_frame(frame)
            print(writer.get_status().summary())
    ```
"""

from .protocol import VoxelWriter
from .types import (
    BufferStage,
    BufferStatus,
    Dtype,
    FrameShape,
    Position,
    StreamMetrics,
    StreamStatus,
    VolumeShape,
    VoxelSize,
    WriterConfig,
)
from .imaris import ImarisWriter
from .ometiff import OMETiffWriter
from .omezarr import OMEZarrWriter, create_ozw_config

__all__ = [
    "BufferStage",
    "BufferStatus",
    "Dtype",
    "FrameShape",
    "ImarisWriter",
    "OMETiffWriter",
    "OMEZarrWriter",
    "Position",
    "StreamMetrics",
    "StreamStatus",
    "VolumeShape",
    "VoxelWriter",
    "VoxelSize",
    "WriterConfig",
    "create_ozw_config",
]
