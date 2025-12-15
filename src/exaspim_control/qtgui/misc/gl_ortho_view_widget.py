"""Orthographic OpenGL view widget."""

import numpy as np
from PyQt6.QtGui import QMatrix4x4
from pyqtgraph.opengl import GLViewWidget


class GLOrthoViewWidget(GLViewWidget):
    """GLViewWidget subclass that uses orthographic projection.

    This enables true orthographic (parallel) projection instead of
    the default perspective projection.
    """

    def projectionMatrix(self, region=None, viewport=None) -> QMatrix4x4:
        """Return orthographic projection matrix.

        :param region: region to create projection matrix for
        :param viewport: viewport parameter (ignored, kept for compatibility)
        :return: QMatrix4x4 projection matrix
        """
        projection = "ortho"
        if region is None:
            dpr = self.devicePixelRatio()
            region = (0, 0, self.width() * dpr, self.height() * dpr)

        x0, y0, w, h = self.getViewport()
        dist = self.opts["distance"]
        fov = self.opts["fov"]
        nearClip = dist * 0.001
        farClip = dist * 1000.0

        r = nearClip * np.tan(fov * 0.5 * np.pi / 180.0)
        t = r * h / w

        left = r * ((region[0] - x0) * (2.0 / w) - 1)
        right = r * ((region[0] + region[2] - x0) * (2.0 / w) - 1)
        bottom = t * ((region[1] - y0) * (2.0 / h) - 1)
        top = t * ((region[1] + region[3] - y0) * (2.0 / h) - 1)

        tr = QMatrix4x4()
        if projection == "ortho":
            tr.ortho(left, right, bottom, top, nearClip, farClip)
        elif projection == "frustum":
            tr.frustum(left, right, bottom, top, nearClip, farClip)
        return tr
