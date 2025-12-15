"""Widget to visualize and monitor an AcquisitionTask."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from voxel.devices.daq.acq_task import AcquisitionTask
    from voxel.devices.daq.base import TaskStatus


class StatusBadge(QLabel):
    """Small status indicator badge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedWidth(80)
        self.set_status("idle")

    def set_status(self, status: str) -> None:
        """Update the status display."""
        status_lower = status.lower()
        if status_lower == "running":
            self.setText("Running")
            self.setStyleSheet("""
                QLabel {
                    background-color: #2e7d32;
                    color: white;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 2px 8px;
                    border-radius: 3px;
                }
            """)
        elif status_lower == "error":
            self.setText("Error")
            self.setStyleSheet("""
                QLabel {
                    background-color: #c62828;
                    color: white;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 2px 8px;
                    border-radius: 3px;
                }
            """)
        else:  # idle
            self.setText("Idle")
            self.setStyleSheet("""
                QLabel {
                    background-color: #616161;
                    color: white;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 2px 8px;
                    border-radius: 3px;
                }
            """)


class AcquisitionTaskWidget(QWidget):
    """Widget to visualize and monitor an AcquisitionTask.

    Shows:
    - Task name and status
    - Timing parameters (sample rate, duration, rest time, num samples)
    - Waveform visualization
    - Channel/port configuration table
    """

    # Colors for different waveform channels
    WAVEFORM_COLORS = [
        "#4fc3f7",  # light blue
        "#81c784",  # light green
        "#ffb74d",  # orange
        "#f06292",  # pink
        "#ba68c8",  # purple
        "#4dd0e1",  # cyan
        "#aed581",  # lime
        "#ff8a65",  # deep orange
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._task: AcquisitionTask | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # Header: Task name + status
        header = self._create_header()
        layout.addWidget(header)

        # Timing section
        timing_section = self._create_timing_section()
        layout.addWidget(timing_section)

        # Waveform plot
        waveform_section = self._create_waveform_section()
        layout.addWidget(waveform_section, stretch=1)

        # Channels table
        channels_section = self._create_channels_section()
        layout.addWidget(channels_section)

    def _create_header(self) -> QWidget:
        """Create header with task name and status badge."""
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)

        self._task_name_label = QLabel("No Task")
        self._task_name_label.setStyleSheet("""
            QLabel {
                color: #d4d4d4;
                font-size: 14px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self._task_name_label)

        layout.addStretch()

        self._status_badge = StatusBadge()
        layout.addWidget(self._status_badge)

        return header

    def _create_timing_section(self) -> QWidget:
        """Create timing parameters section."""
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

        # Labels
        labels = ["Sample Rate", "Duration", "Rest Time", "Num Samples"]
        for i, label_text in enumerate(labels):
            label = QLabel(label_text)
            label.setStyleSheet("color: #888; font-size: 10px; border: none; background: transparent;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label, 0, i)

        # Values
        self._sample_rate_value = self._create_value_label("--")
        self._duration_value = self._create_value_label("--")
        self._rest_time_value = self._create_value_label("--")
        self._num_samples_value = self._create_value_label("--")

        layout.addWidget(self._sample_rate_value, 1, 0)
        layout.addWidget(self._duration_value, 1, 1)
        layout.addWidget(self._rest_time_value, 1, 2)
        layout.addWidget(self._num_samples_value, 1, 3)

        return section

    def _create_value_label(self, text: str) -> QLabel:
        """Create a styled value label."""
        label = QLabel(text)
        label.setStyleSheet("color: #d4d4d4; font-size: 12px; font-weight: bold; border: none; background: transparent;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    def _create_waveform_section(self) -> QWidget:
        """Create waveform visualization section."""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Section label
        label = QLabel("Waveforms")
        label.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")
        layout.addWidget(label)

        # Plot widget
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground("#1e1e1e")
        self._plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self._plot_widget.setLabel("bottom", "Time", units="ms")
        self._plot_widget.setLabel("left", "Voltage", units="V")
        self._plot_widget.setMinimumHeight(200)
        self._plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Style the axes
        for axis in ["bottom", "left"]:
            self._plot_widget.getAxis(axis).setTextPen("#888")
            self._plot_widget.getAxis(axis).setPen("#404040")

        layout.addWidget(self._plot_widget)

        # Legend
        self._legend_layout = QHBoxLayout()
        self._legend_layout.setContentsMargins(0, 0, 0, 0)
        self._legend_layout.setSpacing(16)
        self._legend_layout.addStretch()
        layout.addLayout(self._legend_layout)

        return section

    def _create_channels_section(self) -> QWidget:
        """Create channels table section."""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Section label
        label = QLabel("Channels")
        label.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")
        layout.addWidget(label)

        # Table
        self._channels_table = QTableWidget()
        self._channels_table.setColumnCount(4)
        self._channels_table.setHorizontalHeaderLabels(["Name", "Port", "Waveform", "Voltage Range"])
        self._channels_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._channels_table.verticalHeader().setVisible(False)
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

        layout.addWidget(self._channels_table)

        return section

    def set_task(self, task: AcquisitionTask) -> None:
        """Bind to an AcquisitionTask and display its configuration.

        :param task: The acquisition task to display
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
        timing = self._task._timing
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
        self._status_badge.set_status("idle")
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
        timing = self._task._timing
        total_time_ms = (float(timing.duration) + float(timing.rest_time)) * 1000
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
        timing = self._task._timing
        num_samples = timing.num_samples

        for name, waveform in self._task._waveforms.items():
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
        label = QLabel(name)
        label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(label)

        # Insert before the stretch
        self._legend_layout.insertWidget(self._legend_layout.count() - 1, item)

    def _clear_legend(self) -> None:
        """Clear all legend items."""
        while self._legend_layout.count() > 1:  # Keep the stretch
            item = self._legend_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _update_channels_table(self) -> None:
        """Update the channels table."""
        self._channels_table.setRowCount(0)

        if self._task is None:
            return

        ports = self._task._ports
        waveforms = self._task._waveforms

        for name, port in ports.items():
            row = self._channels_table.rowCount()
            self._channels_table.insertRow(row)

            self._channels_table.setItem(row, 0, QTableWidgetItem(name))
            self._channels_table.setItem(row, 1, QTableWidgetItem(port))

            # Waveform type
            waveform = waveforms.get(name)
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
        self._status_badge.set_status(status.value)

    def refresh(self) -> None:
        """Refresh the display from the current task."""
        self._update_display()

    def clear(self) -> None:
        """Clear the widget and unbind from task."""
        self._task = None
        self._clear_display()
