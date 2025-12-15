from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QSlider


class QScrollableFloatSlider(QSlider):
    """QSlider that emits pyqtSignal on mouse wheel scroll and allows float values."""

    sliderMoved = pyqtSignal(float)  # redefine slider move to emit float

    def __init__(self, decimals: int = 0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.divisor = 10**decimals

    def value(self) -> float:
        return float(super().value()) / self.divisor

    def setMinimum(self, value: float) -> None:
        super().setMinimum(int(value * self.divisor))

    def setMaximum(self, value: float) -> None:
        super().setMaximum(int(value * self.divisor))

    def maximum(self) -> float:
        return super().maximum() / self.divisor

    def minimum(self) -> float:
        return super().minimum() / self.divisor

    def setSingleStep(self, value: float) -> None:
        super().setSingleStep(int(value * self.divisor))

    def singleStep(self) -> float:
        return float(super().singleStep()) / self.divisor

    def setValue(self, value: float) -> None:
        super().setValue(int(value * self.divisor))

    def wheelEvent(self, event) -> None:
        super().wheelEvent(event)
        value = self.value()
        self.sliderMoved.emit(value)
        self.sliderReleased.emit()

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if event.buttons() == Qt.MouseButton.LeftButton:
            value = self.value()
            self.sliderMoved.emit(value)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        value = self.value()
        self.sliderMoved.emit(value)
