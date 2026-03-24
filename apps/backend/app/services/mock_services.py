from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from app.api.schemas import GameSummary
from app.services.interfaces import OddsProvider, PlayerProjectionCandidate, ProjectionProvider, ScheduleProvider
from app.services.odds import NormalizedPlayerOdds
from app.services.odds_provider import LiveOddsProvider
from app.services.projection_store import build_mock_projection_provider
from app.services.recommendation_service import (
    ValueRecommendationService,
    _match_event_to_game,
    _match_player_to_projection,
)


class MockGamesService(ScheduleProvider):
    def __init__(self) -> None:
        self._cache: dict[date, list[GameSummary]] = {}

    def fetch(self, selected_date: date) -> list[GameSummary]:
        if selected_date in self._cache:
            return [game.model_copy(deep=True) for game in self._cache[selected_date]]

        self._cache[selected_date] = _build_games(selected_date)
        return [game.model_copy(deep=True) for game in self._cache[selected_date]]


class MockProjectionService(ProjectionProvider):
    """Mock provider that reads first-goal projections from a structured artifact store."""

    def __init__(self) -> None:
        self._provider = build_mock_projection_provider()

    def fetch_player_first_goal_projections(self, selected_date: date) -> list[PlayerProjectionCandidate]:
        if selected_date == date.today() + timedelta(days=1):
            return []
        return self._provider.fetch_player_first_goal_projections(selected_date)


class MockOddsService(OddsProvider):
    """Mock-mode wrapper around the live odds provider contract."""

    def __init__(self) -> None:
        self._provider = LiveOddsProvider()

    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        return self._provider.fetch_player_first_goal_odds(selected_date)


class MockRecommendationsService(ValueRecommendationService):
    def __init__(self) -> None:
        schedule_provider = MockGamesService()
        projection_provider = MockProjectionService()
        odds_provider = MockOddsService()
        super().__init__(schedule_provider=schedule_provider, projection_provider=projection_provider, odds_provider=odds_provider)


def _build_games(selected_date: date) -> list[GameSummary]:
    if selected_date > date.today() + timedelta(days=1):
        return []

    return [
        GameSummary(
            game_id="g-nyr-vs-bos",
            game_time=datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc),
            away_team="NY Rangers",
            home_team="Boston Bruins",
        ),
        GameSummary(
            game_id="g-col-vs-dal",
            game_time=datetime.combine(selected_date + timedelta(days=1), time(0, 30), tzinfo=timezone.utc),
            away_team="Colorado Avalanche",
            home_team="Dallas Stars",
        ),
        GameSummary(
            game_id="g-lak-vs-vgk",
            game_time=datetime.combine(selected_date + timedelta(days=1), time(3, 0), tzinfo=timezone.utc),
            away_team="LA Kings",
            home_team="Vegas Golden Knights",
        ),
    ]
