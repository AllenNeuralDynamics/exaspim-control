from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QSlider


class QScrollableFloatSlider(QSlider):
    """QSlider that emits pyqtSignal on mouse wheel scroll and allows float values.

    Note: This class intentionally changes return types from int to float for
    value(), maximum(), minimum(), singleStep() to support float values.
    """

    sliderMoved = pyqtSignal(float)  # redefine slider move to emit float

    def __init__(self, decimals: int = 0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.divisor = 10**decimals

    def value(self) -> float:  # pyright: ignore[reportIncompatibleMethodOverride]
        return float(super().value()) / self.divisor

    def setMinimum(self, a0: float) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        super().setMinimum(int(a0 * self.divisor))

    def setMaximum(self, a0: float) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        super().setMaximum(int(a0 * self.divisor))

    def maximum(self) -> float:  # pyright: ignore[reportIncompatibleMethodOverride]
        return super().maximum() / self.divisor

    def minimum(self) -> float:  # pyright: ignore[reportIncompatibleMethodOverride]
        return super().minimum() / self.divisor

    def setSingleStep(self, a0: float) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        super().setSingleStep(int(a0 * self.divisor))

    def singleStep(self) -> float:  # pyright: ignore[reportIncompatibleMethodOverride]
        return float(super().singleStep()) / self.divisor

    def setValue(self, a0: float) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        super().setValue(int(a0 * self.divisor))

    def wheelEvent(self, e) -> None:
        super().wheelEvent(e)
        val = self.value()
        self.sliderMoved.emit(val)
        self.sliderReleased.emit()

    def mouseMoveEvent(self, ev) -> None:
        super().mouseMoveEvent(ev)
        if ev is not None and ev.buttons() == Qt.MouseButton.LeftButton:
            val = self.value()
            self.sliderMoved.emit(val)

    def mousePressEvent(self, ev) -> None:
        super().mousePressEvent(ev)
        val = self.value()
        self.sliderMoved.emit(val)
