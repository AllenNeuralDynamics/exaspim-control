"""SessionPlanner - Grid configuration widget for acquisition planning."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from exaspim_control.qtgui.primitives import (
    FormBuilder,
    HStack,
    VButton,
    VCheckBox,
    VComboBox,
    VDoubleSpinBox,
    VLabel,
    VSpinBox,
)
from exaspim_control.session import AcqPlan, OrderMode

if TYPE_CHECKING:
    from exaspim_control.qtgui.model import InstrumentModel


class SessionPlanner(QWidget):
    """Grid configuration widget.

    Provides controls for:
    - Grid size (rows, columns)
    - Grid options (overlap, order, reverse, illumination paths)
    - Origin/anchor controls
    - Tile table with scan ranges and visibility
    """

    planChanged = pyqtSignal()

    def __init__(
        self,
        model: InstrumentModel,
        plan: AcqPlan,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._model = model
        self._plan = plan
        self._updating = False
        self._unit = model.unit

        # Link states for table columns
        self._enabled_linked = True
        self._z_start_linked = True
        self._z_end_linked = True
        self._illum_linked = True

        # === Create all widgets ===

        # Grid configuration
        self._set_origin_btn = VButton("Set from FOV", variant="secondary")

        self._rows = VSpinBox(min=1, max=100)
        self._columns = VSpinBox(min=1, max=100)

        self._overlap = VDoubleSpinBox(min=0.0, max=99.0, decimals=1)
        self._overlap.setSuffix(" %")

        self._order = VComboBox(items=[m.value for m in OrderMode])

        self._reverse = VCheckBox()

        self._z_start = VDoubleSpinBox(min=-10000.0, max=10000.0, decimals=2)

        self._z_start_fov_btn = VButton("FOV", variant="secondary")
        self._z_start_fov_btn.setToolTip("Set Z start from current FOV position")
        self._z_start_fov_btn.setFixedWidth(40)

        self._z_end = VDoubleSpinBox(min=-10000.0, max=10000.0, decimals=2)

        self._z_end_fov_btn = VButton("FOV", variant="secondary")
        self._z_end_fov_btn.setToolTip("Set Z end from current FOV position")
        self._z_end_fov_btn.setFixedWidth(40)

        self._illum_count = VSpinBox(min=1, max=4)

        # Table header widgets
        self._init_row = VSpinBox(min=0, max=99)
        self._init_row.setToolTip("Starting row")
        self._init_row.setFixedWidth(50)

        self._init_col = VSpinBox(min=0, max=99)
        self._init_col.setToolTip("Starting column")
        self._init_col.setFixedWidth(50)

        self._commit_btn = VButton("Commit", variant="primary")
        self._commit_btn.setToolTip("Lock grid configuration and create tiles")

        self._clear_btn = VButton("Clear", variant="secondary")
        self._clear_btn.setToolTip("Clear tiles and unlock grid configuration")

        self._reset_btn = VButton("Reset Status", variant="secondary")
        self._reset_btn.setToolTip("Reset all tiles to pending status")

        self._table = QTableWidget()
        self._table.setColumnCount(8)

        # === Build layout ===
        self._setup_layout()
        self._configure_table()
        self._connect_signals()
        self._sync_from_plan()

    def _setup_layout(self) -> None:
        """Compose layout from pre-created widgets."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

    def _build_left_panel(self) -> QScrollArea:
        """Compose left panel using FormBuilder."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(220)
        scroll.setMaximumWidth(280)

        form = (
            FormBuilder()
            .header("Configure Grid")
            .field("Origin", self._set_origin_btn)
            .field("Rows", self._rows)
            .field("Cols", self._columns)
            .field("Overlap", self._overlap)
            .field("Order", self._order)
            .field("Reverse", self._reverse)
            .field("Start at", HStack(self._init_row, self._init_col, spacing=4))
            .field("Z start", HStack(self._z_start, self._z_start_fov_btn))
            .field("Z end", HStack(self._z_end, self._z_end_fov_btn))
            .field("Illum paths", self._illum_count)
            .build()
        )

        # Wrap in container with margins
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(form)
        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _build_right_panel(self) -> QWidget:
        """Compose right panel with table."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Action buttons row
        actions = HStack(
            self._commit_btn,
            self._clear_btn,
            self._reset_btn,
            spacing=4,
        )

        layout.addWidget(actions)
        layout.addWidget(self._table)

        return container

    def _configure_table(self) -> None:
        """Configure table appearance and headers."""
        self._update_table_headers()

        if (hheader := self._table.horizontalHeader()) is not None:
            hheader.setSectionsMovable(True)
            hheader.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            hheader.resizeSection(0, 60)  # Tile
            hheader.resizeSection(1, 70)  # X
            hheader.resizeSection(2, 70)  # Y
            hheader.resizeSection(3, 30)  # Enabled
            hheader.resizeSection(4, 90)  # Z Start
            hheader.resizeSection(5, 90)  # Z End
            hheader.resizeSection(6, 40)  # Illum
            hheader.resizeSection(7, 70)  # Status
            hheader.setStretchLastSection(True)
            hheader.sectionClicked.connect(self._on_header_clicked)

        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

    def _connect_signals(self) -> None:
        """Connect UI signals to handlers."""
        # Grid config
        self._set_origin_btn.clicked.connect(self._on_set_origin)
        self._rows.valueChanged.connect(self._on_rows_changed)
        self._columns.valueChanged.connect(self._on_columns_changed)
        self._overlap.valueChanged.connect(self._on_overlap_changed)
        self._order.currentTextChanged.connect(self._on_order_changed)
        self._init_row.valueChanged.connect(self._on_init_tile_changed)
        self._init_col.valueChanged.connect(self._on_init_tile_changed)
        self._reverse.toggled.connect(self._on_reverse_changed)
        self._z_start.valueChanged.connect(self._on_z_start_changed)
        self._z_end.valueChanged.connect(self._on_z_end_changed)
        self._z_start_fov_btn.clicked.connect(self._on_set_z_start_from_fov)
        self._z_end_fov_btn.clicked.connect(self._on_set_z_end_from_fov)
        self._illum_count.valueChanged.connect(self._on_illum_count_changed)

        # Commit/Clear/Reset
        self._commit_btn.clicked.connect(self._on_commit)
        self._clear_btn.clicked.connect(self._on_clear)
        self._reset_btn.clicked.connect(self._on_reset_status)

        # Table
        self._table.cellChanged.connect(self._on_table_cell_changed)

    def _sync_from_plan(self) -> None:
        """Sync UI state from plan."""
        self._updating = True
        try:
            self._rows.setValue(self._plan.rows)
            self._columns.setValue(self._plan.columns)
            self._overlap.setValue(self._plan.overlap)
            self._order.setCurrentText(self._plan.order.value)
            self._init_row.setValue(self._plan.anchor[0])
            self._init_col.setValue(self._plan.anchor[1])
            self._reverse.setChecked(self._plan.reverse)
            self._z_start.setValue(self._plan.z_start)
            self._z_end.setValue(self._plan.z_end)
            self._illum_count.setValue(self._plan.illumination_count)

            self._refresh_table()
            self._update_controls_enabled()
        finally:
            self._updating = False

    def _refresh_table(self) -> None:
        """Refresh the tile table from plan."""
        tiles = self._plan.tiles
        if not tiles:
            self._table.setRowCount(0)
            return

        self._updating = True
        try:
            self._table.setRowCount(len(tiles))

            for i, tile in enumerate(tiles):
                # Column 0: Tile ID (read-only)
                id_item = QTableWidgetItem(f"({tile.row}, {tile.col})")
                id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(i, 0, id_item)

                # Column 1: X position (read-only)
                x_item = QTableWidgetItem(f"{tile.x:.3f}")
                x_item.setFlags(x_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(i, 1, x_item)

                # Column 2: Y position (read-only)
                y_item = QTableWidgetItem(f"{tile.y:.3f}")
                y_item.setFlags(y_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(i, 2, y_item)

                # Column 3: Enabled (checkbox)
                enabled_item = QTableWidgetItem()
                enabled_item.setFlags(enabled_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                enabled_item.setCheckState(Qt.CheckState.Checked if tile.is_enabled else Qt.CheckState.Unchecked)
                self._table.setItem(i, 3, enabled_item)

                # Column 4: Z start (editable)
                z_start_item = QTableWidgetItem(f"{tile.z:.3f}")
                self._table.setItem(i, 4, z_start_item)

                # Column 5: Z end (editable)
                z_end_item = QTableWidgetItem(f"{tile.z_end:.3f}")
                self._table.setItem(i, 5, z_end_item)

                # Column 6: Illumination index (editable)
                illum_item = QTableWidgetItem(str(tile.illumination_index))
                self._table.setItem(i, 6, illum_item)

                # Column 7: Status (read-only)
                status_item = QTableWidgetItem(tile.status.value)
                status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(i, 7, status_item)

        finally:
            self._updating = False

    def _update_table_headers(self) -> None:
        """Update table headers with link indicators."""
        enabled_prefix = "🔗" if self._enabled_linked else "☑"
        z_start_prefix = "🔗 " if self._z_start_linked else ""
        z_end_prefix = "🔗 " if self._z_end_linked else ""
        illum_prefix = "🔗 " if self._illum_linked else ""
        self._table.setHorizontalHeaderLabels(
            [
                "Tile",
                f"X ({self._unit})",
                f"Y ({self._unit})",
                enabled_prefix,
                f"{z_start_prefix}Z Start",
                f"{z_end_prefix}Z End",
                f"{illum_prefix}Illum",
                "Status",
            ]
        )

    def _on_header_clicked(self, logical_index: int) -> None:
        """Handle header clicks for link toggles."""
        if logical_index == 3:
            self._enabled_linked = not self._enabled_linked
            self._update_table_headers()
        elif logical_index == 4:
            self._z_start_linked = not self._z_start_linked
            self._update_table_headers()
        elif logical_index == 5:
            self._z_end_linked = not self._z_end_linked
            self._update_table_headers()
        elif logical_index == 6:
            self._illum_linked = not self._illum_linked
            self._update_table_headers()

    # ===== Event Handlers =====

    def _on_rows_changed(self, value: int) -> None:
        if not self._updating:
            self._plan.rows = value
            self._notify_change()

    def _on_columns_changed(self, value: int) -> None:
        if not self._updating:
            self._plan.columns = value
            self._notify_change()

    def _on_overlap_changed(self, value: float) -> None:
        if not self._updating:
            self._plan.overlap = value
            self._notify_change()

    def _on_order_changed(self, text: str) -> None:
        if not self._updating:
            self._plan.order = OrderMode(text)
            self._notify_change()

    def _on_reverse_changed(self, checked: bool) -> None:
        if not self._updating:
            self._plan.reverse = checked
            self._notify_change()

    def _on_illum_count_changed(self, value: int) -> None:
        if not self._updating:
            self._plan.illumination_count = value
            self._notify_change()

    def _on_set_origin(self) -> None:
        """Set grid origin to current FOV position."""
        self._plan.origin = list(self._model.fov_position)
        self._notify_change()

    def _on_init_tile_changed(self) -> None:
        """Handle init tile (starting tile) change."""
        if not self._updating:
            self._plan.anchor = (self._init_row.value(), self._init_col.value())
            self._notify_change()

    def _on_z_start_changed(self, value: float) -> None:
        if not self._updating:
            self._plan.z_start = value
            self._notify_change()

    def _on_z_end_changed(self, value: float) -> None:
        if not self._updating:
            self._plan.z_end = value
            self._notify_change()

    def _on_set_z_start_from_fov(self) -> None:
        """Set Z start from current FOV Z position."""
        z = self._model.fov_position[2]
        self._z_start.setValue(z)
        self._plan.z_start = z
        self._notify_change()

    def _on_set_z_end_from_fov(self) -> None:
        """Set Z end from current FOV Z position."""
        z = self._model.fov_position[2]
        self._z_end.setValue(z)
        self._plan.z_end = z
        self._notify_change()

    def _on_reset_status(self) -> None:
        """Reset all tiles to pending status."""
        self._plan.reset_all_status()
        self._notify_change()

    def _on_table_cell_changed(self, table_row: int, col: int) -> None:
        """Handle table cell edits."""
        if self._updating:
            return

        tiles = self._plan.tiles
        if table_row >= len(tiles):
            return

        tile = tiles[table_row]
        item = self._table.item(table_row, col)
        if item is None:
            return

        try:
            if col == 3:  # Enabled checkbox
                enabled = item.checkState() == Qt.CheckState.Checked
                if self._enabled_linked:
                    self._plan.set_all_enabled(enabled=enabled)
                else:
                    tile.is_enabled = enabled
                self._notify_change()

            elif col == 4:  # Z Start
                value = float(item.text())
                if self._z_start_linked:
                    for t in tiles:
                        t.z = value
                else:
                    tile.z = value
                self._notify_change()

            elif col == 5:  # Z End
                value = float(item.text())
                if self._z_end_linked:
                    for t in tiles:
                        t.z_end = value
                else:
                    tile.z_end = value
                self._notify_change()

            elif col == 6:  # Illumination index
                value = int(item.text())
                # Clamp to valid range
                max_illum = self._plan.illumination_count - 1
                value = max(0, min(value, max_illum))
                if self._illum_linked:
                    self._plan.set_all_illumination(value)
                else:
                    tile.illumination_index = value
                self._notify_change()

        except ValueError:
            self._refresh_table()

    def _on_commit(self) -> None:
        """Commit the grid - lock config and create tiles."""
        self._plan.commit()
        self._update_controls_enabled()
        self._notify_change()

    def _on_clear(self) -> None:
        """Clear tiles - unlock config and remove tiles."""
        self._plan.clear()
        self._update_controls_enabled()
        self._notify_change()

    def _update_controls_enabled(self) -> None:
        """Enable/disable grid controls based on commit state."""
        is_committed = self._plan.is_committed
        is_planning = not is_committed

        # Grid config controls (only changeable before commit)
        self._set_origin_btn.setEnabled(is_planning)
        self._rows.setEnabled(is_planning)
        self._columns.setEnabled(is_planning)
        self._overlap.setEnabled(is_planning)
        self._order.setEnabled(is_planning)
        self._reverse.setEnabled(is_planning)
        self._init_row.setEnabled(is_planning)
        self._init_col.setEnabled(is_planning)
        self._z_start.setEnabled(is_planning)
        self._z_end.setEnabled(is_planning)
        self._z_start_fov_btn.setEnabled(is_planning)
        self._z_end_fov_btn.setEnabled(is_planning)
        self._illum_count.setEnabled(is_planning)

        # Button states
        self._commit_btn.setEnabled(is_planning)
        self._clear_btn.setEnabled(is_committed)
        self._reset_btn.setEnabled(is_committed)

    def _notify_change(self) -> None:
        """Refresh local UI and emit planChanged signal."""
        self._refresh_table()
        self.planChanged.emit()
