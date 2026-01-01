"""MetadataEditor - Widget for editing experiment metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from exaspim_control.qtgui.primitives import Card, Field, HStack, InfoRow
from exaspim_control.qtgui.primitives.input import VComboBox, VDoubleSpinBox, VLineEdit

if TYPE_CHECKING:
    from exaspim_control.session import Session
    from exaspim_control.session.state import (
        AnatomicalDirectionX,
        AnatomicalDirectionY,
        AnatomicalDirectionZ,
        MetadataDateFmt,
        MetadataDelimiter,
    )


class MetadataEditor(QScrollArea):
    """Editor for experiment metadata.

    Displays:
    - Instrument info (read-only, from config)
    - Experiment metadata (editable, from session state)

    The editable fields write directly to session.state.metadata,
    which is persisted via session autosave.
    """

    metadataChanged = pyqtSignal()

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._metadata = session.state.metadata
        self._instrument = session.instrument.cfg.info

        # === Create all widgets ===

        # Subject fields
        self._subject_id = VLineEdit(text=self._metadata.subject_id or "", placeholder="Enter subject ID...")
        self._experimenters = VLineEdit(
            text=", ".join(self._metadata.experimenter_full_name) if self._metadata.experimenter_full_name else "",
            placeholder="Enter names, comma-separated...",
        )
        self._notes = VLineEdit(
            text=self._metadata.notes or "",
            placeholder="Optional notes...",
        )

        # Chamber fields
        self._chamber_medium = VLineEdit(text=self._metadata.chamber_medium)
        self._refractive_index = VDoubleSpinBox(
            value=self._metadata.chamber_refractive_index,
            min=1.0,
            max=2.0,
            decimals=3,
            step=0.01,
        )

        # Anatomical direction fields
        self._x_direction = VComboBox(
            items=["Anterior_to_posterior", "Posterior_to_anterior"], value=self._metadata.x_anatomical_direction
        )
        self._y_direction = VComboBox(
            items=["Inferior_to_superior", "Superior_to_inferior"], value=self._metadata.y_anatomical_direction
        )
        self._z_direction = VComboBox(
            items=["Left_to_right", "Right_to_left"], value=self._metadata.z_anatomical_direction
        )

        # Naming fields
        self._date_format = VComboBox(items=["Year/Month/Day/Hour/Minute/Second"], value=self._metadata.date_format)
        self._delimiter = VComboBox(items=["_", "."], value=self._metadata.name_delimiter)

        # === Build layout and connect signals ===
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Compose layout from pre-created widgets."""
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        layout.addWidget(self._build_instrument_card())
        layout.addWidget(self._build_subject_card())
        layout.addWidget(self._build_chamber_card())
        layout.addWidget(self._build_directions_card())
        layout.addWidget(self._build_naming_card())
        layout.addStretch()

        self.setWidget(container)

    def _connect_signals(self) -> None:
        """Connect widget signals to handlers."""
        # Subject
        self._subject_id.textChanged.connect(self._on_subject_id_changed)
        self._experimenters.textChanged.connect(self._on_experimenters_changed)
        self._notes.textChanged.connect(self._on_notes_changed)

        # Chamber
        self._chamber_medium.textChanged.connect(self._on_chamber_medium_changed)
        self._refractive_index.valueChanged.connect(self._on_refractive_index_changed)

        # Directions
        self._x_direction.currentTextChanged.connect(self._on_x_direction_changed)
        self._y_direction.currentTextChanged.connect(self._on_y_direction_changed)
        self._z_direction.currentTextChanged.connect(self._on_z_direction_changed)

        # Naming
        self._date_format.currentTextChanged.connect(self._on_date_format_changed)
        self._delimiter.currentTextChanged.connect(self._on_delimiter_changed)

    def _build_instrument_card(self) -> Card:
        """Build read-only instrument info card using InfoRow."""
        return Card(
            "Instrument",
            InfoRow("UID:", self._instrument.instrument_uid),
            HStack(
                InfoRow("Type:", self._instrument.instrument_type, stretch=False),
                InfoRow("Version:", str(self._instrument.instrument_version)),
                spacing=16,
            ),
        )

    def _build_subject_card(self) -> Card:
        """Build subject info card with editable fields."""
        return Card(
            "Subject",
            Field("Subject ID", self._subject_id),
            Field("Experimenter(s)", self._experimenters),
            Field("Notes", self._notes),
        )

    def _build_chamber_card(self) -> Card:
        """Build chamber settings card."""
        return Card(
            "Chamber",
            Field("Medium", self._chamber_medium),
            Field("Refractive Index", self._refractive_index),
            flow="horizontal",
            spacing=12,
        )

    def _build_directions_card(self) -> Card:
        """Build anatomical directions card."""
        return Card(
            "Anatomical Directions",
            Field("X Direction", self._x_direction),
            Field("Y Direction", self._y_direction),
            Field("Z Direction", self._z_direction),
            flow="horizontal",
            spacing=12,
        )

    def _build_naming_card(self) -> Card:
        """Build naming conventions card."""
        return Card(
            "Naming",
            Field("Date Format", self._date_format),
            Field("Delimiter", self._delimiter),
            flow="horizontal",
            spacing=12,
        )

    # === Event Handlers ===

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

    def _on_notes_changed(self, text: str) -> None:
        self._metadata.notes = text if text else None
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
        self._metadata.name_delimiter = text
        self.metadataChanged.emit()

    # === Properties ===

    @property
    def is_configured(self) -> bool:
        """Check if experiment is properly configured."""
        return self._metadata.is_configured
