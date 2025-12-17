"""VolumeModel - Shared reactive state for volume/acquisition planning.

This QObject holds all shared state for volume planning and emits signals
when state changes. It is created by InstrumentUI and passed to all volume
widgets (GridControls, VolumeGraphic).

AxisWidgets push position/limits updates here.
GridControls reads/writes grid configuration and displays tile table.
VolumeGraphic subscribes for display updates.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Literal

import numpy as np
import useq
from PyQt6.QtCore import QObject, pyqtSignal


class GridFromEdges(useq.GridFromEdges):
    """Subclass of useq.GridFromEdges with row/column attributes and reversible order."""

    reverse = property()

    def __init__(self, reverse=False, *args, **kwargs):
        setattr(type(self), "reverse", property(fget=lambda x: reverse))
        super().__init__(*args, **kwargs)

    @property
    def rows(self) -> int:
        if self.fov_width is None or self.fov_height is None:
            return 0
        dx, _ = self._step_size(self.fov_width, self.fov_height)
        return self._nrows(dx)

    @property
    def columns(self) -> int:
        if self.fov_width is None or self.fov_height is None:
            return 0
        _, dy = self._step_size(self.fov_width, self.fov_height)
        return self._ncolumns(dy)

    def iter_grid_positions(self, *args, **kwargs) -> Generator:
        if not self.reverse:
            yield from super().iter_grid_positions(*args, **kwargs)
        else:
            yield from reversed(list(super().iter_grid_positions(*args, **kwargs)))


class GridWidthHeight(useq.GridWidthHeight):
    """Subclass of useq.GridWidthHeight with row/column attributes and reversible order."""

    reverse = property()

    def __init__(self, reverse=False, *args, **kwargs):
        setattr(type(self), "reverse", property(fget=lambda x: reverse))
        super().__init__(*args, **kwargs)

    @property
    def rows(self) -> int:
        if self.fov_width is None or self.fov_height is None:
            return 0
        dx, _ = self._step_size(self.fov_width, self.fov_height)
        return self._nrows(dx)

    @property
    def columns(self) -> int:
        if self.fov_width is None or self.fov_height is None:
            return 0
        _, dy = self._step_size(self.fov_width, self.fov_height)
        return self._ncolumns(dy)

    def iter_grid_positions(self, *args, **kwargs) -> Generator:
        if not self.reverse:
            yield from super().iter_grid_positions(*args, **kwargs)
        else:
            yield from reversed(list(super().iter_grid_positions(*args, **kwargs)))


class GridRowsColumns(useq.GridRowsColumns):
    """Subclass of useq.GridRowsColumns with reversible order."""

    reverse = property()

    def __init__(self, reverse=False, *args, **kwargs):
        setattr(type(self), "reverse", property(fget=lambda x: reverse))
        super().__init__(*args, **kwargs)

    def iter_grid_positions(self, *args, **kwargs) -> Generator:
        if not self.reverse:
            yield from super().iter_grid_positions(*args, **kwargs)
        else:
            yield from reversed(list(super().iter_grid_positions(*args, **kwargs)))


class VolumeModel(QObject):
    """Shared reactive state for volume/acquisition planning.

    This QObject is created by InstrumentUI and passed to all volume widgets.
    It holds all state and emits signals when state changes.
    """

    # ===== Stage State Signals =====
    fovPositionChanged = pyqtSignal(list)
    fovDimensionsChanged = pyqtSignal(list)
    limitsChanged = pyqtSignal(list)
    movingChanged = pyqtSignal(bool)

    # ===== Grid Config Signals =====
    gridChanged = pyqtSignal()  # Any grid parameter changed

    # ===== Tile Output Signal =====
    tilesChanged = pyqtSignal()  # Tile positions recalculated

    def __init__(
        self,
        coordinate_plane: list[str] | None = None,
        unit: str = "mm",
        fov_dimensions: list[float] | None = None,
        fov_position: list[float] | None = None,
        limits: list[list[float]] | None = None,
        default_overlap: float = 15.0,
        default_order: str = "row_wise",
        dual_sided: bool = False,
        parent: QObject | None = None,
    ):
        """Initialize VolumeModel.

        :param coordinate_plane: Coordinate plane labels, e.g. ["-x", "y", "z"]
        :param unit: Unit for all measurements (e.g., "mm")
        :param fov_dimensions: Field of view dimensions [w, h, d]
        :param fov_position: Current FOV position [x, y, z]
        :param limits: Stage limits [[xmin, xmax], [ymin, ymax], [zmin, zmax]]
        :param default_overlap: Default tile overlap percentage
        :param default_order: Default tile order
        :param dual_sided: Whether dual-sided imaging is enabled
        :param parent: Parent QObject
        """
        super().__init__(parent)

        # ===== Stage State =====
        self._coordinate_plane = coordinate_plane or ["x", "y", "z"]
        self._coordinate_plane_clean = [x.replace("-", "") for x in self._coordinate_plane]
        self._polarity = [1 if "-" not in x else -1 for x in self._coordinate_plane]
        self._unit = unit
        self._fov_position = list(fov_position) if fov_position else [0.0, 0.0, 0.0]
        self._fov_dimensions = list(fov_dimensions) if fov_dimensions else [1.0, 1.0, 0.0]
        self._limits = [list(lim) for lim in limits] if limits else [
            [float("-inf"), float("inf")] for _ in range(3)
        ]
        self._is_moving = False

        # ===== Grid Configuration =====
        self._mode: Literal["number", "area", "bounds"] = "number"
        self._rows = 1
        self._columns = 1
        self._area_width = 1.0
        self._area_height = 1.0
        self._bounds = [[0.0, 0.0], [0.0, 0.0]]  # [[x_low, x_high], [y_low, y_high]]
        self._overlap = default_overlap
        self._order = default_order
        self._relative_to = "center"
        self._reverse = False
        self._dual_sided = dual_sided
        self._grid_offset = [0.0, 0.0, 0.0]
        self._anchor_enabled = [False, False, False]

        # ===== Tile Output (computed) =====
        self._tile_visibility: np.ndarray = np.ones([1, 1], dtype=bool)
        self._scan_starts: np.ndarray = np.zeros([1, 1], dtype=float)
        self._scan_ends: np.ndarray = np.zeros([1, 1], dtype=float)

        # Start/stop tile indices
        self._start_tile: int | None = None
        self._stop_tile: int | None = None

        # Initialize tile calculations
        self._recalculate_tiles()

    # ===== Read-only Properties =====

    @property
    def coordinate_plane(self) -> list[str]:
        """Coordinate plane labels including polarity (e.g., ['-x', 'y', 'z'])."""
        return self._coordinate_plane

    @property
    def coordinate_plane_clean(self) -> list[str]:
        """Coordinate plane labels without polarity (e.g., ['x', 'y', 'z'])."""
        return self._coordinate_plane_clean

    @property
    def polarity(self) -> list[int]:
        """Polarity for each axis (+1 or -1)."""
        return self._polarity

    @property
    def unit(self) -> str:
        """Unit for all measurements."""
        return self._unit

    # ===== Stage State Properties =====

    @property
    def fov_position(self) -> list[float]:
        """Current FOV position [x, y, z]."""
        return self._fov_position

    @fov_position.setter
    def fov_position(self, value: list[float]) -> None:
        if list(value) != self._fov_position:
            self._fov_position = list(value)
            self._update_grid_offset_from_fov()
            self.fovPositionChanged.emit(self._fov_position)

    @property
    def fov_dimensions(self) -> list[float]:
        """FOV dimensions [width, height, depth]."""
        return self._fov_dimensions

    @fov_dimensions.setter
    def fov_dimensions(self, value: list[float]) -> None:
        if list(value) != self._fov_dimensions:
            self._fov_dimensions = list(value)
            self._recalculate_tiles()
            self.fovDimensionsChanged.emit(self._fov_dimensions)

    @property
    def limits(self) -> list[list[float]]:
        """Stage limits [[xmin, xmax], [ymin, ymax], [zmin, zmax]]."""
        return self._limits

    @limits.setter
    def limits(self, value: list[list[float]]) -> None:
        new_limits = [list(lim) for lim in value]
        if new_limits != self._limits:
            self._limits = new_limits
            self.limitsChanged.emit(self._limits)

    @property
    def is_moving(self) -> bool:
        """Whether any stage axis is currently moving."""
        return self._is_moving

    @is_moving.setter
    def is_moving(self, value: bool) -> None:
        if value != self._is_moving:
            self._is_moving = value
            self.movingChanged.emit(value)

    # ===== Grid Configuration Properties =====

    @property
    def mode(self) -> Literal["number", "area", "bounds"]:
        """Grid mode: 'number', 'area', or 'bounds'."""
        return self._mode

    @mode.setter
    def mode(self, value: Literal["number", "area", "bounds"]) -> None:
        if value != self._mode:
            self._mode = value
            self._recalculate_tiles()
            self.gridChanged.emit()

    @property
    def rows(self) -> int:
        """Number of tile rows."""
        return self._rows

    @rows.setter
    def rows(self, value: int) -> None:
        if value != self._rows:
            self._rows = value
            self._recalculate_tiles()
            self.gridChanged.emit()

    @property
    def columns(self) -> int:
        """Number of tile columns."""
        return self._columns

    @columns.setter
    def columns(self, value: int) -> None:
        if value != self._columns:
            self._columns = value
            self._recalculate_tiles()
            self.gridChanged.emit()

    @property
    def area_width(self) -> float:
        """Area width for 'area' mode."""
        return self._area_width

    @area_width.setter
    def area_width(self, value: float) -> None:
        if value != self._area_width:
            self._area_width = value
            self._recalculate_tiles()
            self.gridChanged.emit()

    @property
    def area_height(self) -> float:
        """Area height for 'area' mode."""
        return self._area_height

    @area_height.setter
    def area_height(self, value: float) -> None:
        if value != self._area_height:
            self._area_height = value
            self._recalculate_tiles()
            self.gridChanged.emit()

    @property
    def bounds(self) -> list[list[float]]:
        """Bounds for 'bounds' mode: [[x_low, x_high], [y_low, y_high]]."""
        return self._bounds

    @bounds.setter
    def bounds(self, value: list[list[float]]) -> None:
        new_bounds = [list(b) for b in value]
        if new_bounds != self._bounds:
            self._bounds = new_bounds
            self._recalculate_tiles()
            self.gridChanged.emit()

    @property
    def overlap(self) -> float:
        """Tile overlap percentage."""
        return self._overlap

    @overlap.setter
    def overlap(self, value: float) -> None:
        if value != self._overlap:
            self._overlap = value
            self._recalculate_tiles()
            self.gridChanged.emit()

    @property
    def order(self) -> str:
        """Tile order (e.g., 'row_wise', 'column_wise_snake', etc.)."""
        return self._order

    @order.setter
    def order(self, value: str) -> None:
        if value != self._order:
            self._order = value
            self._recalculate_tiles()
            self.gridChanged.emit()

    @property
    def relative_to(self) -> str:
        """Grid relative to ('center' or corner)."""
        return self._relative_to

    @relative_to.setter
    def relative_to(self, value: str) -> None:
        if value != self._relative_to:
            self._relative_to = value
            self._recalculate_tiles()
            self.gridChanged.emit()

    @property
    def reverse(self) -> bool:
        """Whether tile order is reversed."""
        return self._reverse

    @reverse.setter
    def reverse(self, value: bool) -> None:
        if value != self._reverse:
            self._reverse = value
            self._recalculate_tiles()
            self.gridChanged.emit()

    @property
    def dual_sided(self) -> bool:
        """Whether dual-sided imaging is enabled."""
        return self._dual_sided

    @dual_sided.setter
    def dual_sided(self, value: bool) -> None:
        if value != self._dual_sided:
            self._dual_sided = value
            self._recalculate_tiles()
            self.gridChanged.emit()

    @property
    def grid_offset(self) -> list[float]:
        """Grid offset from origin [x, y, z]."""
        return self._grid_offset

    @grid_offset.setter
    def grid_offset(self, value: list[float]) -> None:
        if list(value) != self._grid_offset:
            self._grid_offset = list(value)
            self._scan_starts[:, :] = value[2]
            self._recalculate_tiles()
            self.gridChanged.emit()

    @property
    def anchor_enabled(self) -> list[bool]:
        """Whether each axis is anchored [x, y, z]."""
        return self._anchor_enabled

    @anchor_enabled.setter
    def anchor_enabled(self, value: list[bool]) -> None:
        if list(value) != self._anchor_enabled:
            self._anchor_enabled = list(value)
            self._update_grid_offset_from_fov()
            self.gridChanged.emit()

    # ===== Tile Output Properties =====

    @property
    def tile_visibility(self) -> np.ndarray:
        """2D bool array of tile visibility [rows, cols]."""
        return self._tile_visibility

    def set_tile_visibility(self, row: int, col: int, visible: bool) -> None:
        """Set visibility for a specific tile."""
        if self._tile_visibility[row, col] != visible:
            self._tile_visibility[row, col] = visible
            self.tilesChanged.emit()

    @property
    def scan_starts(self) -> np.ndarray:
        """2D array of scan start positions [rows, cols]."""
        return self._scan_starts

    def set_scan_start(self, row: int, col: int, value: float) -> None:
        """Set scan start for a specific tile."""
        if self._scan_starts[row, col] != value:
            self._scan_starts[row, col] = value
            self.tilesChanged.emit()

    @property
    def scan_ends(self) -> np.ndarray:
        """2D array of scan end positions [rows, cols]."""
        return self._scan_ends

    def set_scan_end(self, row: int, col: int, value: float) -> None:
        """Set scan end for a specific tile."""
        if self._scan_ends[row, col] != value:
            self._scan_ends[row, col] = value
            self.tilesChanged.emit()

    @property
    def start_tile(self) -> int | None:
        """Index of first tile to acquire (None = start from beginning)."""
        return self._start_tile

    @start_tile.setter
    def start_tile(self, value: int | None) -> None:
        if value != self._start_tile:
            self._start_tile = value
            self.tilesChanged.emit()

    @property
    def stop_tile(self) -> int | None:
        """Index of last tile to acquire (None = go to end)."""
        return self._stop_tile

    @stop_tile.setter
    def stop_tile(self, value: int | None) -> None:
        if value != self._stop_tile:
            self._stop_tile = value
            self.tilesChanged.emit()

    # ===== Computed Properties =====

    @property
    def tile_positions(self) -> np.ndarray:
        """3D array of tile positions [rows, cols, xyz]."""
        grid = self._get_grid_value()
        if grid is None:
            return np.zeros([1, 1, 3])

        coords = np.zeros((grid.rows, grid.columns, 3))
        if self._mode != "bounds":
            for tile in grid:
                x = tile.x if tile.x is not None else 0.0
                y = tile.y if tile.y is not None else 0.0
                coords[tile.row, tile.col, :] = [
                    x + self._grid_offset[0],
                    y + self._grid_offset[1],
                    self._scan_starts[tile.row, tile.col],
                ]
        else:
            for tile in grid:
                coords[tile.row, tile.col, :] = [
                    tile.x if tile.x is not None else 0.0,
                    tile.y if tile.y is not None else 0.0,
                    self._scan_starts[tile.row, tile.col],
                ]
        return coords

    @property
    def scan_volumes(self) -> np.ndarray:
        """2D array of scan volumes (end - start) [rows, cols]."""
        return self._scan_ends - self._scan_starts

    @property
    def path_coords(self) -> list[np.ndarray]:
        """Ordered list of tile coordinates for path visualization."""
        grid = self._get_grid_value()
        if grid is None:
            return []

        positions = self.tile_positions
        return [positions[tile.row, tile.col] for tile in grid]

    # ===== Private Methods =====

    def _update_grid_offset_from_fov(self) -> None:
        """Update grid offset from FOV position for non-anchored axes."""
        for i in range(3):
            if not self._anchor_enabled[i]:
                self._grid_offset[i] = self._fov_position[i]

    def _get_grid_value(self) -> GridRowsColumns | GridFromEdges | GridWidthHeight | None:
        """Get current grid configuration as useq object."""
        over = self._overlap
        common = {
            "reverse": self._reverse,
            "dual_sided": self._dual_sided,
            "overlap": (over, over),
            "mode": self._order,
            "fov_width": self._fov_dimensions[0],
            "fov_height": self._fov_dimensions[1],
        }

        if self._mode == "number":
            return GridRowsColumns(
                rows=self._rows,
                columns=self._columns,
                relative_to="center" if self._relative_to == "center" else "top_left",
                **common,
            )
        elif self._mode == "bounds":
            return GridFromEdges(
                top=self._bounds[1][1],
                left=self._bounds[0][0],
                bottom=self._bounds[1][0],
                right=self._bounds[0][1],
                **common,
            )
        elif self._mode == "area":
            return GridWidthHeight(
                width=self._area_width,
                height=self._area_height,
                relative_to="center" if self._relative_to == "center" else "top_left",
                **common,
            )
        return None

    def _recalculate_tiles(self) -> None:
        """Recalculate tile arrays based on current configuration."""
        grid = self._get_grid_value()
        if grid is None:
            return

        new_rows = grid.rows
        new_cols = grid.columns

        # Resize arrays if needed
        if (new_rows, new_cols) != self._tile_visibility.shape:
            self._tile_visibility = np.resize(self._tile_visibility, [new_rows, new_cols])
            self._scan_starts = np.resize(self._scan_starts, [new_rows, new_cols])
            self._scan_ends = np.resize(self._scan_ends, [new_rows, new_cols])

        self.tilesChanged.emit()

    # ===== Public Methods =====

    def get_grid_value(self) -> GridRowsColumns | GridFromEdges | GridWidthHeight | None:
        """Get current grid configuration as useq object (public accessor)."""
        return self._get_grid_value()

    def apply_to_all_tiles(self, scan_start: float | None = None, scan_end: float | None = None,
                           visible: bool | None = None) -> None:
        """Apply a value to all tiles.

        :param scan_start: Scan start value to apply
        :param scan_end: Scan end value to apply
        :param visible: Visibility to apply
        """
        if scan_start is not None:
            self._scan_starts[:, :] = scan_start
        if scan_end is not None:
            self._scan_ends[:, :] = scan_end
        if visible is not None:
            self._tile_visibility[:, :] = visible
        self.tilesChanged.emit()
