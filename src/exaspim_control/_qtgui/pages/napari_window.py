"""NapariWindow - Standalone napari viewer window for full-resolution frame viewing."""

from __future__ import annotations

import logging

import numpy as np
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget


class NapariWindow(QObject):
    """Standalone napari viewer window with lazy initialization.

    The napari viewer is created on first show() call to avoid
    slow import/initialization at application startup.

    Signals:
        visibilityChanged: Emitted when window visibility changes.
    """

    visibilityChanged = pyqtSignal(bool)

    def __init__(
        self,
        title: str = "Live Viewer",
        image_rotation_deg: float = 0.0,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._title = title
        self._parent_widget = parent
        self._image_rotation_deg = image_rotation_deg
        self._is_closing = False

        # Lazy initialization - viewer created on first show()
        self._viewer = None

    @property
    def qt_window(self):
        """Get the underlying Qt window (None if not initialized)."""
        if self._viewer is None:
            return None
        return self._viewer.window._qt_window  # noqa: SLF001

    @property
    def is_visible(self) -> bool:
        """Check if napari window is currently visible."""
        if self._viewer is None:
            return False
        return self.qt_window.isVisible()

    @property
    def is_initialized(self) -> bool:
        """Check if napari viewer has been created."""
        return self._viewer is not None

    @property
    def viewer(self):
        """Get the napari viewer instance (None if not initialized)."""
        return self._viewer

    def _ensure_initialized(self) -> None:
        """Create napari viewer if not already created (lazy init)."""
        if self._viewer is not None:
            return

        self.log.info("Creating napari viewer (lazy initialization)")

        # Import napari only when needed
        import napari

        self._viewer = napari.Viewer(
            title=self._title,
            ndisplay=2,
            axis_labels=("x", "y"),
            show=False,
        )

        # Configure scale bar
        self._viewer.scale_bar.unit = "um"
        self._viewer.scale_bar.position = "bottom_left"

        # Set parent so napari closes when main window closes
        if self._parent_widget is not None:
            self.qt_window.setParent(self._parent_widget)
            # Re-apply window flags to keep it as a separate window
            self.qt_window.setWindowFlags(
                self.qt_window.windowFlags() | Qt.WindowType.Window
            )

        # Custom close event - hide instead of close
        original_close = self.qt_window.closeEvent

        def on_close(event):
            if self._is_closing:
                original_close(event)
                return
            event.ignore()
            self.hide()

        self.qt_window.closeEvent = on_close

        self.log.info("Napari viewer created")

    def show(self) -> None:
        """Show the napari window (creates viewer on first call)."""
        self._ensure_initialized()
        self._viewer.scale_bar.visible = True
        self.qt_window.show()
        self.qt_window.raise_()
        self.qt_window.activateWindow()
        self.log.info("Napari viewer shown")
        self.visibilityChanged.emit(True)

    def hide(self) -> None:
        """Hide the napari window."""
        if self._viewer is None:
            return
        self._viewer.scale_bar.visible = False
        self.qt_window.hide()
        self.log.info("Napari viewer hidden")
        self.visibilityChanged.emit(False)

    def toggle(self) -> None:
        """Toggle napari window visibility."""
        self.set_visible(not self.is_visible)

    def set_visible(self, visible: bool) -> None:
        """Set napari window visibility."""
        if visible:
            self.show()
        else:
            self.hide()

    def update_frame(self, frame: np.ndarray) -> None:
        """Update the viewer with a new frame.

        Args:
            frame: Image data as numpy array.
        """
        if self._viewer is None or not self.is_visible:
            return
        if frame is None or frame.size == 0:
            return

        try:
            if len(self._viewer.layers) == 0:
                layer = self._viewer.add_image(frame, name="Camera")
                if self._image_rotation_deg != 0:
                    layer.affine = _create_center_rotation_affine(
                        self._image_rotation_deg, frame.shape
                    )
            self._viewer.layers[0].data = frame
        except Exception:
            self.log.exception("Failed to update napari viewer")

    def close(self) -> None:
        """Close the napari viewer."""
        self._is_closing = True
        if self._viewer is not None:
            try:
                self._viewer.close()
            except Exception:
                self.log.exception("Error closing napari viewer")
            self._viewer = None


def _create_center_rotation_affine(image_rotation_deg: float, shape: tuple[int, ...]):
    """Create affine transform for rotation around image center.

    Args:
        image_rotation_deg: Rotation angle in degrees.
        shape: Image shape (height, width, ...).

    Returns:
        napari Affine transform.
    """
    from napari.utils.transforms import Affine

    h, w = shape[:2]
    cy, cx = h / 2, w / 2
    theta = np.radians(image_rotation_deg)
    cos_t, sin_t = np.cos(theta), np.sin(theta)

    # Rotation around center: translate to origin, rotate, translate back
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
