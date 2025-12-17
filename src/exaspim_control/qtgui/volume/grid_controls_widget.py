"""Grid controls widget for volume planning configuration."""

from typing import Literal

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from exaspim_control.qtgui.components.input import (
    VCheckBox,
    VComboBox,
    VDoubleSpinBox,
    VLabel,
    VSpinBox,
)
from exaspim_control.qtgui.misc.q_item_delegates import QSpinItemDelegate
from exaspim_control.qtgui.misc.q_start_stop_table_header import QStartStopTableHeader

from .volume_model import VolumeModel


class GridControls(QWidget):
    """Widget for grid planning controls and tile table.

    Layout: Controls on left (400px fixed) | Tile table on right (flexible)

    Controls section contains:
    - Grid mode rows (Rows/Cols, Area, Bounds) - inline with inputs
    - Overlap, Order, Relative to options
    - Reverse, Dual-sided checkboxes
    - Anchor Grid settings
    - View controls (single row)

    Tile table section contains:
    - Apply all checkbox
    - Table with tile positions, scan ranges, and visibility

    Reads from and writes to a shared VolumeModel instance.
    """

    # Layout constants for alignment
    RADIO_WIDTH = 75  # Width for mode radio buttons (Rows/Cols, Area, Bounds)
    LABEL_WIDTH = 45  # Width for field labels (Rows, Cols, Width, Height, etc.)
    CONTROLS_WIDTH = 400  # Fixed width for controls panel

    viewPlaneChanged = pyqtSignal(str)  # Emits plane like "xy", "xz", "zy"
    showPathChanged = pyqtSignal(bool)
    valueChanged = pyqtSignal(object)  # Emitted when tile values change

    def __init__(
        self,
        model: VolumeModel,
        parent: QWidget | None = None,
    ):
        """Initialize GridControls.

        :param model: VolumeModel instance containing shared state
        :param parent: Parent widget
        """
        super().__init__(parent)

        self._model = model
        self._updating_from_model = False  # Flag to prevent feedback loops

        # Store coordinate plane info from model
        self.coordinate_plane = model.coordinate_plane_clean
        self.polarity = model.polarity
        self.unit = model.unit

        # Apply all setting (for tile table)
        self._apply_all = True

        self._setup_ui()
        self._connect_signals()
        self._sync_from_model()

        # Connect to model signals for tile table
        self._model.tilesChanged.connect(self._on_tiles_changed)

        # Initial table population
        self._refill_table()

    def _setup_ui(self) -> None:
        """Setup the UI with controls on left and tile table on right."""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        # LEFT: Controls (fixed 400px width)
        left_panel = self._create_controls_panel()
        left_panel.setFixedWidth(self.CONTROLS_WIDTH)
        main_layout.addWidget(left_panel, stretch=0)

        # RIGHT: Tile table (flexible width)
        right_panel = self._create_tile_table_panel()
        main_layout.addWidget(right_panel, stretch=1)

    def _create_tile_table_panel(self) -> QWidget:
        """Create the tile table panel (right side)."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Apply all checkbox
        apply_all_layout = QHBoxLayout()
        self.apply_all_box = VCheckBox()
        self.apply_all_box.setText("Apply to all")
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
            header_item = self.tile_table.horizontalHeaderItem(i)
            column_name = header_item.text() if header_item else f"col_{i}"
            delegate = QSpinItemDelegate()
            setattr(self, f"table_column_{column_name}_delegate", delegate)
            self.tile_table.setItemDelegateForColumn(i, delegate)

        self.tile_table.itemChanged.connect(self._on_tile_table_changed)
        layout.addWidget(self.tile_table)

        return panel

    def _create_controls_panel(self) -> QWidget:
        """Create the controls panel (left side)."""
        # Scroll area for controls
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(16)

        # Grid Mode Section (stacked rows)
        layout.addWidget(self._create_mode_section())

        # Options Section
        layout.addWidget(self._create_options_section())

        # Anchor Section
        layout.addWidget(self._create_anchor_section())

        # View Controls Section (single row)
        layout.addWidget(self._create_view_controls_section())

        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _create_mode_section(self) -> QWidget:
        """Create stacked mode rows with inline inputs."""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)

        # Row 1: Rows/Cols mode
        layout.addLayout(self._create_number_row())

        # Row 2: Area mode
        layout.addLayout(self._create_area_row())

        # Row 3-4: Bounds mode (needs 2 rows)
        layout.addLayout(self._create_bounds_row1())
        layout.addLayout(self._create_bounds_row2())

        return section

    def _create_number_row(self) -> QHBoxLayout:
        """Create Rows/Cols mode row with inline inputs."""
        row = QHBoxLayout()
        row.setSpacing(8)

        # Radio button
        self._number_radio = QRadioButton("Rows/Cols")
        self._number_radio.setStyleSheet("QRadioButton { color: #d4d4d4; font-size: 11px; }")
        self._number_radio.setChecked(True)
        self._number_radio.setFixedWidth(self.RADIO_WIDTH)
        self._mode_group.addButton(self._number_radio)
        row.addWidget(self._number_radio)

        # Rows
        rows_label = VLabel("Rows")
        rows_label.setFixedWidth(self.LABEL_WIDTH)
        row.addWidget(rows_label)
        self._rows = VSpinBox()
        self._rows.setRange(1, 1000)
        self._rows.setValue(1)
        self._rows.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(self._rows)

        # Cols
        cols_label = VLabel("Cols")
        cols_label.setFixedWidth(self.LABEL_WIDTH)
        row.addWidget(cols_label)
        self._columns = VSpinBox()
        self._columns.setRange(1, 1000)
        self._columns.setValue(1)
        self._columns.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(self._columns)

        return row

    def _create_area_row(self) -> QHBoxLayout:
        """Create Area mode row with inline inputs."""
        row = QHBoxLayout()
        row.setSpacing(8)

        limits = self._model.limits

        # Radio button
        self._area_radio = QRadioButton("Area")
        self._area_radio.setStyleSheet("QRadioButton { color: #d4d4d4; font-size: 11px; }")
        self._area_radio.setFixedWidth(self.RADIO_WIDTH)
        self._mode_group.addButton(self._area_radio)
        row.addWidget(self._area_radio)

        # Width
        width_label = VLabel("Width")
        width_label.setFixedWidth(self.LABEL_WIDTH)
        row.addWidget(width_label)
        self._area_width = VDoubleSpinBox()
        self._area_width.setRange(0.01, abs(limits[0][1] - limits[0][0]) or 10000)
        self._area_width.setValue(1.0)
        self._area_width.setDecimals(2)
        self._area_width.setSuffix(f" {self.unit}")
        self._area_width.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._area_width.setEnabled(False)
        row.addWidget(self._area_width)

        # Height
        height_label = VLabel("Height")
        height_label.setFixedWidth(self.LABEL_WIDTH)
        row.addWidget(height_label)
        self._area_height = VDoubleSpinBox()
        self._area_height.setRange(0.01, abs(limits[1][1] - limits[1][0]) or 10000)
        self._area_height.setValue(1.0)
        self._area_height.setDecimals(2)
        self._area_height.setSuffix(f" {self.unit}")
        self._area_height.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._area_height.setEnabled(False)
        row.addWidget(self._area_height)

        return row

    def _create_bounds_row1(self) -> QHBoxLayout:
        """Create Bounds mode row 1 (Left/Right)."""
        row = QHBoxLayout()
        row.setSpacing(8)

        limits = self._model.limits

        # Radio button
        self._bounds_radio = QRadioButton("Bounds")
        self._bounds_radio.setStyleSheet("QRadioButton { color: #d4d4d4; font-size: 11px; }")
        self._bounds_radio.setFixedWidth(self.RADIO_WIDTH)
        self._mode_group.addButton(self._bounds_radio)
        row.addWidget(self._bounds_radio)

        # Determine labels based on polarity
        dim_0_low_label = "Left" if self.polarity[0] == 1 else "Right"
        dim_0_high_label = "Right" if self.polarity[0] == 1 else "Left"

        # Left/Right
        left_label = VLabel(dim_0_low_label)
        left_label.setFixedWidth(self.LABEL_WIDTH)
        row.addWidget(left_label)
        self._dim_0_low = VDoubleSpinBox()
        self._dim_0_low.setRange(limits[0][0], limits[0][1])
        self._dim_0_low.setDecimals(3)
        self._dim_0_low.setSuffix(f" {self.unit}")
        self._dim_0_low.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._dim_0_low.setEnabled(False)
        row.addWidget(self._dim_0_low)

        right_label = VLabel(dim_0_high_label)
        right_label.setFixedWidth(self.LABEL_WIDTH)
        row.addWidget(right_label)
        self._dim_0_high = VDoubleSpinBox()
        self._dim_0_high.setRange(limits[0][0], limits[0][1])
        self._dim_0_high.setDecimals(3)
        self._dim_0_high.setSuffix(f" {self.unit}")
        self._dim_0_high.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._dim_0_high.setEnabled(False)
        row.addWidget(self._dim_0_high)

        return row

    def _create_bounds_row2(self) -> QHBoxLayout:
        """Create Bounds mode row 2 (Bottom/Top)."""
        row = QHBoxLayout()
        row.setSpacing(8)

        limits = self._model.limits

        # Spacer to align with other rows (same width as radio button)
        spacer = QWidget()
        spacer.setFixedWidth(self.RADIO_WIDTH)
        row.addWidget(spacer)

        # Determine labels based on polarity
        dim_1_low_label = "Bot." if self.polarity[1] == 1 else "Top"
        dim_1_high_label = "Top" if self.polarity[1] == 1 else "Bot."

        # Bottom/Top
        bot_label = VLabel(dim_1_low_label)
        bot_label.setFixedWidth(self.LABEL_WIDTH)
        row.addWidget(bot_label)
        self._dim_1_low = VDoubleSpinBox()
        self._dim_1_low.setRange(limits[1][0], limits[1][1])
        self._dim_1_low.setDecimals(3)
        self._dim_1_low.setSuffix(f" {self.unit}")
        self._dim_1_low.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._dim_1_low.setEnabled(False)
        row.addWidget(self._dim_1_low)

        top_label = VLabel(dim_1_high_label)
        top_label.setFixedWidth(self.LABEL_WIDTH)
        row.addWidget(top_label)
        self._dim_1_high = VDoubleSpinBox()
        self._dim_1_high.setRange(limits[1][0], limits[1][1])
        self._dim_1_high.setDecimals(3)
        self._dim_1_high.setSuffix(f" {self.unit}")
        self._dim_1_high.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._dim_1_high.setEnabled(False)
        row.addWidget(self._dim_1_high)

        return row

    def _create_options_section(self) -> QWidget:
        """Create options section."""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Row 1: Overlap (full width, stacked)
        overlap_col = QVBoxLayout()
        overlap_col.setSpacing(4)
        overlap_col.addWidget(VLabel("Overlap"))
        self._overlap = VDoubleSpinBox()
        self._overlap.setRange(-100, 100)
        self._overlap.setValue(self._model.overlap)
        self._overlap.setSuffix(" %")
        self._overlap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        overlap_col.addWidget(self._overlap)
        layout.addLayout(overlap_col)

        # Row 2: Order + Relative to (stacked labels)
        combo_row = QHBoxLayout()
        combo_row.setSpacing(12)

        order_col = QVBoxLayout()
        order_col.setSpacing(4)
        order_col.addWidget(VLabel("Order"))
        self._order = VComboBox()
        self._order.addItems([
            "row_wise_snake",
            "column_wise_snake",
            "spiral",
            "row_wise",
            "column_wise",
        ])
        self._order.setCurrentText(self._model.order)
        self._order.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        order_col.addWidget(self._order)
        combo_row.addLayout(order_col)

        rel_col = QVBoxLayout()
        rel_col.setSpacing(4)
        rel_col.addWidget(VLabel("Relative to"))
        self._relative_to = VComboBox()
        item = f"{'top' if self.polarity[1] == 1 else 'bottom'} {'left' if self.polarity[0] == 1 else 'right'}"
        self._relative_to.addItems(["center", item])
        self._relative_to.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        rel_col.addWidget(self._relative_to)
        combo_row.addLayout(rel_col)

        layout.addLayout(combo_row)

        # Row 3: Reverse + Dual-sided
        checkbox_row = QHBoxLayout()
        checkbox_row.setContentsMargins(0, 4, 0, 0)
        checkbox_row.setSpacing(16)

        self._reverse = VCheckBox()
        self._reverse.setText("Reverse")
        checkbox_row.addWidget(self._reverse)

        checkbox_row.addStretch()

        self._dual_sided = VCheckBox()
        self._dual_sided.setText("Dual-sided")
        checkbox_row.addWidget(self._dual_sided)

        layout.addLayout(checkbox_row)

        return section

    def _create_anchor_section(self) -> QWidget:
        """Create the anchor grid section with horizontal layout."""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(VLabel("Anchor Grid"))

        self._anchor_checks = []
        self._anchor_values = []

        limits = self._model.limits
        fov_position = self._model.fov_position

        # Horizontal layout for x, y, z columns
        anchor_row = QHBoxLayout()
        anchor_row.setSpacing(12)

        for i, plane in enumerate(self.coordinate_plane):
            col = QVBoxLayout()
            col.setSpacing(4)

            # Label + checkbox row
            label_row = QHBoxLayout()
            label_row.setSpacing(4)
            label_row.addWidget(VLabel(plane))
            label_row.addStretch()

            check = VCheckBox()
            check.toggled.connect(lambda checked, idx=i: self._on_anchor_toggled(checked, idx))
            self._anchor_checks.append(check)
            label_row.addWidget(check)

            col.addLayout(label_row)

            # Spinbox
            value = VDoubleSpinBox()
            value.setRange(limits[i][0], limits[i][1])
            value.setDecimals(3)
            value.setValue(fov_position[i])
            value.setSuffix(f" {self.unit}")
            value.setEnabled(False)
            value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._anchor_values.append(value)
            col.addWidget(value)

            anchor_row.addLayout(col)

        layout.addLayout(anchor_row)

        return section

    def _create_view_controls_section(self) -> QWidget:
        """Create view controls in a single row."""
        section = QWidget()
        layout = QHBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Show Path checkbox
        self._show_path = VCheckBox()
        self._show_path.setText("Show Path")
        self._show_path.setChecked(True)
        layout.addWidget(self._show_path)

        layout.addSpacing(12)

        # Plane label
        layout.addWidget(VLabel("Plane:"))

        # Plane radio buttons
        self._plane_group = QButtonGroup(self)
        planes = [
            (f"({self.coordinate_plane[0]},{self.coordinate_plane[1]})", "xy"),
            (f"({self.coordinate_plane[0]},{self.coordinate_plane[2]})", "xz"),
            (f"({self.coordinate_plane[2]},{self.coordinate_plane[1]})", "zy"),
        ]

        for label, plane_id in planes:
            radio = QRadioButton(label)
            radio.setStyleSheet("QRadioButton { color: #d4d4d4; font-size: 11px; }")
            radio.setProperty("plane_id", plane_id)
            radio.toggled.connect(lambda checked, r=radio: self._on_plane_changed(r, checked))
            self._plane_group.addButton(radio)
            layout.addWidget(radio)
            if plane_id == "xy":
                radio.setChecked(True)

        layout.addStretch()

        return section

    def _connect_signals(self) -> None:
        """Connect widget signals to model updates."""
        # Mode radio buttons
        self._number_radio.toggled.connect(lambda checked: self._set_mode("number") if checked else None)
        self._area_radio.toggled.connect(lambda checked: self._set_mode("area") if checked else None)
        self._bounds_radio.toggled.connect(lambda checked: self._set_mode("bounds") if checked else None)

        # Number mode
        self._rows.valueChanged.connect(self._on_rows_changed)
        self._columns.valueChanged.connect(self._on_columns_changed)

        # Area mode
        self._area_width.valueChanged.connect(self._on_area_width_changed)
        self._area_height.valueChanged.connect(self._on_area_height_changed)

        # Bounds mode
        self._dim_0_low.valueChanged.connect(self._on_bounds_changed)
        self._dim_0_high.valueChanged.connect(self._on_bounds_changed)
        self._dim_1_low.valueChanged.connect(self._on_bounds_changed)
        self._dim_1_high.valueChanged.connect(self._on_bounds_changed)

        # Options
        self._overlap.valueChanged.connect(self._on_overlap_changed)
        self._order.currentIndexChanged.connect(self._on_order_changed)
        self._reverse.toggled.connect(self._on_reverse_changed)
        self._dual_sided.toggled.connect(self._on_dual_sided_changed)
        self._relative_to.currentIndexChanged.connect(self._on_relative_to_changed)

        # Anchor values
        for i, value in enumerate(self._anchor_values):
            value.valueChanged.connect(lambda v, idx=i: self._on_anchor_value_changed(idx))

        # View controls
        self._show_path.toggled.connect(self.showPathChanged.emit)

        # Connect to model signals for external updates
        self._model.gridChanged.connect(self._on_model_grid_changed)
        self._model.fovPositionChanged.connect(self._on_model_fov_position_changed)
        self._model.limitsChanged.connect(self._on_model_limits_changed)

    def _sync_from_model(self) -> None:
        """Synchronize UI state from model."""
        self._updating_from_model = True
        try:
            # Mode
            mode = self._model.mode
            if mode == "number":
                self._number_radio.setChecked(True)
            elif mode == "area":
                self._area_radio.setChecked(True)
            elif mode == "bounds":
                self._bounds_radio.setChecked(True)

            # Number mode values
            self._rows.setValue(self._model.rows)
            self._columns.setValue(self._model.columns)

            # Area mode values
            self._area_width.setValue(self._model.area_width)
            self._area_height.setValue(self._model.area_height)

            # Bounds mode values
            bounds = self._model.bounds
            self._dim_0_low.setValue(bounds[0][0])
            self._dim_0_high.setValue(bounds[0][1])
            self._dim_1_low.setValue(bounds[1][0])
            self._dim_1_high.setValue(bounds[1][1])

            # Options
            self._overlap.setValue(self._model.overlap)
            self._order.setCurrentText(self._model.order)
            self._reverse.setChecked(self._model.reverse)
            self._dual_sided.setChecked(self._model.dual_sided)
            self._relative_to.setCurrentText(self._model.relative_to)

            # Anchor
            anchor_enabled = self._model.anchor_enabled
            grid_offset = self._model.grid_offset
            for i, (check, value) in enumerate(zip(self._anchor_checks, self._anchor_values)):
                check.setChecked(anchor_enabled[i])
                value.setValue(grid_offset[i])
                value.setEnabled(anchor_enabled[i])
        finally:
            self._updating_from_model = False

    def _set_mode(self, mode: Literal["number", "area", "bounds"]) -> None:
        """Set grid mode and update model."""
        if self._updating_from_model:
            return

        # Enable/disable inputs based on mode
        number_enabled = mode == "number"
        area_enabled = mode == "area"
        bounds_enabled = mode == "bounds"

        self._rows.setEnabled(number_enabled)
        self._columns.setEnabled(number_enabled)
        self._area_width.setEnabled(area_enabled)
        self._area_height.setEnabled(area_enabled)
        self._dim_0_low.setEnabled(bounds_enabled)
        self._dim_0_high.setEnabled(bounds_enabled)
        self._dim_1_low.setEnabled(bounds_enabled)
        self._dim_1_high.setEnabled(bounds_enabled)

        # Update anchor state
        self._update_anchor_state(mode)

        # Update model
        self._model.mode = mode

    def _update_anchor_state(self, mode: str | None = None) -> None:
        """Update anchor controls based on current mode."""
        if mode is None:
            mode = self._model.mode
        for i, (check, value) in enumerate(zip(self._anchor_checks, self._anchor_values)):
            anchor_enabled = mode != "bounds"
            check.setEnabled(anchor_enabled)
            value.setEnabled(anchor_enabled and check.isChecked())

    def _on_anchor_toggled(self, checked: bool, index: int) -> None:
        """Handle anchor checkbox toggle."""
        if self._updating_from_model:
            return

        self._anchor_values[index].setEnabled(checked)
        if not checked:
            # Reset to current FOV position
            fov_pos = self._model.fov_position[index]
            self._anchor_values[index].setValue(fov_pos)

        # Update model anchor_enabled
        anchor_enabled = [c.isChecked() for c in self._anchor_checks]
        self._model.anchor_enabled = anchor_enabled

        # Update model grid_offset
        self._model.grid_offset = [v.value() for v in self._anchor_values]

    def _on_anchor_value_changed(self, index: int) -> None:
        """Handle anchor value spinbox change."""
        if self._updating_from_model:
            return
        self._model.grid_offset = [v.value() for v in self._anchor_values]

    def _on_rows_changed(self, value: int) -> None:
        if not self._updating_from_model:
            self._model.rows = value

    def _on_columns_changed(self, value: int) -> None:
        if not self._updating_from_model:
            self._model.columns = value

    def _on_area_width_changed(self, value: float) -> None:
        if not self._updating_from_model:
            self._model.area_width = value

    def _on_area_height_changed(self, value: float) -> None:
        if not self._updating_from_model:
            self._model.area_height = value

    def _on_bounds_changed(self) -> None:
        if self._updating_from_model:
            return
        self._model.bounds = [
            [self._dim_0_low.value(), self._dim_0_high.value()],
            [self._dim_1_low.value(), self._dim_1_high.value()],
        ]

    def _on_overlap_changed(self, value: float) -> None:
        if not self._updating_from_model:
            self._model.overlap = value

    def _on_order_changed(self) -> None:
        if not self._updating_from_model:
            self._model.order = self._order.currentText()

    def _on_reverse_changed(self, checked: bool) -> None:
        if not self._updating_from_model:
            self._model.reverse = checked

    def _on_dual_sided_changed(self, checked: bool) -> None:
        if not self._updating_from_model:
            self._model.dual_sided = checked

    def _on_relative_to_changed(self) -> None:
        if not self._updating_from_model:
            self._model.relative_to = self._relative_to.currentText()

    def _on_plane_changed(self, radio: QRadioButton, checked: bool) -> None:
        """Handle plane radio button change."""
        if checked:
            plane_id = radio.property("plane_id")
            self.viewPlaneChanged.emit(plane_id)

    def _on_model_grid_changed(self) -> None:
        """Handle grid changed signal from model."""
        self._sync_from_model()
        self._refill_table()

    def _on_model_fov_position_changed(self, position: list) -> None:
        """Handle FOV position change from model."""
        self._updating_from_model = True
        try:
            anchor_enabled = self._model.anchor_enabled
            for i, (check, spinbox) in enumerate(zip(self._anchor_checks, self._anchor_values)):
                if not anchor_enabled[i] and check.isEnabled():
                    spinbox.setValue(position[i])
        finally:
            self._updating_from_model = False

    def _on_model_limits_changed(self, limits: list) -> None:
        """Handle limits change from model."""
        self._updating_from_model = True
        try:
            # Update area width/height ranges
            self._area_width.setRange(0.01, abs(limits[0][1] - limits[0][0]) or 10000)
            self._area_height.setRange(0.01, abs(limits[1][1] - limits[1][0]) or 10000)

            # Update bounds spinboxes
            self._dim_0_low.setRange(limits[0][0], limits[0][1])
            self._dim_0_high.setRange(limits[0][0], limits[0][1])
            self._dim_1_low.setRange(limits[1][0], limits[1][1])
            self._dim_1_high.setRange(limits[1][0], limits[1][1])

            # Update anchor value spinboxes
            for i in range(3):
                self._anchor_values[i].setRange(limits[i][0], limits[i][1])
        finally:
            self._updating_from_model = False

    # Public property accessors (delegate to model)

    @property
    def mode(self) -> Literal["number", "area", "bounds"]:
        return self._model.mode

    @mode.setter
    def mode(self, value: Literal["number", "area", "bounds"]) -> None:
        self._model.mode = value

    @property
    def fov_position(self) -> list[float]:
        return self._model.fov_position

    @fov_position.setter
    def fov_position(self, value: list[float]) -> None:
        self._model.fov_position = value

    @property
    def fov_dimensions(self) -> list[float]:
        return self._model.fov_dimensions

    @fov_dimensions.setter
    def fov_dimensions(self, value: list[float]) -> None:
        self._model.fov_dimensions = value

    @property
    def rows(self) -> int:
        return self._model.rows

    @property
    def columns(self) -> int:
        return self._model.columns

    @property
    def overlap(self) -> float:
        return self._model.overlap

    @property
    def order(self) -> str:
        return self._model.order

    @property
    def reverse(self) -> bool:
        return self._model.reverse

    @property
    def dual_sided(self) -> bool:
        return self._model.dual_sided

    @property
    def relative_to(self) -> str:
        return self._model.relative_to

    @property
    def grid_offset(self) -> list[float]:
        return self._model.grid_offset

    def set_limits(self, limits: list[list[float]]) -> None:
        """Set new stage limits (updates model).

        :param limits: list of 3 [min, max] pairs for each coordinate plane axis
        """
        self._model.limits = limits

    # Tile table methods

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
        table_order: list[list[int]] = []
        for i in range(self.tile_table.rowCount()):
            item = self.tile_table.item(i, 0)
            if item:
                table_order.append([int(x) for x in item.text() if x.isdigit()])
        value_order: list[list[int]] = [
            [t.row, t.col] for t in grid if t.row is not None and t.col is not None
        ]
        order_matches = np.array_equal(table_order, value_order)
        if not order_matches:
            self._refill_table()
            return

        # Check if tile positions match
        table_pos = []
        for j in range(self.tile_table.rowCount()):
            row_data = []
            for i in range(1, 4):
                item = self.tile_table.item(j, i)
                row_data.append(item.data(Qt.ItemDataRole.EditRole) if item else None)
            table_pos.append(row_data)
        value_pos = self._model.tile_positions
        # Flatten value_pos for comparison
        value_pos_list = [
            [value_pos[t.row, t.col, 0], value_pos[t.row, t.col, 1], value_pos[t.row, t.col, 2]]
            for t in grid
            if t.row is not None and t.col is not None
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
            if tile.row is not None and tile.col is not None:
                self._add_tile_to_table(tile.row, tile.col)

        # Restore start/stop indices
        self.header.blockSignals(True)
        start_tile = self._model.start_tile
        stop_tile = self._model.stop_tile
        if start_tile is not None:
            self.header.set_start(start_tile)
        if stop_tile is not None:
            self.header.set_stop(stop_tile)
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
        visible = VCheckBox()
        visible.setText("Visible")
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
                if checkbox is not None and isinstance(checkbox, VCheckBox):
                    checkbox.blockSignals(True)
                    checkbox.setChecked(checked)
                    checkbox.blockSignals(False)

        self.valueChanged.emit(self._model.get_grid_value())

    def _on_tile_table_changed(self, item: QTableWidgetItem) -> None:
        """Handle table item change.

        :param item: Changed table item
        """
        first_col_item = self.tile_table.item(item.row(), 0)
        if first_col_item is None:
            return
        row, column = [int(x) for x in first_col_item.text() if x.isdigit()]
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
                    row_item = self.tile_table.item(r, item.column())
                    if row_item is not None:
                        self.tile_table.blockSignals(True)
                        row_item.setData(Qt.ItemDataRole.EditRole, value)
                        self.tile_table.blockSignals(False)

            self.valueChanged.emit(self._model.get_grid_value())

    # Public interface for tile table access

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
