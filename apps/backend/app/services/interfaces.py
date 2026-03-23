from abc import ABC, abstractmethod
from datetime import date

from app.api.schemas import GameSummary, Recommendation


class GamesProvider(ABC):
    @abstractmethod
    def fetch(self, selected_date: date) -> list[GameSummary]:
        """Return all games for a date."""


class RecommendationsProvider(ABC):
    @abstractmethod
    def fetch_daily(self, selected_date: date) -> list[Recommendation]:
        """Return all recommendations for a date."""

    @abstractmethod
    def fetch_for_game(self, selected_date: date, game_id: str) -> list[Recommendation]:
        """Return recommendations for one game and date."""
