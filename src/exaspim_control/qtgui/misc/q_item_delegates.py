from typing import cast

from PyQt6.QtCore import QAbstractItemModel, QModelIndex
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTextEdit,
    QWidget,
)


class QTextItemDelegate(QStyledItemDelegate):
    """QStyledItemDelegate acting like QTextEdit."""

    def createEditor(
        self, parent: QWidget | None, option: QStyleOptionViewItem, index: QModelIndex
    ) -> QTextEdit:
        return QTextEdit(parent)

    def setEditorData(self, editor: QWidget | None, index: QModelIndex) -> None:
        if editor:
            cast(QTextEdit, editor).setText(str(index.data()))

    def setModelData(
        self, editor: QWidget | None, model: QAbstractItemModel | None, index: QModelIndex
    ) -> None:
        if editor and model:
            model.setData(index, cast(QTextEdit, editor).toPlainText())


class QComboItemDelegate(QStyledItemDelegate):
    """QStyledItemDelegate acting like QComboBox."""

    def __init__(self, items: list, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.items = items

    def createEditor(
        self, parent: QWidget | None, option: QStyleOptionViewItem, index: QModelIndex
    ) -> QComboBox:
        return QComboBox(parent)

    def setEditorData(self, editor: QWidget | None, index: QModelIndex) -> None:
        if editor:
            cast(QComboBox, editor).addItems(self.items)

    def setModelData(
        self, editor: QWidget | None, model: QAbstractItemModel | None, index: QModelIndex
    ) -> None:
        if editor and model:
            model.setData(index, cast(QComboBox, editor).currentText())


class QSpinItemDelegate(QStyledItemDelegate):
    """QStyledItemDelegate acting like QSpinBox."""

    def __init__(
        self,
        minimum: float | None = None,
        maximum: float | None = None,
        step: float | int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.minimum = minimum if minimum is not None else -2147483647
        self.maximum = maximum if maximum is not None else 2147483647
        self.step = step if step is not None else 0.01

    def createEditor(
        self, parent: QWidget | None, option: QStyleOptionViewItem, index: QModelIndex
    ) -> QSpinBox | QDoubleSpinBox:
        if isinstance(self.step, int):
            box = QSpinBox(parent)
            box.setMinimum(int(self.minimum))
            box.setMaximum(int(self.maximum))
        else:
            box = QDoubleSpinBox(parent)
            box.setMinimum(float(self.minimum))
            box.setMaximum(float(self.maximum))
        if isinstance(box, QDoubleSpinBox):
            box.setDecimals(5)
            box.setSingleStep(float(self.step))
        else:
            box.setSingleStep(int(self.step))
        return box

    def setEditorData(self, editor: QWidget | None, index: QModelIndex) -> None:
        if editor is None:
            return
        value = int(index.data()) if isinstance(self.step, int) else float(index.data())
        if isinstance(editor, QSpinBox):
            editor.setValue(int(value))
        elif isinstance(editor, QDoubleSpinBox):
            editor.setValue(float(value))

    def setModelData(
        self, editor: QWidget | None, model: QAbstractItemModel | None, index: QModelIndex
    ) -> None:
        if editor is None or model is None:
            return
        if isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            value = int(editor.value()) if isinstance(self.step, int) else float(editor.value())
            model.setData(index, value)
