"""VolumeGraphic - 2D visualization widget for acquisition grid.

Displays tiles in X/Y plane with a Z scan range bar on the side.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QTransform, QWheelEvent
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QWidget,
)

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QGraphicsSceneHoverEvent

    from exaspim_control._qtgui.model import InstrumentModel
    from exaspim_control.session import AcqPlan


# Colors for illumination indices
ILLUMINATION_COLORS = [
    QColor("#00bcd4"),  # Cyan - index 0
    QColor("#e040fb"),  # Magenta - index 1
    QColor("#69f0ae"),  # Green - index 2
    QColor("#ffab40"),  # Orange - index 3
]

INACTIVE_COLOR = QColor("#666666")
FOV_COLOR = QColor("#ffeb3b")  # Yellow
PATH_COLOR = QColor("#4caf50")  # Green
BACKGROUND_COLOR = QColor("#1e1e1e")
GRID_COLOR = QColor("#2d2d30")


class GridCellItem(QGraphicsRectItem):
    """Graphics item for computed grid cell borders (no fill)."""

    def __init__(
        self,
        row: int,
        col: int,
        x: float,
        y: float,
        width: float,
        height: float,
        illumination_index: int = 0,
    ):
        super().__init__(0, 0, width, height)
        self.row = row
        self.col = col
        self.cell_x = x
        self.cell_y = y
        self.illumination_index = illumination_index

        self.setPos(x, y)
        self._setup_appearance()

    def _setup_appearance(self) -> None:
        """Set up border-only appearance with cosmetic pen."""
        color_idx = min(self.illumination_index, len(ILLUMINATION_COLORS) - 1)
        border_color = QColor(ILLUMINATION_COLORS[color_idx])
        border_color.setAlpha(150)

        # No fill, cosmetic 1px border (constant screen pixels)
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        pen = QPen(border_color, 1.0)
        pen.setCosmetic(True)  # Width stays 1px regardless of zoom
        self.setPen(pen)


class TileFillItem(QGraphicsRectItem):
    """Graphics item for committed tile fills (no border)."""

    def __init__(
        self,
        row: int,
        col: int,
        x: float,
        y: float,
        width: float,
        height: float,
        illumination_index: int = 0,
        is_enabled: bool = True,
    ):
        super().__init__(0, 0, width, height)
        self.row = row
        self.col = col
        self.tile_x = x
        self.tile_y = y
        self.illumination_index = illumination_index
        self._is_enabled = is_enabled
        self._is_hovered = False
        self._is_selected = False

        self.setPos(x, y)
        self.setAcceptHoverEvents(True)
        self._update_appearance()

    def _update_appearance(self) -> None:
        """Update fill appearance based on state."""
        if self._is_enabled:
            color_idx = min(self.illumination_index, len(ILLUMINATION_COLORS) - 1)
            base_color = ILLUMINATION_COLORS[color_idx]
        else:
            base_color = INACTIVE_COLOR

        # Translucent fill only
        fill_color = QColor(base_color)
        if self._is_hovered:
            fill_color.setAlpha(50)
        elif self._is_selected:
            fill_color.setAlpha(60)
        else:
            fill_color.setAlpha(30)

        self.setBrush(QBrush(fill_color))
        self.setPen(QPen(Qt.PenStyle.NoPen))  # No border

    def set_enabled(self, enabled: bool) -> None:
        self._is_enabled = enabled
        self._update_appearance()

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent | None) -> None:
        if event is not None:
            self._is_hovered = True
            self._update_appearance()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent | None) -> None:
        if event is not None:
            self._is_hovered = False
            self._update_appearance()
        super().hoverLeaveEvent(event)

    def set_selected(self, selected: bool) -> None:
        self._is_selected = selected
        self._update_appearance()


class FOVItem(QGraphicsRectItem):
    """Graphics item representing the current FOV position."""

    def __init__(self, width: float, height: float):
        super().__init__(0, 0, width, height)
        self._setup_appearance()

    def _setup_appearance(self) -> None:
        # Subtle yellow fill
        fill = QColor(FOV_COLOR)
        fill.setAlpha(20)
        self.setBrush(QBrush(fill))

        # Cosmetic dashed border (constant 1px)
        pen = QPen(FOV_COLOR, 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.setPen(pen)

    def set_size(self, width: float, height: float) -> None:
        self.setRect(0, 0, width, height)


class PathItem(QGraphicsPathItem):
    """Graphics item for acquisition path visualization."""

    def __init__(self):
        super().__init__()
        pen = QPen(PATH_COLOR, 1)
        pen.setStyle(Qt.PenStyle.SolidLine)
        pen.setCosmetic(True)  # Constant 1px width
        self.setPen(pen)
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))

    def set_path_coords(self, coords: list[tuple[float, float]], fov_width: float, fov_height: float) -> None:
        """Set path from list of (x, y) tile coordinates."""
        if len(coords) < 2:
            self.setPath(QPainterPath())
            return

        path = QPainterPath()
        # Offset to tile centers
        offset_x = fov_width / 2
        offset_y = fov_height / 2

        # Start at first tile center
        path.moveTo(coords[0][0] + offset_x, coords[0][1] + offset_y)

        # Draw lines to subsequent tiles
        for x, y in coords[1:]:
            path.lineTo(x + offset_x, y + offset_y)

        self.setPath(path)


class PathArrowItem(QGraphicsPathItem):
    """Small arrow indicating path start and direction."""

    def __init__(self):
        super().__init__()
        self._setup_appearance()

    def _setup_appearance(self) -> None:
        """Set up arrow appearance."""
        fill = QColor(PATH_COLOR)
        fill.setAlpha(200)
        self.setBrush(QBrush(fill))

        pen = QPen(PATH_COLOR, 1)
        pen.setCosmetic(True)
        self.setPen(pen)

    def set_position_and_direction(
        self,
        x: float,
        y: float,
        fov_width: float,
        fov_height: float,
        next_x: float | None = None,
        next_y: float | None = None,
    ) -> None:
        """Position arrow at tile center, pointing toward next tile."""

        center_x = x + fov_width / 2
        center_y = y + fov_height / 2
        self.setPos(center_x, center_y)

        # Calculate direction angle (default: right)
        angle = 0.0
        if next_x is not None and next_y is not None:
            next_cx = next_x + fov_width / 2
            next_cy = next_y + fov_height / 2
            dx = next_cx - center_x
            dy = next_cy - center_y
            if dx != 0 or dy != 0:
                angle = math.atan2(dy, dx)

        # Arrow size proportional to FOV (15% of smaller dimension)
        size = min(fov_width, fov_height) * 0.15
        path = QPainterPath()
        # Arrow pointing right, then rotated
        path.moveTo(size, 0)  # Tip
        path.lineTo(-size * 0.5, -size * 0.6)  # Top-left
        path.lineTo(-size * 0.5, size * 0.6)  # Bottom-left
        path.closeSubpath()

        # Apply rotation

        transform = QTransform()
        transform.rotateRadians(angle)
        self.setPath(transform.map(path))


class LimitsRectItem(QGraphicsRectItem):
    """Graphics item showing stage limits boundary."""

    def __init__(self):
        super().__init__()
        self._setup_appearance()

    def _setup_appearance(self) -> None:
        # Very faint gray background
        fill = QColor("#404040")
        fill.setAlpha(15)
        self.setBrush(QBrush(fill))

        # Cosmetic dashed border (constant 1px)
        pen = QPen(QColor("#444444"), 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.setPen(pen)

    def set_limits(self, x_min: float, x_max: float, y_min: float, y_max: float) -> None:
        """Update the limits rectangle."""
        self.setRect(x_min, y_min, x_max - x_min, y_max - y_min)


class PositionDisplay(QWidget):
    """Floating widget showing current FOV position."""

    def __init__(self, unit: str = "mm", parent: QWidget | None = None):
        super().__init__(parent)
        self._unit = unit
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        self.setStyleSheet("""
            PositionDisplay {
                background-color: rgba(30, 30, 30, 200);
                border-radius: 4px;
            }
            QLabel {
                color: #aaaaaa;
                font-size: 11px;
                font-family: monospace;
            }
        """)

        # Position labels
        self._x_label = QLabel("X: 0.000")
        self._y_label = QLabel("Y: 0.000")
        self._z_label = QLabel("Z: 0.000")

        layout.addWidget(self._x_label)
        layout.addWidget(self._y_label)
        layout.addWidget(self._z_label)

        self.adjustSize()

    def set_position(self, x: float, y: float, z: float) -> None:
        """Update the displayed position."""
        self._x_label.setText(f"X: {x:.3f}")
        self._y_label.setText(f"Y: {y:.3f}")
        self._z_label.setText(f"Z: {z:.3f}")
        self.adjustSize()


class FloatingToolbar(QWidget):
    """Floating toolbar overlay for VolumeGraphic view controls."""

    showGridChanged = pyqtSignal(bool)
    showTilesChanged = pyqtSignal(bool)
    showPathChanged = pyqtSignal(bool)
    fitToStageChanged = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self.setStyleSheet("""
            FloatingToolbar {
                background-color: rgba(30, 30, 30, 200);
                border-radius: 4px;
            }
            QToolButton {
                background-color: transparent;
                border: none;
                padding: 4px 8px;
                border-radius: 3px;
                color: #888888;
                font-size: 11px;
            }
            QToolButton:hover {
                background-color: rgba(255, 255, 255, 20);
                color: #aaaaaa;
            }
            QToolButton:checked {
                background-color: rgba(0, 120, 212, 80);
                color: #ffffff;
            }
        """)

        # Grid toggle (computed borders)
        self._grid_btn = QToolButton()
        self._grid_btn.setText("Grid")
        self._grid_btn.setCheckable(True)
        self._grid_btn.setChecked(True)
        self._grid_btn.setToolTip("Show computed grid borders")
        self._grid_btn.toggled.connect(self.showGridChanged.emit)
        layout.addWidget(self._grid_btn)

        # Tiles toggle (committed fills)
        self._tiles_btn = QToolButton()
        self._tiles_btn.setText("Tiles")
        self._tiles_btn.setCheckable(True)
        self._tiles_btn.setChecked(True)
        self._tiles_btn.setToolTip("Show committed tile fills")
        self._tiles_btn.toggled.connect(self.showTilesChanged.emit)
        layout.addWidget(self._tiles_btn)

        # Path toggle
        self._path_btn = QToolButton()
        self._path_btn.setText("Path")
        self._path_btn.setCheckable(True)
        self._path_btn.setChecked(True)
        self._path_btn.setToolTip("Show acquisition path")
        self._path_btn.toggled.connect(self.showPathChanged.emit)
        layout.addWidget(self._path_btn)

        # Fit to stage toggle
        self._stage_btn = QToolButton()
        self._stage_btn.setText("Stage")
        self._stage_btn.setCheckable(True)
        self._stage_btn.setChecked(False)
        self._stage_btn.setToolTip("Fit view to stage limits")
        self._stage_btn.toggled.connect(self.fitToStageChanged.emit)
        layout.addWidget(self._stage_btn)

        self.adjustSize()


class TileGridView(QGraphicsView):
    """2D view of the tile grid in X/Y plane.

    Manages three visual layers:
    - Grid: Computed cell borders (always reflects current config)
    - Tiles: Committed tile fills (reflects committed state)
    - Path: Acquisition order path
    """

    tileClicked = pyqtSignal(int, int, list)  # row, col, position

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        # Configure view
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(BACKGROUND_COLOR))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Layer items
        self._grid_items: list[GridCellItem] = []  # Computed grid borders
        self._tile_items: list[TileFillItem] = []  # Committed tile fills
        self._fov_item: FOVItem | None = None
        self._path_item: PathItem | None = None
        self._start_arrow: PathArrowItem | None = None
        self._limits_item: LimitsRectItem | None = None
        self._selected_tile: TileFillItem | None = None

        # Layer visibility
        self._grid_visible = True
        self._tiles_visible = True

        # State
        self._fov_width = 1.0
        self._fov_height = 1.0
        self._fit_to_stage = False  # False = fit to tiles, True = fit to stage limits
        self._limits: list[list[float]] | None = None  # [[x_min, x_max], [y_min, y_max]]

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        """Zoom with mouse wheel."""
        if event is not None:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:
        """Handle tile clicks."""
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            if isinstance(item, TileFillItem):
                # Clear previous selection
                if self._selected_tile:
                    self._selected_tile.set_selected(False)

                # Select new tile
                item.set_selected(True)
                self._selected_tile = item

                # Emit signal
                pos = [item.tile_x, item.tile_y, 0.0]
                self.tileClicked.emit(item.row, item.col, pos)
                return

        super().mousePressEvent(event)

    def set_grid(
        self,
        grid_cells: list,  # list[GridCell]
        fov_width: float,
        fov_height: float,
    ) -> None:
        """Update grid layer from computed grid cells (borders only)."""
        self._fov_width = fov_width
        self._fov_height = fov_height

        # Clear existing grid items
        for item in self._grid_items:
            self._scene.removeItem(item)
        self._grid_items.clear()

        # Create new grid cell items
        for cell in grid_cells:
            item = GridCellItem(
                row=cell.row,
                col=cell.col,
                x=cell.x,
                y=cell.y,
                width=fov_width,
                height=fov_height,
                illumination_index=cell.illumination_index,
            )
            item.setVisible(self._grid_visible)
            item.setZValue(1)  # Above tiles
            self._scene.addItem(item)
            self._grid_items.append(item)

        self._update_scene_rect()

    def set_tiles(
        self,
        tiles: list,  # list[Tile]
        fov_width: float,
        fov_height: float,
    ) -> None:
        """Update tiles layer from committed tiles (fills only)."""
        self._fov_width = fov_width
        self._fov_height = fov_height

        # Clear existing tile items
        for item in self._tile_items:
            self._scene.removeItem(item)
        self._tile_items.clear()
        self._selected_tile = None

        # Create new tile fill items
        for tile in tiles:
            item = TileFillItem(
                row=tile.row,
                col=tile.col,
                x=tile.x,
                y=tile.y,
                width=fov_width,
                height=fov_height,
                illumination_index=tile.illumination_index,
                is_enabled=tile.is_enabled,
            )
            item.setVisible(self._tiles_visible)
            item.setZValue(0)  # Below grid
            self._scene.addItem(item)
            self._tile_items.append(item)

        self._update_scene_rect()

    def set_fov_position(self, x: float, y: float, width: float, height: float) -> None:
        """Update FOV marker position."""
        if self._fov_item is None:
            self._fov_item = FOVItem(width, height)
            self._scene.addItem(self._fov_item)

        self._fov_item.set_size(width, height)
        self._fov_item.setPos(x, y)

    def set_path(self, tiles: list, fov_width: float, fov_height: float) -> None:
        """Update acquisition path visualization with start arrow."""
        # Create path item if needed
        if self._path_item is None:
            self._path_item = PathItem()
            self._scene.addItem(self._path_item)
            self._path_item.setZValue(-1)  # Behind tiles

        # Create start arrow if needed
        if self._start_arrow is None:
            self._start_arrow = PathArrowItem()
            self._scene.addItem(self._start_arrow)
            self._start_arrow.setZValue(5)  # Above everything

        # Get enabled tiles
        enabled_tiles = [t for t in tiles if t.is_enabled]
        coords = [(t.x, t.y) for t in enabled_tiles]

        # Set path line
        self._path_item.set_path_coords(coords, fov_width, fov_height)

        # Position start arrow
        if enabled_tiles:
            first = enabled_tiles[0]
            # Get next tile for direction (if available)
            next_x = enabled_tiles[1].x if len(enabled_tiles) > 1 else None
            next_y = enabled_tiles[1].y if len(enabled_tiles) > 1 else None
            self._start_arrow.set_position_and_direction(first.x, first.y, fov_width, fov_height, next_x, next_y)
            self._start_arrow.setVisible(True)
        else:
            self._start_arrow.setVisible(False)

    def set_path_visible(self, visible: bool) -> None:
        """Show/hide acquisition path and arrow."""
        if self._path_item:
            self._path_item.setVisible(visible)
        if self._start_arrow:
            self._start_arrow.setVisible(visible)

    def set_grid_visible(self, visible: bool) -> None:
        """Show/hide grid layer (computed cell borders)."""
        self._grid_visible = visible
        for item in self._grid_items:
            item.setVisible(visible)

    def set_tiles_visible(self, visible: bool) -> None:
        """Show/hide tiles layer (committed tile fills)."""
        self._tiles_visible = visible
        for item in self._tile_items:
            item.setVisible(visible)

    def set_limits(self, limits: list[list[float]]) -> None:
        """Set stage limits [[x_min, x_max], [y_min, y_max], ...].

        The displayed rectangle is extended by FOV dimensions since tiles are
        anchored top-left, so the visible area extends beyond the position limits.
        """
        if len(limits) < 2:
            return

        self._limits = limits

        # Create limits item if needed
        if self._limits_item is None:
            self._limits_item = LimitsRectItem()
            self._scene.addItem(self._limits_item)
            # Limits should be behind everything
            self._limits_item.setZValue(-10)

        # Extend limits by FOV to show actual visible area
        x_min, x_max = limits[0]
        y_min, y_max = limits[1]
        self._limits_item.set_limits(x_min, x_max + self._fov_width, y_min, y_max + self._fov_height)

        # Update scene rect to include limits
        self._update_scene_rect()

    def set_fit_to_stage(self, fit_to_stage: bool) -> None:
        """Set fit mode: True = fit to stage limits, False = fit to tiles."""
        self._fit_to_stage = fit_to_stage
        self.fit_to_contents()

    def fit_to_contents(self) -> None:
        """Fit view based on current fit mode."""
        if self._fit_to_stage and self._limits is not None:
            # Fit to stage limits (extended by FOV to match displayed rectangle)
            x_min, x_max = self._limits[0]
            y_min, y_max = self._limits[1]
            x_max += self._fov_width
            y_max += self._fov_height
            padding = max(self._fov_width, self._fov_height) * 0.5
            rect = QRectF(
                x_min - padding,
                y_min - padding,
                (x_max - x_min) + 2 * padding,
                (y_max - y_min) + 2 * padding,
            )
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        else:
            # Fit to grid/tile bounds (not scene rect which includes stage limits)
            rect = self._compute_grid_bounds()
            if rect is not None:
                self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _compute_grid_bounds(self) -> QRectF | None:
        """Compute bounding rect of grid cells and tiles only (excludes stage limits)."""
        min_x: float | None = None
        max_x: float | None = None
        min_y: float | None = None
        max_y: float | None = None

        # Include grid items (computed borders)
        for item in self._grid_items:
            if min_x is None:
                min_x = item.cell_x
                max_x = item.cell_x + self._fov_width
                min_y = item.cell_y
                max_y = item.cell_y + self._fov_height
            else:
                assert max_x is not None
                assert min_y is not None
                assert max_y is not None
                min_x = min(min_x, item.cell_x)
                max_x = max(max_x, item.cell_x + self._fov_width)
                min_y = min(min_y, item.cell_y)
                max_y = max(max_y, item.cell_y + self._fov_height)

        # Include tile items (committed fills)
        for item in self._tile_items:
            if min_x is None:
                min_x = item.tile_x
                max_x = item.tile_x + self._fov_width
                min_y = item.tile_y
                max_y = item.tile_y + self._fov_height
            else:
                assert max_x is not None
                assert min_y is not None
                assert max_y is not None
                min_x = min(min_x, item.tile_x)
                max_x = max(max_x, item.tile_x + self._fov_width)
                min_y = min(min_y, item.tile_y)
                max_y = max(max_y, item.tile_y + self._fov_height)

        if min_x is None:
            return None
        assert max_x is not None
        assert min_y is not None
        assert max_y is not None

        # Add padding
        padding = max(self._fov_width, self._fov_height) * 0.5
        return QRectF(
            min_x - padding,
            min_y - padding,
            (max_x - min_x) + 2 * padding,
            (max_y - min_y) + 2 * padding,
        )

    def _update_scene_rect(self) -> None:
        """Update scene rect to fit tiles and limits."""
        # Start with limits bounds if available (extended by FOV)
        if self._limits is not None and len(self._limits) >= 2:
            min_x, max_x = self._limits[0]
            min_y, max_y = self._limits[1]
            max_x += self._fov_width
            max_y += self._fov_height
        elif self._tile_items:
            min_x = min(t.tile_x for t in self._tile_items)
            max_x = max(t.tile_x + self._fov_width for t in self._tile_items)
            min_y = min(t.tile_y for t in self._tile_items)
            max_y = max(t.tile_y + self._fov_height for t in self._tile_items)
        else:
            return

        # Expand to include tiles if they exceed limits
        if self._tile_items:
            min_x = min(min_x, *(t.tile_x for t in self._tile_items))
            max_x = max(max_x, *(t.tile_x + self._fov_width for t in self._tile_items))
            min_y = min(min_y, *(t.tile_y for t in self._tile_items))
            max_y = max(max_y, *(t.tile_y + self._fov_height for t in self._tile_items))

        # Add padding
        padding = max(self._fov_width, self._fov_height)
        rect = QRectF(
            min_x - padding,
            min_y - padding,
            (max_x - min_x) + 2 * padding,
            (max_y - min_y) + 2 * padding,
        )
        self._scene.setSceneRect(rect)


class ZBarWidget(QFrame):
    """Vertical bar showing Z scan range."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(50)
        self.setMaximumWidth(60)
        # Subtle border matching TileGridView style
        self.setStyleSheet("""
            ZBarWidget {
                border: 1px solid #2d2d30;
                border-radius: 2px;
            }
        """)

        # State
        self._z_min = 0.0
        self._z_max = 100.0
        self._scan_start = 0.0
        self._scan_end = 50.0
        self._fov_z = 25.0
        self._unit = "mm"

    def set_range(self, z_min: float, z_max: float) -> None:
        """Set the Z axis limits."""
        self._z_min = z_min
        self._z_max = z_max
        self.update()

    def set_scan_range(self, start: float, end: float) -> None:
        """Set the scan range to display."""
        self._scan_start = start
        self._scan_end = end
        self.update()

    def set_fov_z(self, z: float) -> None:
        """Set current FOV Z position."""
        self._fov_z = z
        self.update()

    def set_unit(self, unit: str) -> None:
        """Set the unit label."""
        self._unit = unit
        self.update()

    def paintEvent(self, a0) -> None:
        """Custom paint for Z bar."""
        super().paintEvent(a0)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.contentsRect()
        margin = 8
        bar_left = margin
        bar_right = rect.width() - margin
        bar_top = margin + 15  # Space for max value
        bar_bottom = rect.height() - margin - 15  # Space for min value
        bar_height = bar_bottom - bar_top

        if bar_height <= 0 or self._z_max <= self._z_min:
            return

        # Draw background
        painter.fillRect(rect, BACKGROUND_COLOR)

        # Draw the bar outline (subtle)
        bar_rect = QRectF(bar_left, bar_top, bar_right - bar_left, bar_height)
        painter.setPen(QPen(QColor("#3a3a3a"), 1))
        painter.drawRect(bar_rect)

        # Helper to convert Z value to Y pixel
        def z_to_y(z: float) -> float:
            normalized = (z - self._z_min) / (self._z_max - self._z_min)
            return bar_bottom - normalized * bar_height

        # Draw scan range
        scan_top = z_to_y(self._scan_end)
        scan_bottom = z_to_y(self._scan_start)
        scan_rect = QRectF(bar_left + 2, scan_top, bar_right - bar_left - 4, scan_bottom - scan_top)

        scan_color = QColor(ILLUMINATION_COLORS[0])
        scan_color.setAlpha(100)
        painter.fillRect(scan_rect, scan_color)
        painter.setPen(QPen(ILLUMINATION_COLORS[0], 2))
        painter.drawRect(scan_rect)

        # Draw FOV Z marker
        fov_y = z_to_y(self._fov_z)
        painter.setPen(QPen(FOV_COLOR, 2))
        painter.drawLine(int(bar_left - 5), int(fov_y), int(bar_right + 5), int(fov_y))

        # Draw Z values at bottom
        painter.setPen(QPen(QColor("#888888")))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        # Min value
        painter.drawText(
            rect.left(),
            bar_bottom + 5,
            rect.width(),
            15,
            Qt.AlignmentFlag.AlignHCenter,
            f"{self._z_min:.1f}",
        )

        # Max value (at top)
        painter.drawText(
            rect.left(),
            bar_top - 15,
            rect.width(),
            15,
            Qt.AlignmentFlag.AlignHCenter,
            f"{self._z_max:.1f}",
        )


