from abc import ABC, abstractmethod
from datetime import date
from typing import Any


class ScheduleProvider(ABC):
    @abstractmethod
    def fetch(self, selected_date: date) -> list[dict[str, Any]]:
        """Return schedule rows for a date."""


class ProjectionsProvider(ABC):
    @abstractmethod
    def fetch(self, selected_date: date) -> list[dict[str, Any]]:
        """Return player projection rows for a date."""


class OddsProvider(ABC):
    @abstractmethod
    def fetch(self, selected_date: date) -> list[dict[str, Any]]:
        """Return betting odds rows for a date."""


class RecommendationsProvider(ABC):
    @abstractmethod
    def fetch(self, selected_date: date) -> list[dict[str, Any]]:
        """Return recommendation rows for a date."""
