from datetime import date, datetime, time, timezone

from app.api.routes import get_daily_recommendations, get_game_recommendations, get_games
from app.api.schemas import GameSummary
from app.services.interfaces import OddsProvider, ProjectionProvider, ScheduleProvider
from app.services.mock_services import ValueRecommendationService
from app.services.odds import NormalizedPlayerOdds
from app.services.provider_wiring import ProviderRegistry


class StubScheduleProvider(ScheduleProvider):
    def fetch(self, selected_date: date) -> list[GameSummary]:
        return [
            GameSummary(
                game_id="g-custom-vs-test",
                game_time=datetime.combine(selected_date, time(19, 0), tzinfo=timezone.utc),
                away_team="Custom Away",
                home_team="Custom Home",
            )
        ]


class StubProjectionProvider(ProjectionProvider):
    def fetch_player_first_goal_projections(self, selected_date: date) -> list[tuple[str, str, str, str, float]]:
        return [
            ("g-custom-vs-test", "p-custom", "Injected Player", "Custom Home", 0.3),
        ]


class StubOddsProvider(OddsProvider):
    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        return [
            NormalizedPlayerOdds(
                game_id="g-custom-vs-test",
                player_id="p-custom",
                market_odds_american=250,
                snapshot_at=datetime.combine(selected_date, time(18, 30), tzinfo=timezone.utc),
            )
        ]


def _provider_registry() -> ProviderRegistry:
    schedule_provider = StubScheduleProvider()
    projection_provider = StubProjectionProvider()
    odds_provider = StubOddsProvider()

    return ProviderRegistry(
        schedule_provider=schedule_provider,
        projection_provider=projection_provider,
        odds_provider=odds_provider,
        recommendation_service=ValueRecommendationService(
            schedule_provider=schedule_provider,
            projection_provider=projection_provider,
            odds_provider=odds_provider,
        ),
    )


def test_games_route_uses_injected_schedule_provider() -> None:
    selected_date = date.today()

    payload = get_games(date=selected_date, providers=_provider_registry())

    assert payload.games[0].game_id == "g-custom-vs-test"
    assert payload.games[0].home_top_projected_scorer is not None
    assert payload.games[0].home_top_projected_scorer.player_id == "p-custom"


def test_daily_recommendations_route_uses_injected_recommendation_dependencies() -> None:
    selected_date = date.today()

    payload = get_daily_recommendations(date=selected_date, providers=_provider_registry())

    assert payload.recommendations[0].game_id == "g-custom-vs-test"
    assert payload.recommendations[0].player_id == "p-custom"


def test_game_recommendations_route_uses_injected_registry() -> None:
    selected_date = date.today()

    payload = get_game_recommendations(game_id="g-custom-vs-test", date=selected_date, providers=_provider_registry())

    assert payload.game.game_id == "g-custom-vs-test"
    assert payload.recommendations[0].player_id == "p-custom"