class VolumeGraphic(QWidget):
    """2D volume visualization widget.

    Shows tiles in X/Y plane with a Z scan range bar on the side.
    """

    fovMove = pyqtSignal(list)  # Emitted when user wants to move FOV to a tile

    def __init__(
        self,
        model: InstrumentModel,
        plan: AcqPlan,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._model = model
        self._plan = plan

        self._setup_ui()
        self._connect_signals()
        self.refresh()

    def _setup_ui(self) -> None:
        """Build the UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Z bar (left side)
        self._z_bar = ZBarWidget()
        self._z_bar.set_unit(self._model.unit)
        layout.addWidget(self._z_bar)

        # Tile grid view (main area)
        self._grid_view = TileGridView()
        layout.addWidget(self._grid_view, stretch=1)

        # Floating toolbar (overlaid on grid view, top-left)
        self._toolbar = FloatingToolbar(self)
        self._toolbar.showGridChanged.connect(self.set_grid_visible)
        self._toolbar.showTilesChanged.connect(self.set_tiles_visible)
        self._toolbar.showPathChanged.connect(self.set_path_visible)
        self._toolbar.fitToStageChanged.connect(self.set_fit_to_stage)

        # Position display (overlaid on grid view, top-right)
        self._position_display = PositionDisplay(unit=self._model.unit, parent=self)
        fov_pos = self._model.fov_position
        self._position_display.set_position(fov_pos[0], fov_pos[1], fov_pos[2])

    def _connect_signals(self) -> None:
        """Connect signals."""
        # Model signals
        self._model.fovPositionChanged.connect(self._on_fov_changed)
        self._model.fovDimensionsChanged.connect(self._on_fov_changed)
        self._model.stageLimitsChanged.connect(self._on_limits_changed)

        # Grid view signals
        self._grid_view.tileClicked.connect(self._on_tile_clicked)

    def refresh(self) -> None:
        """Refresh visualization from plan and model.

        Updates both layers:
        - Grid layer: computed cells from plan.grid (always reflects current config)
        - Tiles layer: committed tiles from plan.tiles (reflects committed state)
        """
        fov = self._model.fov_dimensions
        fov_pos = self._model.fov_position
        limits = self._model.stage_limits

        # Update limits first (so scene rect includes them)
        if limits:
            self._grid_view.set_limits(limits)
            if len(limits) > 2:
                self._z_bar.set_range(limits[2][0], limits[2][1])

        # Update grid layer (computed borders - always fresh)
        self._grid_view.set_grid(self._plan.grid, fov[0], fov[1])

        # Update tiles layer (committed fills)
        self._grid_view.set_tiles(self._plan.tiles, fov[0], fov[1])

        # Update FOV and path
        self._grid_view.set_fov_position(fov_pos[0], fov_pos[1], fov[0], fov[1])
        self._grid_view.set_path(self._plan.tiles, fov[0], fov[1])

        # Update Z bar with scan range from plan
        self._z_bar.set_scan_range(self._plan.z_start, self._plan.z_end)
        self._z_bar.set_fov_z(fov_pos[2])

        # Fit view on first load
        self._grid_view.fit_to_contents()

    def _on_fov_changed(self, _) -> None:
        """Handle FOV position/dimension changes."""
        fov = self._model.fov_dimensions
        fov_pos = self._model.fov_position

        self._grid_view.set_fov_position(fov_pos[0], fov_pos[1], fov[0], fov[1])
        self._z_bar.set_fov_z(fov_pos[2])
        self._position_display.set_position(fov_pos[0], fov_pos[1], fov_pos[2])

    def _on_limits_changed(self, limits: list) -> None:
        """Handle stage limits changes."""
        # Update grid view with X/Y limits
        if len(limits) >= 2:
            self._grid_view.set_limits(limits)

        # Update Z bar with Z limits
        if len(limits) > 2:
            self._z_bar.set_range(limits[2][0], limits[2][1])

    def _on_tile_clicked(self, row: int, col: int, pos: list) -> None:
        """Handle tile click - emit signal to move FOV."""
        tile = self._plan.get_tile(row, col)
        if tile:
            pos = [tile.x, tile.y, tile.z]
            self.fovMove.emit(pos)

    def set_grid_visible(self, visible: bool) -> None:
        """Show/hide grid layer (computed cell borders)."""
        self._grid_view.set_grid_visible(visible)

    def set_tiles_visible(self, visible: bool) -> None:
        """Show/hide tiles layer (committed tile fills)."""
        self._grid_view.set_tiles_visible(visible)

    def set_path_visible(self, visible: bool) -> None:
        """Show/hide acquisition path."""
        self._grid_view.set_path_visible(visible)

    def set_fit_to_stage(self, fit_to_stage: bool) -> None:
        """Set fit mode: True = fit to stage limits, False = fit to tiles."""
        self._grid_view.set_fit_to_stage(fit_to_stage)

    def fit_to_contents(self) -> None:
        """Fit view to show all content."""
        self._grid_view.fit_to_contents()

    def resizeEvent(self, a0) -> None:
        """Reposition floating widgets on resize."""
        super().resizeEvent(a0)
        # Position toolbar in top-left of grid view (after Z bar)
        z_bar_width = self._z_bar.width()
        self._toolbar.move(z_bar_width + 12, 8)

        # Position display in top-right of grid view
        total_width = self.width()
        display_width = self._position_display.width()
        self._position_display.move(total_width - display_width - 8, 8)
