"""Unified live viewer for camera frames - embeddable or expandable to napari window."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import napari
import numpy as np
from napari.utils.transforms import Affine
from PyQt6.QtCore import QByteArray, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QTransform
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)
from voxel.preview import PreviewFrame


class LiveViewer(QWidget):
    """Live viewer with embedded preview and optional napari window for full-res."""

    expandToggled = pyqtSignal(bool)
    _frameReceived = pyqtSignal(object)  # Internal signal for thread-safe frame updates
    _previewReceived = pyqtSignal(object)  # Internal signal for pre-processed preview frames

    def __init__(
        self,
        title: str = "Live Viewer",
        camera_rotation_deg: float = 0.0,
        parent: QWidget | None = None,
    ):
        """Initialize LiveViewer.

        :param title: Window title for napari viewer
        :param camera_rotation_deg: Camera rotation in degrees (0, 90, -90, 180, etc.)
            Used to rotate displayed frames to match physical stage orientation.
        :param parent: Parent widget
        """
        super().__init__(parent)
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._title = title
        self._parent = parent
        self._image_rotation_deg = -camera_rotation_deg
        self._is_closing = False
        self._frame_times: list[float] = []

        # Connect frame signals to slots (ensures updates happen on main thread)
        self._frameReceived.connect(self._process_frame)
        self._previewReceived.connect(self._process_preview)

        # Store last histogram for future UI controls
        self._last_histogram: list[int] | None = None

        # Embedded view widgets
        self._image_label = self._create_image_label()
        self._expand_button = self._create_expand_button()
        self._fps_label = self._create_fps_label()

        # Build layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._image_label)

        self.setStyleSheet("background-color: black;")
        self.setMinimumSize(300, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._napari_viewer = self._create_napari_viewer()

    @property
    def is_expanded(self) -> bool:
        return self._napari_viewer.window._qt_window.isVisible()

    def update_frame(self, frame: np.ndarray) -> None:
        """Update napari viewer with raw frame (for full-res viewing).

        Note: The frame is already copied by PreviewGenerator, so no copy is needed here.
        """
        if frame is None or frame.size == 0:
            return
        self._frameReceived.emit(frame)

    def update_preview(self, preview: PreviewFrame) -> None:
        """Update embedded display with pre-processed preview frame."""
        if preview is None:
            return
        self._previewReceived.emit(preview)

    def reset(self) -> None:
        self._frame_times.clear()
        self._fps_label.setText("-- FPS")

    def close(self) -> bool:
        self._is_closing = True
        if self._napari_viewer is not None:
            try:
                self._napari_viewer.close()
            except Exception:
                self.log.exception("Error closing napari viewer")
        return True

    def sizeHint(self) -> QSize:
        return QSize(400, 300)

    def resizeEvent(self, a0) -> None:
        """Position overlay widgets when resized."""
        super().resizeEvent(a0)

        # Position expand button in top-right corner
        margin = 8
        btn_size = self._expand_button.sizeHint()
        self._expand_button.move(
            self.width() - btn_size.width() - margin,
            margin,
        )

        # Position FPS label in bottom-left corner
        fps_size = self._fps_label.sizeHint()
        self._fps_label.move(
            margin,
            self.height() - fps_size.height() - margin,
        )

    def _create_image_label(self) -> QLabel:
        """Create the embedded image display label."""
        label = QLabel(self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("background-color: black; color: #888;")
        label.setText("No Image")
        label.setScaledContents(False)
        return label

    def _create_expand_button(self) -> QPushButton:
        """Create the expand button overlay."""
        button = QPushButton(self)
        button.setCheckable(True)
        button.setFixedSize(28, 28)
        button.setToolTip("Expand to napari viewer")

        # Use standard fullscreen icon
        if (style := QApplication.style()) is not None:
            button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton))

        button.setStyleSheet("""
            QPushButton {
                background-color: rgba(60, 60, 60, 180);
                border: 1px solid rgba(80, 80, 80, 180);
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: rgba(80, 80, 80, 200);
            }
            QPushButton:checked {
                background-color: rgba(0, 120, 212, 200);
                border-color: rgba(0, 140, 232, 200);
            }
        """)
        button.toggled.connect(self._on_expand_toggled)
        return button

    def _create_fps_label(self) -> QLabel:
        """Create the FPS display label overlay."""
        label = QLabel("-- FPS", self)
        label.setStyleSheet("""
            QLabel {
                color: #00ff00;
                background-color: rgba(0, 0, 0, 150);
                padding: 2px 6px;
                border-radius: 3px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumWidth(60)
        label.adjustSize()
        return label

    def _create_napari_viewer(self) -> napari.Viewer:
        """Create napari viewer as child window of main window."""
        self.log.info("Creating napari viewer")

        viewer = napari.Viewer(
            title=self._title,
            ndisplay=2,
            axis_labels=("x", "y"),
            show=False,
        )
        viewer.scale_bar.visible = True
        viewer.scale_bar.unit = "um"
        viewer.scale_bar.position = "bottom_left"

        qt_window = viewer.window._qt_window

        # Set window icon
        icon_path = Path(__file__).parent / "voxel-logo.png"
        if icon_path.exists():
            qt_window.setWindowIcon(QIcon(str(icon_path)))

        # Set parent so napari closes when main window closes
        if self._parent is not None:
            qt_window.setParent(self._parent)
            # Re-apply window flags to keep it as a separate window (not embedded)
            qt_window.setWindowFlags(qt_window.windowFlags() | Qt.WindowType.Window)

        # Custom close event - hide instead of close, uncheck expand button
        original_close = qt_window.closeEvent

        def on_close(event):
            if self._is_closing:
                original_close(event)
                return
            event.ignore()
            qt_window.hide()
            self._expand_button.blockSignals(True)
            self._expand_button.setChecked(False)
            self._expand_button.blockSignals(False)
            self.expandToggled.emit(False)
            self.log.info("Napari viewer hidden")

        qt_window.closeEvent = on_close

        return viewer

    def _process_frame(self, frame: np.ndarray) -> None:
        """Process raw frame for napari viewer."""
        if self.is_expanded and self._napari_viewer is not None:
            try:
                if len(self._napari_viewer.layers) == 0:
                    layer = self._napari_viewer.add_image(frame, name="Camera")
                    if self._image_rotation_deg != 0:
                        layer.affine = _create_center_rotation_affine(self._image_rotation_deg, frame.shape)  # pyright: ignore[reportAttributeAccessIssue]
                layer = self._napari_viewer.layers[0]
                layer.data = frame
            except Exception:
                self.log.exception("Failed to update napari viewer")

    def _process_preview(self, preview: PreviewFrame) -> None:
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

            # Apply rotation if needed (same rotation as napari viewer)
            if self._image_rotation_deg != 0:
                transform = QTransform().rotate(self._image_rotation_deg)
                pixmap = pixmap.transformed(transform, Qt.TransformationMode.FastTransformation)

            scaled = pixmap.scaled(
                self._image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            self._image_label.setPixmap(scaled)

        except Exception:
            self.log.exception("Failed to process preview frame")

    def _on_expand_toggled(self, checked: bool) -> None:
        """Handle expand button toggle."""
        qt_window = self._napari_viewer.window._qt_window
        if checked:
            qt_window.show()
            qt_window.raise_()
            qt_window.activateWindow()
            self.log.info("Napari viewer shown")
        else:
            qt_window.hide()
            self.log.info("Napari viewer hidden")
        self.expandToggled.emit(checked)


def _create_center_rotation_affine(image_rotation_deg, shape: tuple[int, ...]) -> Affine:
    """Create affine transform for rotation around image center."""
    h, w = shape[:2]
    cy, cx = h / 2, w / 2
    theta = np.radians(image_rotation_deg)
    cos_t, sin_t = np.cos(theta), np.sin(theta)

    # Rotation around center: translate to origin, rotate, translate back
    # Combined into single affine matrix (column vector convention)
    # Translation compensates for rotation around origin to make it appear as center rotation
    ty = cy - (cy * cos_t - cx * sin_t)
    tx = cx - (cy * sin_t + cx * cos_t)

    matrix = np.array(
        [
            [cos_t, -sin_t, ty],
            [sin_t, cos_t, tx],
            [0, 0, 1],
        ]
    )
    return Affine(affine_matrix=matrix)
