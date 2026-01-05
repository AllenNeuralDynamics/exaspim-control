"""Widget to visualize and monitor an AcquisitionTask."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from exaspim_control._qtgui.primitives import HStack, VButton
from exaspim_control._qtgui.primitives.input import VLabel, VStatusBadge

if TYPE_CHECKING:
    from voxel.interfaces.daq import TaskStatus

    from exaspim_control._qtgui.model import InstrumentModel
    from exaspim_control.instrument.frame_task import DAQFrameTask


class FrameTaskPanel(QWidget):
    """Widget to visualize and monitor an AcquisitionTask.

    Autonomous widget that subscribes to InstrumentModel.streamingChanged
    and refreshes its display when streaming starts/stops.

    Shows:
    - Task name and status
    - Timing parameters (sample rate, duration, rest time, num samples)
    - Waveform visualization
    - Channel/port configuration table
    """

    # Colors for different waveform channels
    WAVEFORM_COLORS: ClassVar = [
        "#4fc3f7",  # light blue
        "#81c784",  # light green
        "#ffb74d",  # orange
        "#f06292",  # pink
        "#ba68c8",  # purple
        "#4dd0e1",  # cyan
        "#aed581",  # lime
        "#ff8a65",  # deep orange
    ]

    def __init__(self, model: InstrumentModel, parent: QWidget | None = None):
        super().__init__(parent)
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._model = model
        self._task: DAQFrameTask | None = None

        # === Create all widgets ===

        # Header widgets
        self._task_name_label = VLabel("No Task", variant="title")
        self._refresh_btn = VButton("↻", variant="secondary")
        self._refresh_btn.setFixedSize(24, 24)
        self._refresh_btn.setToolTip("Refresh waveforms from instrument")
        self._status_badge = VStatusBadge()

        # Timing value labels
        self._sample_rate_value = VLabel("--", variant="value")
        self._sample_rate_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._duration_value = VLabel("--", variant="value")
        self._duration_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rest_time_value = VLabel("--", variant="value")
        self._rest_time_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._num_samples_value = VLabel("--", variant="value")
        self._num_samples_value.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Waveform plot
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground("#1e1e1e")
        self._plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self._plot_widget.setLabel("bottom", "Time", units="ms")
        self._plot_widget.setLabel("left", "Voltage", units="V")
        self._plot_widget.setMinimumHeight(200)
        self._plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        for axis in ["bottom", "left"]:
            self._plot_widget.getAxis(axis).setTextPen("#888")
            self._plot_widget.getAxis(axis).setPen("#404040")

        # Legend layout (populated dynamically)
        self._legend_layout = QHBoxLayout()
        self._legend_layout.setContentsMargins(0, 0, 0, 0)
        self._legend_layout.setSpacing(16)
        self._legend_layout.addStretch()

        # Channels table
        self._channels_table = QTableWidget()
        self._channels_table.setColumnCount(4)
        self._channels_table.setHorizontalHeaderLabels(["Name", "Port", "Waveform", "Voltage Range"])
        if header := self._channels_table.horizontalHeader():
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        if v_header := self._channels_table.verticalHeader():
            v_header.setVisible(False)
        self._channels_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._channels_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._channels_table.setMaximumHeight(120)
        self._channels_table.setStyleSheet("""
            QTableWidget {
                background-color: #2d2d30;
                border: 1px solid #404040;
                border-radius: 4px;
                gridline-color: #404040;
            }
            QTableWidget::item {
                color: #d4d4d4;
                padding: 4px;
            }
            QHeaderView::section {
                background-color: #252526;
                color: #888;
                font-size: 10px;
                font-weight: bold;
                border: none;
                border-bottom: 1px solid #404040;
                padding: 4px;
            }
        """)

        # === Build layout and connect signals ===
        self._setup_ui()
        self._connect_signals()

        # Subscribe to streaming state changes
        model.streamingChanged.connect(self._on_streaming_changed)

    def _setup_ui(self) -> None:
        """Compose layout from pre-created widgets."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_timing_section())
        layout.addWidget(self._build_waveform_section(), stretch=1)
        layout.addWidget(self._build_channels_section())

    def _connect_signals(self) -> None:
        """Connect widget signals to handlers."""
        self._refresh_btn.clicked.connect(self._refresh_from_model)

    def _build_header(self) -> QWidget:
        """Build header with task name, refresh button, and status badge."""
        header = HStack(
            self._task_name_label,
            self._refresh_btn,
            self._status_badge,
            spacing=8,
        )
        # Add stretch between name and buttons
        if (header_layout := header.layout()) is not None and isinstance(header_layout, QHBoxLayout):
            header_layout.insertStretch(1)
        return header

    def _build_timing_section(self) -> QWidget:
        """Build timing parameters section."""
        section = QFrame()
        section.setStyleSheet("""
            QFrame {
                background-color: #2d2d30;
                border: 1px solid #404040;
                border-radius: 4px;
            }
        """)

        layout = QGridLayout(section)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setHorizontalSpacing(24)
        layout.setVerticalSpacing(4)

        # Labels row
        labels = ["Sample Rate", "Duration", "Rest Time", "Num Samples"]
        for i, label_text in enumerate(labels):
            label = VLabel(label_text, variant="muted")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label, 0, i)

        # Values row
        layout.addWidget(self._sample_rate_value, 1, 0)
        layout.addWidget(self._duration_value, 1, 1)
        layout.addWidget(self._rest_time_value, 1, 2)
        layout.addWidget(self._num_samples_value, 1, 3)

        return section

    def _build_waveform_section(self) -> QWidget:
        """Build waveform visualization section."""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Section label
        layout.addWidget(VLabel("Waveforms", variant="section"))

        # Plot widget
        layout.addWidget(self._plot_widget)

        # Legend
        layout.addLayout(self._legend_layout)

        return section

    def _build_channels_section(self) -> QWidget:
        """Build channels table section."""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Section label
        layout.addWidget(VLabel("Channels", variant="section"))

        # Table
        layout.addWidget(self._channels_table)

        return section

    def _on_streaming_changed(self, is_streaming: bool) -> None:
        """Handle streaming state changes - refresh or clear display."""
        if is_streaming:
            self._refresh_from_model()
        else:
            self._clear_display()

    def _refresh_from_model(self) -> None:
        """Refresh display from the model's current frame task."""
        self._task = self._model.frame_task
        self._update_display()

    def set_task(self, task: DAQFrameTask) -> None:
        """Bind to an AcquisitionTask and display its configuration.

        :param task: The frame task to display
        """
        self._task = task
        self._update_display()

    def _update_display(self) -> None:
        """Update all display elements from the current task."""
        if self._task is None:
            self._clear_display()
            return

        # Update header
        self._task_name_label.setText(f"Task: {self._task.uid}")

        # Update timing
        timing = self._task.timing
        self._sample_rate_value.setText(f"{float(timing.sample_rate) / 1000:.1f} kHz")
        self._duration_value.setText(f"{float(timing.duration) * 1000:.1f} ms")
        self._rest_time_value.setText(f"{float(timing.rest_time) * 1000:.1f} ms")
        self._num_samples_value.setText(str(timing.num_samples))

        # Update waveforms plot
        self._update_waveforms()

        # Update channels table
        self._update_channels_table()

    def _clear_display(self) -> None:
        """Clear all display elements."""
        self._task_name_label.setText("No Task")
        self._status_badge.setStatus("idle")
        self._sample_rate_value.setText("--")
        self._duration_value.setText("--")
        self._rest_time_value.setText("--")
        self._num_samples_value.setText("--")
        self._plot_widget.clear()
        self._channels_table.setRowCount(0)
        self._clear_legend()

    def _update_waveforms(self) -> None:
        """Update the waveform plot."""
        self._plot_widget.clear()
        self._clear_legend()

        if self._task is None:
            return

        try:
            # Get downsampled waveforms for visualization
            waveforms = self._task.get_written_waveforms(target_points=1000)
        except RuntimeError:
            # Task not set up yet, generate preview from config
            waveforms = self._generate_preview_waveforms()

        if not waveforms:
            return

        # Calculate time axis
        total_time_ms = (float(self._task.timing.duration) + float(self._task.timing.rest_time)) * 1000
        num_points = len(next(iter(waveforms.values())))
        time_axis = [i * total_time_ms / num_points for i in range(num_points)]

        # Plot each waveform
        for i, (name, data) in enumerate(waveforms.items()):
            color = self.WAVEFORM_COLORS[i % len(self.WAVEFORM_COLORS)]
            pen = pg.mkPen(color=color, width=2)
            self._plot_widget.plot(time_axis, data, pen=pen, name=name)
            self._add_legend_item(name, color)

    def _generate_preview_waveforms(self) -> dict[str, list[float]]:
        """Generate preview waveforms when task is not set up."""
        if self._task is None:
            return {}

        waveforms = {}
        timing = self._task.timing
        num_samples = timing.num_samples

        for name, waveform in self._task.waveforms.items():
            waveform_array = waveform.get_array(num_samples)
            waveforms[name] = waveform_array.tolist()

        return waveforms

    def _add_legend_item(self, name: str, color: str) -> None:
        """Add an item to the legend."""
        item = QWidget()
        layout = QHBoxLayout(item)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Color swatch

        swatch = QLabel()
        swatch.setFixedSize(12, 12)
        swatch.setStyleSheet(f"background-color: {color}; border-radius: 2px;")
        layout.addWidget(swatch)

        # Name
        layout.addWidget(VLabel(name, variant="muted"))

        # Insert before the stretch
        self._legend_layout.insertWidget(self._legend_layout.count() - 1, item)

    def _clear_legend(self) -> None:
        """Clear all legend items."""
        while self._legend_layout.count() > 1:  # Keep the stretch
            if (item := self._legend_layout.takeAt(0)) and (widget := item.widget()):
                widget.deleteLater()

    def _update_channels_table(self) -> None:
        """Update the channels table."""
        self._channels_table.setRowCount(0)

        if self._task is None:
            return

        for name, port in self._task.ports.items():
            row = self._channels_table.rowCount()
            self._channels_table.insertRow(row)

            self._channels_table.setItem(row, 0, QTableWidgetItem(name))
            self._channels_table.setItem(row, 1, QTableWidgetItem(port))

            # Waveform type
            waveform = self._task.waveforms.get(name)
            if waveform:
                wf_type = getattr(waveform, "type", "unknown")
                self._channels_table.setItem(row, 2, QTableWidgetItem(wf_type))

                # Voltage range
                voltage = getattr(waveform, "voltage", None)
                if voltage:
                    voltage_str = f"{float(voltage.min):.1f}V - {float(voltage.max):.1f}V"
                    self._channels_table.setItem(row, 3, QTableWidgetItem(voltage_str))
                else:
                    self._channels_table.setItem(row, 3, QTableWidgetItem("--"))
            else:
                self._channels_table.setItem(row, 2, QTableWidgetItem("--"))
                self._channels_table.setItem(row, 3, QTableWidgetItem("--"))

    def update_status(self, status: TaskStatus) -> None:
        """Update the status indicator.

        :param status: Task status (TaskStatus enum)
        """
        self._status_badge.setStatus(status.value)  # type: ignore[arg-type]

    def refresh(self) -> None:
        """Refresh the display from the current task."""
        self._update_display()

    def clear(self) -> None:
        """Clear the widget and unbind from task."""
        self._task = None
        self._clear_display()
