from datetime import date

from app.api.schemas import GameSummary
from app.services.interfaces import OddsProvider, ProjectionProvider, ScheduleProvider
from app.services.odds import NormalizedPlayerOdds


class EmptyScheduleProvider(ScheduleProvider):
    """Production wiring placeholder until live schedule integration is added."""

    def fetch(self, selected_date: date) -> list[GameSummary]:
        return []


class EmptyProjectionProvider(ProjectionProvider):
    """Production wiring placeholder until model projection integration is added."""

    def fetch_player_first_goal_projections(self, selected_date: date) -> list[tuple[str, str, str, str, float]]:
        return []


class EmptyOddsProvider(OddsProvider):
    """Production wiring placeholder until live odds integration is added."""

    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        return []
