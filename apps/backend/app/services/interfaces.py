from abc import ABC, abstractmethod
from datetime import date

from app.api.schemas import GameSummary, Recommendation
from app.services.odds import NormalizedPlayerOdds


class GamesProvider(ABC):
    @abstractmethod
    def fetch(self, selected_date: date) -> list[GameSummary]:
        """Return all games for a date."""


class ProjectionProvider(ABC):
    @abstractmethod
    def fetch_player_first_goal_projections(self, selected_date: date) -> list[tuple[str, str, str, str, float]]:
        """Return (game_id, player_id, player_name, team_name, model_probability) records for one date."""


class OddsProvider(ABC):
    @abstractmethod
    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        """Return normalized first-goal player odds snapshots for one date."""


class RecommendationsProvider(ABC):
    @abstractmethod
    def fetch_daily(self, selected_date: date) -> list[Recommendation]:
        """Return all recommendations for a date."""

    @abstractmethod
    def fetch_for_game(self, selected_date: date, game_id: str) -> list[Recommendation]:
        """Return recommendations for one game and date."""


class AvailabilityProvider(ABC):
    @abstractmethod
    def projections_available(self, selected_date: date) -> bool:
        """Return whether projections exist for a given date."""

    @abstractmethod
    def odds_available(self, selected_date: date) -> bool:
        """Return whether odds exist for a given date."""
