"""Experiment tab for metadata and experiment configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from exaspim_control.config import (
    AnatomicalDirectionX,
    AnatomicalDirectionY,
    AnatomicalDirectionZ,
    MetadataDateFmt,
    MetadataDelimiter,
)
from exaspim_control.qtgui.components import Card
from exaspim_control.qtgui.components.input import VComboBox, VDoubleSpinBox, VLabel

if TYPE_CHECKING:
    from exaspim_control.config import Metadata


class ExperimentTab(QScrollArea):
    """Experiment tab with metadata fields for experiment configuration.

    Fields:
    - Instrument info (read-only): uid, type, version
    - Subject ID
    - Experimenter names
    - Chamber medium and refractive index
    - Anatomical directions (x, y, z)
    - Date format and name delimiter
    """

    metadataChanged = pyqtSignal()

    def __init__(self, metadata: Metadata, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._metadata = metadata

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # Instrument Info Card (read-only)
        info_card = Card("Instrument")
        info_container = QWidget()
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(8)

        # UID row
        uid_row = QHBoxLayout()
        uid_row.addWidget(VLabel("UID:"))
        self._uid_label = VLabel(metadata.instrument_uid)
        self._uid_label.setStyleSheet("color: #888; font-size: 11px;")
        uid_row.addWidget(self._uid_label)
        uid_row.addStretch()
        info_layout.addLayout(uid_row)

        # Type and Version row
        type_row = QHBoxLayout()
        type_row.addWidget(VLabel("Type:"))
        self._type_label = VLabel(metadata.instrument_type)
        self._type_label.setStyleSheet("color: #888; font-size: 11px;")
        type_row.addWidget(self._type_label)
        type_row.addSpacing(16)
        type_row.addWidget(VLabel("Version:"))
        self._version_label = VLabel(str(metadata.instrument_version))
        self._version_label.setStyleSheet("color: #888; font-size: 11px;")
        type_row.addWidget(self._version_label)
        type_row.addStretch()
        info_layout.addLayout(type_row)

        info_card.add_widget(info_container)
        layout.addWidget(info_card)

        # Subject Card
        subject_card = Card("Subject")
        subject_container = QWidget()
        subject_layout = QVBoxLayout(subject_container)
        subject_layout.setContentsMargins(0, 0, 0, 0)
        subject_layout.setSpacing(8)

        # Subject ID
        subject_layout.addWidget(VLabel("Subject ID"))
        self._subject_id = QLineEdit()
        self._subject_id.setPlaceholderText("Enter subject ID...")
        self._subject_id.setText(metadata.subject_id or "")
        self._subject_id.setStyleSheet(self._line_edit_style())
        self._subject_id.textChanged.connect(self._on_subject_id_changed)
        subject_layout.addWidget(self._subject_id)

        # Experimenter names
        subject_layout.addWidget(VLabel("Experimenter(s)"))
        self._experimenters = QLineEdit()
        self._experimenters.setPlaceholderText("Enter names, comma-separated...")
        if metadata.experimenter_full_name:
            self._experimenters.setText(", ".join(metadata.experimenter_full_name))
        self._experimenters.setStyleSheet(self._line_edit_style())
        self._experimenters.textChanged.connect(self._on_experimenters_changed)
        subject_layout.addWidget(self._experimenters)

        subject_card.add_widget(subject_container)
        layout.addWidget(subject_card)

        # Chamber Card
        chamber_card = Card("Chamber")
        chamber_container = QWidget()
        chamber_layout = QVBoxLayout(chamber_container)
        chamber_layout.setContentsMargins(0, 0, 0, 0)
        chamber_layout.setSpacing(8)

        # Medium and refractive index row
        chamber_row = QHBoxLayout()
        chamber_row.setSpacing(12)

        medium_col = QVBoxLayout()
        medium_col.setSpacing(4)
        medium_col.addWidget(VLabel("Medium"))
        self._chamber_medium = QLineEdit()
        self._chamber_medium.setText(metadata.chamber_medium)
        self._chamber_medium.setStyleSheet(self._line_edit_style())
        self._chamber_medium.textChanged.connect(self._on_chamber_medium_changed)
        medium_col.addWidget(self._chamber_medium)
        chamber_row.addLayout(medium_col)

        ri_col = QVBoxLayout()
        ri_col.setSpacing(4)
        ri_col.addWidget(VLabel("Refractive Index"))
        self._refractive_index = VDoubleSpinBox()
        self._refractive_index.setRange(1.0, 2.0)
        self._refractive_index.setDecimals(3)
        self._refractive_index.setSingleStep(0.01)
        self._refractive_index.setValue(metadata.chamber_refractive_index)
        self._refractive_index.valueChanged.connect(self._on_refractive_index_changed)
        ri_col.addWidget(self._refractive_index)
        chamber_row.addLayout(ri_col)

        chamber_layout.addLayout(chamber_row)
        chamber_card.add_widget(chamber_container)
        layout.addWidget(chamber_card)

        # Anatomical Directions Card
        directions_card = Card("Anatomical Directions")
        directions_container = QWidget()
        directions_layout = QVBoxLayout(directions_container)
        directions_layout.setContentsMargins(0, 0, 0, 0)
        directions_layout.setSpacing(8)

        directions_row = QHBoxLayout()
        directions_row.setSpacing(12)

        # X direction
        x_col = QVBoxLayout()
        x_col.setSpacing(4)
        x_col.addWidget(VLabel("X Direction"))
        self._x_direction = VComboBox()
        self._x_direction.addItems(["Anterior_to_posterior", "Posterior_to_anterior"])
        self._x_direction.setCurrentText(metadata.x_anatomical_direction)
        self._x_direction.currentTextChanged.connect(self._on_x_direction_changed)
        x_col.addWidget(self._x_direction)
        directions_row.addLayout(x_col)

        # Y direction
        y_col = QVBoxLayout()
        y_col.setSpacing(4)
        y_col.addWidget(VLabel("Y Direction"))
        self._y_direction = VComboBox()
        self._y_direction.addItems(["Inferior_to_superior", "Superior_to_inferior"])
        self._y_direction.setCurrentText(metadata.y_anatomical_direction)
        self._y_direction.currentTextChanged.connect(self._on_y_direction_changed)
        y_col.addWidget(self._y_direction)
        directions_row.addLayout(y_col)

        # Z direction
        z_col = QVBoxLayout()
        z_col.setSpacing(4)
        z_col.addWidget(VLabel("Z Direction"))
        self._z_direction = VComboBox()
        self._z_direction.addItems(["Left_to_right", "Right_to_left"])
        self._z_direction.setCurrentText(metadata.z_anatomical_direction)
        self._z_direction.currentTextChanged.connect(self._on_z_direction_changed)
        z_col.addWidget(self._z_direction)
        directions_row.addLayout(z_col)

        directions_layout.addLayout(directions_row)
        directions_card.add_widget(directions_container)
        layout.addWidget(directions_card)

        # Naming Card
        naming_card = Card("Naming")
        naming_container = QWidget()
        naming_layout = QHBoxLayout(naming_container)
        naming_layout.setContentsMargins(0, 0, 0, 0)
        naming_layout.setSpacing(12)

        # Date format
        date_col = QVBoxLayout()
        date_col.setSpacing(4)
        date_col.addWidget(VLabel("Date Format"))
        self._date_format = VComboBox()
        self._date_format.addItems(["Year/Month/Day/Hour/Minute/Second"])
        self._date_format.setCurrentText(metadata.date_format)
        self._date_format.currentTextChanged.connect(self._on_date_format_changed)
        date_col.addWidget(self._date_format)
        naming_layout.addLayout(date_col)

        # Name delimiter
        delim_col = QVBoxLayout()
        delim_col.setSpacing(4)
        delim_col.addWidget(VLabel("Delimiter"))
        self._delimiter = VComboBox()
        self._delimiter.addItems(["_", "."])
        self._delimiter.setCurrentText(metadata.name_delimitor)
        self._delimiter.currentTextChanged.connect(self._on_delimiter_changed)
        delim_col.addWidget(self._delimiter)
        naming_layout.addLayout(delim_col)

        naming_card.add_widget(naming_container)
        layout.addWidget(naming_card)

        layout.addStretch()
        self.setWidget(container)

    def _line_edit_style(self) -> str:
        return """
            QLineEdit {
                background-color: #2d2d30;
                color: #d4d4d4;
                border: 1px solid #505050;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QLineEdit:focus {
                border-color: #0078d4;
            }
            QLineEdit::placeholder {
                color: #6d6d6d;
            }
        """

    def _on_subject_id_changed(self, text: str) -> None:
        self._metadata.subject_id = text if text else None
        self.metadataChanged.emit()

    def _on_experimenters_changed(self, text: str) -> None:
        if text:
            names = [n.strip() for n in text.split(",") if n.strip()]
            self._metadata.experimenter_full_name = names if names else None
        else:
            self._metadata.experimenter_full_name = None
        self.metadataChanged.emit()

    def _on_chamber_medium_changed(self, text: str) -> None:
        self._metadata.chamber_medium = text
        self.metadataChanged.emit()

    def _on_refractive_index_changed(self, value: float) -> None:
        self._metadata.chamber_refractive_index = value
        self.metadataChanged.emit()

    def _on_x_direction_changed(self, text: AnatomicalDirectionX) -> None:
        self._metadata.x_anatomical_direction = text
        self.metadataChanged.emit()

    def _on_y_direction_changed(self, text: AnatomicalDirectionY) -> None:
        self._metadata.y_anatomical_direction = text
        self.metadataChanged.emit()

    def _on_z_direction_changed(self, text: AnatomicalDirectionZ) -> None:
        self._metadata.z_anatomical_direction = text
        self.metadataChanged.emit()

    def _on_date_format_changed(self, text: MetadataDateFmt) -> None:
        self._metadata.date_format = text
        self.metadataChanged.emit()

    def _on_delimiter_changed(self, text: MetadataDelimiter) -> None:
        self._metadata.name_delimitor = text
        self.metadataChanged.emit()

    @property
    def metadata(self) -> Metadata:
        """Get the metadata object."""
        return self._metadata

    @property
    def is_configured(self) -> bool:
        """Check if experiment is properly configured."""
        return self._metadata.is_experiment_configured
