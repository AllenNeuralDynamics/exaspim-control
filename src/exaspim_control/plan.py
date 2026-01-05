"""Grid planning: AcqPlan and Tile classes."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Iterable


class TileStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class OrderMode(StrEnum):
    ROW_WISE = "row_wise"
    COLUMN_WISE = "column_wise"
    ROW_WISE_SNAKE = "row_wise_snake"
    COLUMN_WISE_SNAKE = "column_wise_snake"


# class TileInfo(BaseModel):
#     channel: str
#     position: Vec3D
#     settings: dict[str, dict[str, Any]] = Field(default_factory=dict)


class GridCell(BaseModel):
    """A cell in the computed grid (from config)."""

    row: int
    col: int
    x: float
    y: float
    z: float
    z_end: float
    illumination_index: int = 0


class Tile(GridCell):
    """A committed tile with acquisition state."""

    status: TileStatus = TileStatus.PENDING
    is_enabled: bool = True


class AcqPlan(BaseModel):
    """Acquisition plan with grid configuration and tiles."""

    model_config = {"validate_assignment": True}

    # Grid geometry
    fov_width: float = 1.0
    fov_height: float = 1.0
    overlap: float = Field(default=15.0, ge=0.0, lt=100.0)
    rows: int = Field(default=1, ge=1)
    columns: int = Field(default=1, ge=1)
    origin: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    anchor: tuple[int, int] = (0, 0)

    # Scan range
    z_start: float = 0.0
    z_end: float = 0.0

    # Ordering
    order: OrderMode = OrderMode.ROW_WISE
    reverse: bool = False

    # Illumination
    illumination_count: int = Field(default=1, ge=1, le=4)

    # Generated tiles (empty = planning phase, populated = committed)
    tiles: list[Tile] = Field(default_factory=list)

    # ===== Computed properties =====

    @property
    def step_x(self) -> float:
        return self.fov_width * (1 - self.overlap / 100)

    @property
    def step_y(self) -> float:
        return self.fov_height * (1 - self.overlap / 100)

    @property
    def is_committed(self) -> bool:
        """True if tiles have been generated."""
        return len(self.tiles) > 0

    @property
    def is_locked(self) -> bool:
        """True if any tile is in_progress or completed (acquisition started)."""
        return any(t.status in (TileStatus.IN_PROGRESS, TileStatus.COMPLETED) for t in self.tiles)

    # ===== Grid (computed) =====

    @property
    def grid(self) -> list[GridCell]:
        """Computed grid cells from current config (always fresh)."""
        cells: list[GridCell] = []
        positions = self._compute_positions()

        for row, col, x, y in positions:
            illum = self._compute_illumination_index(row, col)
            cells.append(
                GridCell(
                    row=row,
                    col=col,
                    x=x,
                    y=y,
                    z=self.z_start,
                    z_end=self.z_end,
                    illumination_index=illum,
                )
            )

        return cells

    # ===== Tiles (committed) =====

    def commit(self) -> None:
        """Commit the grid - store tiles with fixed positions."""
        self.tiles = [
            Tile(
                row=cell.row,
                col=cell.col,
                x=cell.x,
                y=cell.y,
                z=cell.z,
                z_end=cell.z_end,
                illumination_index=cell.illumination_index,
            )
            for cell in self.grid
        ]

    def clear(self) -> None:
        """Clear all tiles (return to planning phase)."""
        self.tiles = []

    def _compute_positions(self) -> list[tuple[int, int, float, float]]:
        """Compute (row, col, x, y) for all tiles in acquisition order.

        Grid positions are fixed: tile (0,0) is at origin, others offset by step.
        The `anchor` field determines which tile is first in acquisition order.
        """
        origin_x, origin_y = self.origin[0], self.origin[1]
        start_row, start_col = self.anchor

        positions: list[tuple[int, int, float, float]] = []

        # Generate positions in order mode pattern
        if self.order in (OrderMode.ROW_WISE, OrderMode.ROW_WISE_SNAKE):
            for row in range(self.rows):
                cols: Iterable[int] = range(self.columns)
                if self.order == OrderMode.ROW_WISE_SNAKE and row % 2 == 1:
                    cols = reversed(range(self.columns))
                for col in cols:
                    x = origin_x + col * self.step_x
                    y = origin_y + row * self.step_y
                    positions.append((row, col, x, y))
        else:
            for col in range(self.columns):
                rows: Iterable[int] = range(self.rows)
                if self.order == OrderMode.COLUMN_WISE_SNAKE and col % 2 == 1:
                    rows = reversed(range(self.rows))
                for row in rows:
                    x = origin_x + col * self.step_x
                    y = origin_y + row * self.step_y
                    positions.append((row, col, x, y))

        if self.reverse:
            positions.reverse()

        # Rotate list so start_tile comes first (if valid)
        if start_row > 0 or start_col > 0:
            start_idx = next(
                (i for i, (r, c, _, _) in enumerate(positions) if r == start_row and c == start_col),
                0,
            )
            if start_idx > 0:
                positions = positions[start_idx:] + positions[:start_idx]

        return positions

    def _compute_illumination_index(self, row: int, col: int) -> int:
        """Compute illumination index based on tile position.

        Assignment strategy depends on illumination_count:
        - 1: All tiles get index 0
        - 2-3: Dual split (left half = 0, right half = 1)
        - 4+: Quad split (TL=0, TR=1, BL=2, BR=3)
        """
        if self.illumination_count == 1:
            return 0

        center_col = self.columns / 2
        left = col < center_col

        if self.illumination_count <= 3:
            # Dual split: left vs right
            return 0 if left else 1

        # Quad split: 2x2 quadrants
        center_row = self.rows / 2
        top = row < center_row
        if top and left:
            return 0  # Top-left
        if top and not left:
            return 1  # Top-right
        if not top and left:
            return 2  # Bottom-left
        return 3  # Bottom-right

    # ===== Tile access =====

    def get_tile(self, row: int, col: int) -> Tile | None:
        """Get a specific tile by row/col."""
        for tile in self.tiles:
            if tile.row == row and tile.col == col:
                return tile
        return None

    # ===== Bulk operations =====

    def set_all_enabled(self, *, enabled: bool) -> None:
        """Set enabled state for all tiles."""
        for tile in self.tiles:
            tile.is_enabled = enabled

    def set_all_illumination(self, index: int) -> None:
        """Set illumination index for all tiles."""
        clamped = max(0, min(index, self.illumination_count - 1))
        for tile in self.tiles:
            tile.illumination_index = clamped

    def reset_all_status(self) -> None:
        """Reset all tiles to PENDING status."""
        for tile in self.tiles:
            tile.status = TileStatus.PENDING
