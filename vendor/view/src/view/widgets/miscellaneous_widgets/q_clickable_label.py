from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QLabel


class QClickableLabel(QLabel):
    """QLabel that emits pyqtSignal when clicked"""

    clicked = pyqtSignal()

    def mousePressEvent(self, ev: QMouseEvent, **kwargs) -> None:
        """
        Overwriting to emit pyqtSignal
        :param ev: mouse click event
        """
        self.clicked.emit()
        super().mousePressEvent(ev, **kwargs)
