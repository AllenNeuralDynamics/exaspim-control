from typing import cast

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QMouseEvent
from PyQt6.QtWidgets import QHeaderView, QMenu, QStyle, QTableWidget, QTableWidgetItem


class QStartStopTableHeader(QHeaderView):
    """QTableWidgetItem to be used to select certain tiles to start at"""

    sectionRightClicked = pyqtSignal(QMouseEvent)
    startChanged = pyqtSignal(int)
    stopChanged = pyqtSignal(int)

    def __init__(self, parent):
        super().__init__(Qt.Orientation.Vertical, parent)

        self.start = None
        self.stop = None
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sectionRightClicked.connect(self.menu_popup)

    def mousePressEvent(self, e: QMouseEvent | None) -> None:
        """Detect click event and set correct setting."""
        super().mousePressEvent(e)
        if e is not None and e.button() == Qt.MouseButton.RightButton:
            self.sectionRightClicked.emit(e)

    def menu_popup(self, event: QMouseEvent):
        """
        Function to set tile start or stop
        :param event: mousePressEvent of click
        :return:
        """

        index = self.logicalIndexAt(event.pos())

        start_act = QAction("Set Start", self)
        start_act.triggered.connect(lambda trigger: self.set_start(index))

        stop_act = QAction("Set Stop", self)
        stop_act.triggered.connect(lambda trigger: self.set_stop(index))

        clear_act = QAction("Clear", self)
        clear_act.triggered.connect(lambda trigger: self.clear(index))

        menu = QMenu(self)
        if self.stop is None or (self.stop is not None and self.stop > index):
            menu.addAction(start_act)
        if self.start is None or (self.start is not None and self.start < index):
            menu.addAction(stop_act)
        if index in [self.start, self.stop]:
            menu.addAction(clear_act)
        menu.popup(self.mapToGlobal(event.pos()))

    def _table(self) -> QTableWidget:
        """Get parent table widget."""
        return cast(QTableWidget, self.parent())

    def set_start(self, index: int) -> None:
        """Set start tile."""
        if self.start is not None:
            self.clear(self.start)

        if style := self.style():
            icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogYesButton)
            item = QTableWidgetItem()
            item.setIcon(icon)
            self._table().setVerticalHeaderItem(index, item)

        self.start = index
        self.startChanged.emit(index)

    def set_stop(self, index: int) -> None:
        """Set stop tile."""
        if self.stop is not None:
            self.clear(self.stop)

        if style := self.style():
            icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogNoButton)
            item = QTableWidgetItem()
            item.setIcon(icon)
            self._table().setVerticalHeaderItem(index, item)

        self.stop = index
        self.stopChanged.emit(index)

    def clear(self, index: int) -> None:
        """Clear index of start or stop."""
        if index == self.stop:
            self.stop = None
        elif index == self.start:
            self.start = None

        item = QTableWidgetItem()
        item.setText(str(index + 1))
        self._table().setVerticalHeaderItem(index, item)
