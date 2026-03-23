from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(slots=True)
class Prediction:
    match_id: str
    selected_date: date
    win_probability: float


@dataclass(slots=True)
class ModelArtifact:
    name: str
    version: str


class FeaturePipeline(Protocol):
    def run(self, selected_date: date) -> list[Prediction]:
        """Generate predictions for a selected date."""
