"""Pydantic models for exaspim.state.json."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .plan import AcqPlan

# Type aliases for constrained metadata fields
type AnatomicalDirectionX = Literal["Anterior_to_posterior", "Posterior_to_anterior"]
type AnatomicalDirectionY = Literal["Inferior_to_superior", "Superior_to_inferior"]
type AnatomicalDirectionZ = Literal["Left_to_right", "Right_to_left"]
type MetadataDateFmt = Literal["Year/Month/Day/Hour/Minute/Second"]
type MetadataDelimiter = Literal["_", "."]


class ExperimentMetadata(BaseModel):
    """Per-experiment metadata stored in session state.

    This data changes between experiments and is saved in state.json,
    not in the instrument config YAML.
    """

    # Subject info
    subject_id: str | None = None
    experimenter_full_name: list[str] | None = None
    notes: str | None = None

    # Chamber settings
    chamber_medium: str = "other"
    chamber_refractive_index: float = 1.33

    # Anatomical directions
    x_anatomical_direction: AnatomicalDirectionX = "Anterior_to_posterior"
    y_anatomical_direction: AnatomicalDirectionY = "Inferior_to_superior"
    z_anatomical_direction: AnatomicalDirectionZ = "Left_to_right"

    # Naming conventions
    date_format: MetadataDateFmt = "Year/Month/Day/Hour/Minute/Second"
    name_delimiter: MetadataDelimiter = "_"

    @property
    def is_configured(self) -> bool:
        """Check if minimum required fields are set."""
        return self.subject_id is not None and self.experimenter_full_name is not None


class ExecutionState(BaseModel):
    """Acquisition progress tracking."""

    started_at: datetime | None = None
    completed_at: datetime | None = None
    current_tile: int | None = None


class SessionState(BaseModel):
    """Root model for session state serialization."""

    version: str = "1.0"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    metadata: ExperimentMetadata = Field(default_factory=ExperimentMetadata)
    plan: AcqPlan = Field(default_factory=AcqPlan)
    execution: ExecutionState = Field(default_factory=ExecutionState)

    def touch(self) -> None:
        self.updated_at = datetime.now()
