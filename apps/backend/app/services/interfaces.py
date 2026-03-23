from abc import ABC, abstractmethod
from datetime import date

from app.api.schemas import GameSummary, Recommendation
from app.services.odds import NormalizedPlayerOdds


class ScheduleProvider(ABC):
    @abstractmethod
    def fetch(self, selected_date: date) -> list[GameSummary]:
        """Return the published game schedule for a date."""


class ProjectionProvider(ABC):
    @abstractmethod
    def fetch_player_first_goal_projections(self, selected_date: date) -> list[tuple[str, str, str, str, float]]:
        """Return (game_id, player_id, player_name, team_name, model_probability) rows for a date."""


class OddsProvider(ABC):
    @abstractmethod
    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        """Return normalized first-goal player odds snapshots for a date."""


class RecommendationsProvider(ABC):
    @abstractmethod
    def fetch_daily(self, selected_date: date) -> list[Recommendation]:
        """Return top daily recommendations for a date."""

    @abstractmethod
    def fetch_for_game(self, selected_date: date, game_id: str) -> list[Recommendation]:
        """Return recommendations for one game/date."""


class AvailabilityProvider(ABC):
    @abstractmethod
    def projections_available(self, selected_date: date) -> bool:
        """Return whether projections exist for a given date."""

    @abstractmethod
    def odds_available(self, selected_date: date) -> bool:
        """Return whether odds exist for a given date."""


# Backwards-compatibility alias while call-sites migrate to the new naming.
GamesProvider = ScheduleProvider
