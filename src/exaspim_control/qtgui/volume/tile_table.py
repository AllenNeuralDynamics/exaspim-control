"""TileTable - Table widget for viewing and editing tile configurations.

This widget displays the tile configuration in a table and allows editing
scan start/end values and visibility. It subscribes to VolumeModel for updates.
"""

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from exaspim_control.qtgui.misc.q_item_delegates import QSpinItemDelegate
from exaspim_control.qtgui.misc.q_start_stop_table_header import QStartStopTableHeader

from .volume_model import VolumeModel


class TileTable(QWidget):
    """Table widget for viewing and editing tile configurations.

    Displays tiles with their positions, scan ranges, and visibility.
    Connects to VolumeModel for shared state management.
    """

    valueChanged = pyqtSignal(object)

    def __init__(
        self,
        model: VolumeModel,
        parent: QWidget | None = None,
    ):
        """Initialize TileTable.

        :param model: VolumeModel instance containing shared state
        :param parent: Parent widget
        """
        super().__init__(parent=parent)

        self._model = model
        self.coordinate_plane = model.coordinate_plane_clean
        self.unit = model.unit

        # Apply all setting (local to this widget)
        self._apply_all = True

        layout = QVBoxLayout()

        # Apply all checkbox
        apply_all_layout = QHBoxLayout()
        self.apply_all_box = QCheckBox("Apply to all")
        self.apply_all_box.setChecked(True)
        self.apply_all_box.toggled.connect(self._set_apply_all)
        apply_all_layout.addWidget(self.apply_all_box)
        apply_all_layout.addStretch()
        layout.addLayout(apply_all_layout)

        # Create table
        self.table_columns = [
            "row, column",
            *[f"{x} [{self.unit}]" for x in self.coordinate_plane],
            f"{self.coordinate_plane[2]} max [{self.unit}]",
            "visibility",
        ]
        self.tile_table = QTableWidget()

        # Configure header with start/stop tile selection
        self.header = QStartStopTableHeader(self.tile_table)
        self.header.startChanged.connect(self._on_start_changed)
        self.header.stopChanged.connect(self._on_stop_changed)
        self.tile_table.setVerticalHeader(self.header)

        self.tile_table.setColumnCount(len(self.table_columns))
        self.tile_table.setHorizontalHeaderLabels(self.table_columns)
        self.tile_table.resizeColumnsToContents()

        # Set up delegates for editable columns
        for i in range(1, len(self.table_columns)):
            column_name = self.tile_table.horizontalHeaderItem(i).text()
            delegate = QSpinItemDelegate()
            setattr(self, f"table_column_{column_name}_delegate", delegate)
            self.tile_table.setItemDelegateForColumn(i, delegate)

        self.tile_table.itemChanged.connect(self._on_tile_table_changed)
        layout.addWidget(self.tile_table)

        self.setLayout(layout)

        # Connect to model signals
        self._model.tilesChanged.connect(self._on_tiles_changed)
        self._model.gridChanged.connect(self._on_grid_changed)

        # Initial population
        self._refill_table()

    def _on_start_changed(self, index: int) -> None:
        """Handle start tile index change."""
        self._model.start_tile = index

    def _on_stop_changed(self, index: int) -> None:
        """Handle stop tile index change."""
        self._model.stop_tile = index

    def _set_apply_all(self, checked: bool) -> None:
        """Handle apply all checkbox toggle."""
        self._apply_all = checked

        # Update values if apply_all enabled
        if checked:
            # Apply first tile's settings to all
            tile_visibility = self._model.tile_visibility
            scan_starts = self._model.scan_starts
            scan_ends = self._model.scan_ends

            if tile_visibility.size > 0:
                self._model.apply_to_all_tiles(
                    scan_start=scan_starts[0, 0],
                    scan_end=scan_ends[0, 0],
                    visible=bool(tile_visibility[0, 0]),
                )

        self._refill_table()

    @property
    def apply_all(self) -> bool:
        """Return whether settings for tile [0,0] apply to all tiles."""
        return self._apply_all

    def _on_tiles_changed(self) -> None:
        """Handle tiles changed signal from model."""
        self._update_tile_table()

    def _on_grid_changed(self) -> None:
        """Handle grid configuration change from model."""
        self._refill_table()

    def _update_tile_table(self) -> None:
        """Update tile table when values change."""
        grid = self._model.get_grid_value()
        if grid is None:
            return

        # Check if order changed
        table_order = [
            [int(x) for x in self.tile_table.item(i, 0).text() if x.isdigit()]
            for i in range(self.tile_table.rowCount())
        ]
        value_order = [[t.row, t.col] for t in grid]
        order_matches = np.array_equal(table_order, value_order)
        if not order_matches:
            self._refill_table()
            return

        # Check if tile positions match
        table_pos = [
            [self.tile_table.item(j, i).data(Qt.ItemDataRole.EditRole) for i in range(1, 4)]
            for j in range(self.tile_table.rowCount())
        ]
        value_pos = self._model.tile_positions
        # Flatten value_pos for comparison
        value_pos_list = [
            [value_pos[t.row, t.col, 0], value_pos[t.row, t.col, 1], value_pos[t.row, t.col, 2]] for t in grid
        ]
        pos_matches = np.array_equal(table_pos, value_pos_list)
        if not pos_matches:
            self._refill_table()

    def _refill_table(self) -> None:
        """Clear and populate tile table with current tile configuration."""
        grid = self._model.get_grid_value()
        if grid is None:
            return

        self.tile_table.clearContents()
        self.tile_table.setRowCount(0)

        for tile in grid:
            self._add_tile_to_table(tile.row, tile.col)

        # Restore start/stop indices
        self.header.blockSignals(True)
        if self._model.start_tile is not None:
            self.header.set_start(self._model.start_tile)
        if self._model.stop_tile is not None:
            self.header.set_stop(self._model.stop_tile)
        self.header.blockSignals(False)

    def _add_tile_to_table(self, row: int, column: int) -> None:
        """Add a configured tile to the table.

        :param row: Tile row index
        :param column: Tile column index
        """
        self.tile_table.blockSignals(True)

        table_row = self.tile_table.rowCount()
        self.tile_table.insertRow(table_row)

        tile_positions = self._model.tile_positions
        scan_starts = self._model.scan_starts
        scan_ends = self._model.scan_ends

        kwargs = {
            "row, column": [row, column],
            f"{self.coordinate_plane[0]} [{self.unit}]": tile_positions[row, column, 0],
            f"{self.coordinate_plane[1]} [{self.unit}]": tile_positions[row, column, 1],
            f"{self.coordinate_plane[2]} [{self.unit}]": scan_starts[row, column],
            f"{self.coordinate_plane[2]} max [{self.unit}]": scan_ends[row, column],
        }

        items = {}
        for header_col, header in enumerate(self.table_columns[:-1]):
            item = QTableWidgetItem()
            if header == "row, column":
                item.setText(str([row, column]))
            else:
                value = float(kwargs[header])
                item.setData(Qt.ItemDataRole.EditRole, value)
            items[header] = item
            self.tile_table.setItem(table_row, header_col, item)

        # Determine which cells should be disabled
        disable = list(kwargs.keys())

        # Always disable row, column and position columns
        # Only allow editing scan start/end for first tile (or all if apply_all is False)
        if not self._apply_all or (row, column) == (0, 0):
            disable.remove(f"{self.coordinate_plane[2]} max [{self.unit}]")
            anchor_enabled = self._model.anchor_enabled
            if anchor_enabled[2] or not self._apply_all:
                disable.remove(f"{self.coordinate_plane[2]} [{self.unit}]")

        flags = QTableWidgetItem().flags()
        flags &= ~Qt.ItemFlag.ItemIsEditable
        for var in disable:
            items[var].setFlags(flags)

        # Add visibility checkbox
        tile_visibility = self._model.tile_visibility
        visible = QCheckBox("Visible")
        visible.setChecked(bool(tile_visibility[row, column]))
        visible.toggled.connect(lambda checked: self._toggle_visibility(checked, row, column))
        visible.setEnabled(not (self._apply_all and (row, column) != (0, 0)))
        self.tile_table.setCellWidget(table_row, self.table_columns.index("visibility"), visible)

        self.tile_table.blockSignals(False)

    def _toggle_visibility(self, checked: bool, row: int, column: int) -> None:
        """Handle visibility checkbox toggle.

        :param checked: New checked state
        :param row: Tile row index
        :param column: Tile column index
        """
        self._model.set_tile_visibility(row, column, checked)

        if self._apply_all and [row, column] == [0, 0]:
            # Apply to all tiles
            self._model.apply_to_all_tiles(visible=checked)
            # Update all checkboxes in table
            for r in range(self.tile_table.rowCount()):
                checkbox = self.tile_table.cellWidget(r, self.table_columns.index("visibility"))
                if checkbox:
                    checkbox.blockSignals(True)
                    checkbox.setChecked(checked)
                    checkbox.blockSignals(False)

        self.valueChanged.emit(self._model.get_grid_value())

    def _on_tile_table_changed(self, item: QTableWidgetItem) -> None:
        """Handle table item change.

        :param item: Changed table item
        """
        row, column = [int(x) for x in self.tile_table.item(item.row(), 0).text() if x.isdigit()]
        col_title = self.table_columns[item.column()]

        titles = [
            f"{self.coordinate_plane[2]} [{self.unit}]",
            f"{self.coordinate_plane[2]} max [{self.unit}]",
        ]

        if col_title in titles:
            value = item.data(Qt.ItemDataRole.EditRole)

            if col_title == titles[0]:
                self._model.set_scan_start(row, column, value)
            else:
                self._model.set_scan_end(row, column, value)

            if self._apply_all and [row, column] == [0, 0]:
                # Apply to all tiles
                if col_title == titles[0]:
                    self._model.apply_to_all_tiles(scan_start=value)
                else:
                    self._model.apply_to_all_tiles(scan_end=value)

                # Update all rows in table
                for r in range(self.tile_table.rowCount()):
                    self.tile_table.blockSignals(True)
                    self.tile_table.item(r, item.column()).setData(Qt.ItemDataRole.EditRole, value)
                    self.tile_table.blockSignals(False)

            self.valueChanged.emit(self._model.get_grid_value())

    # Public interface for external access

    @property
    def tile_positions(self) -> np.ndarray:
        """Get tile positions from model."""
        return self._model.tile_positions

    @property
    def tile_visibility(self) -> np.ndarray:
        """Get tile visibility from model."""
        return self._model.tile_visibility

    @property
    def scan_starts(self) -> np.ndarray:
        """Get scan start positions from model."""
        return self._model.scan_starts

    @property
    def scan_ends(self) -> np.ndarray:
        """Get scan end positions from model."""
        return self._model.scan_ends

    @property
    def start(self) -> int | None:
        """Get start tile index from model."""
        return self._model.start_tile

    @property
    def stop(self) -> int | None:
        """Get stop tile index from model."""
        return self._model.stop_tile

    def value(self):
        """Get current grid value from model."""
        return self._model.get_grid_value()
