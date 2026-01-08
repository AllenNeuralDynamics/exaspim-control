"""LiveViewer - Lightweight embedded preview widget for camera frames."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from PyQt6.QtCore import QByteArray, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QTransform
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from exaspim_control._qtgui.primitives import Colors, Label

if TYPE_CHECKING:
    from voxel.preview import PreviewFrame


class LiveViewer(QWidget):
    """Lightweight embedded preview widget for camera frames.

    Displays downscaled preview frames in the embedded view.
    Full-resolution frames can be routed to an external napari window
    via the frameReceived signal.

    Signals:
        frameReceived: Emitted with raw numpy frame for external viewers.
        previewUpdated: Emitted after preview frame is displayed.
    """

    frameReceived = pyqtSignal(object)  # numpy array for napari
    previewUpdated = pyqtSignal()

    # Internal signal for thread-safe preview updates
    _previewReceived = pyqtSignal(object)

    def __init__(
        self,
        camera_rotation_deg: float = 0.0,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._image_rotation_deg = -camera_rotation_deg
        self._frame_times: list[float] = []

        # Connect preview signal to slot (ensures updates happen on main thread)
        self._previewReceived.connect(self._process_preview)

        # Store last histogram for future UI controls
        self._last_histogram: list[int] | None = None

        # Embedded view widgets
        self._image_label = self._create_image_label()
        self._fps_label = self._create_fps_label()

        # Build layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._image_label)

        self.setStyleSheet(f"background-color: {Colors.BG_DARK};")
        self.setMinimumSize(300, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def update_frame(self, frame) -> None:
        """Emit raw frame for external viewers (e.g., napari).

        Args:
            frame: numpy array with raw camera data.
        """
        if frame is None or frame.size == 0:
            return
        self.frameReceived.emit(frame)

    def update_preview(self, preview: PreviewFrame) -> None:
        """Update embedded display with pre-processed preview frame.

        Args:
            preview: PreviewFrame with JPEG data and metadata.
        """
        if preview is not None:
            self._previewReceived.emit(preview)

    def reset(self) -> None:
        """Reset FPS counter and display."""
        self._frame_times.clear()
        self._fps_label.setText("-- FPS")
        self._image_label.clear()
        self._image_label.setText("No Image")

    def close(self) -> bool:
        """Clean up resources."""
        return True

    def sizeHint(self) -> QSize:
        return QSize(400, 300)

    def resizeEvent(self, a0) -> None:
        """Position overlay widgets when resized."""
        super().resizeEvent(a0)

        # Position FPS label in bottom-left corner
        margin = 8
        fps_size = self._fps_label.sizeHint()
        self._fps_label.move(
            margin,
            self.height() - fps_size.height() - margin,
        )

    def _create_image_label(self) -> QLabel:
        """Create the embedded image display label."""
        label = QLabel(self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"background-color: {Colors.BG_DARK}; color: {Colors.TEXT_MUTED};")
        label.setText("No Image")
        label.setScaledContents(False)
        return label

    def _create_fps_label(self) -> Label:
        """Create the FPS display label overlay."""
        label = Label("-- FPS", variant="overlay", parent=self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumWidth(60)
        label.adjustSize()
        return label

    def _process_preview(self, preview: PreviewFrame) -> None:
        """Process and display preview frame (runs on main thread)."""
        try:
            now = time.time()
            self._frame_times.append(now)
            self._frame_times = self._frame_times[-10:]

            if len(self._frame_times) >= 2:
                elapsed = self._frame_times[-1] - self._frame_times[0]
                if elapsed > 0:
                    fps = (len(self._frame_times) - 1) / elapsed
                    self._fps_label.setText(f"{fps:.1f} FPS")

            if preview.info.histogram is not None:
                self._last_histogram = preview.info.histogram

            pixmap = QPixmap()
            if not pixmap.loadFromData(QByteArray(preview.data)):
                self.log.warning("Failed to decode preview image data")
                return

            # Apply rotation if needed
            if self._image_rotation_deg != 0:
                transform = QTransform().rotate(self._image_rotation_deg)
                pixmap = pixmap.transformed(transform, Qt.TransformationMode.FastTransformation)

            scaled = pixmap.scaled(
                self._image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            self._image_label.setPixmap(scaled)
            self.previewUpdated.emit()

        except Exception:
            self.log.exception("Failed to process preview frame")

    @property
    def last_histogram(self) -> list[int] | None:
        """Get the histogram from the last processed frame."""
        return self._last_histogram
