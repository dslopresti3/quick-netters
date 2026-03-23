import io
import json
from datetime import date, datetime, time, timedelta, timezone
from urllib.error import URLError
from unittest.mock import patch

from app.api.routes import get_daily_recommendations, get_date_availability, get_game_recommendations, get_games
from app.api.schemas import GameSummary
from app.services.interfaces import (
    OddsProvider,
    PlayerHistoricalProduction,
    PlayerProjectionCandidate,
    PlayerRosterEligibility,
    ProjectionProvider,
    ScheduleProvider,
)
from app.services.mock_services import ValueRecommendationService
from app.services.odds import NormalizedPlayerOdds
from app.services.odds_provider import LiveOddsProvider
from app.services.provider_wiring import ProviderRegistry
from app.services.real_services import NhlScheduleProvider


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
    def fetch_player_first_goal_projections(self, selected_date: date) -> list[PlayerProjectionCandidate]:
        return [
            PlayerProjectionCandidate(
                game_id="g-custom-vs-test",
                nhl_player_id="p-custom",
                player_name="Injected Player",
                projected_team_name="Custom Home",
                model_probability=0.3,
                historical_production=PlayerHistoricalProduction(),
                roster_eligibility=PlayerRosterEligibility(active_team_name="Custom Home", is_active_roster=True),
            ),
        ]


class StubOddsProvider(OddsProvider):
    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        return [
            NormalizedPlayerOdds(
                nhl_game_id="g-custom-vs-test",
                nhl_player_id="p-custom",
                market_odds_american=250,
                snapshot_at=datetime.now(timezone.utc),
                provider_name="stub-odds",
                provider_event_id="evt-custom",
                provider_player_name_raw="Injected Player",
                provider_team_raw="Custom Home",
                away_team_raw="Custom Away",
                home_team_raw="Custom Home",
                provider_start_time=datetime.combine(selected_date, time(19, 0), tzinfo=timezone.utc),
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


class _StubRawOddsClient:
    provider_name = "the-odds-api"

    def fetch_raw_events(self, selected_date: date) -> list[dict]:
        return [
            {
                "id": "g-custom-vs-test",
                "away_team": "Custom Away",
                "home_team": "Custom Home",
                "commence_time": datetime.combine(selected_date, time(19, 0), tzinfo=timezone.utc).isoformat(),
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "markets": [
                            {
                                "key": "player_first_goal_scorer",
                                "last_update": datetime.now(timezone.utc).isoformat(),
                                "outcomes": [{"name": "Injected Player", "description": "Custom Home", "price": 250}],
                            }
                        ],
                    }
                ],
            }
        ]


def test_daily_recommendations_route_integrates_with_live_odds_provider() -> None:
    class _SlugProjectionProvider(ProjectionProvider):
        def fetch_player_first_goal_projections(self, selected_date: date) -> list[PlayerProjectionCandidate]:
            return [
                PlayerProjectionCandidate(
                    game_id="g-custom-vs-test",
                    nhl_player_id="player-injected-player",
                    player_name="Injected Player",
                    projected_team_name="Custom Home",
                    model_probability=0.3,
                    historical_production=PlayerHistoricalProduction(),
                    roster_eligibility=PlayerRosterEligibility(active_team_name="Custom Home", is_active_roster=True),
                )
            ]

    selected_date = date.today()
    schedule_provider = StubScheduleProvider()
    projection_provider = _SlugProjectionProvider()
    odds_provider = LiveOddsProvider(client=_StubRawOddsClient())  # type: ignore[arg-type]
    providers = ProviderRegistry(
        schedule_provider=schedule_provider,
        projection_provider=projection_provider,
        odds_provider=odds_provider,
        recommendation_service=ValueRecommendationService(
            schedule_provider=schedule_provider,
            projection_provider=projection_provider,
            odds_provider=odds_provider,
        ),
    )

    payload = get_daily_recommendations(date=selected_date, providers=providers)

    assert payload.odds_available is True
    assert payload.recommendations[0].market_odds == 250


class EmptyScheduleProvider(ScheduleProvider):
    def fetch(self, selected_date: date) -> list[GameSummary]:
        return []


class EmptyProjectionProvider(ProjectionProvider):
    def fetch_player_first_goal_projections(self, selected_date: date) -> list[PlayerProjectionCandidate]:
        return []


class EmptyOddsProvider(OddsProvider):
    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        return []


def _registry_with(
    schedule_provider: ScheduleProvider,
    projection_provider: ProjectionProvider,
    odds_provider: OddsProvider,
) -> ProviderRegistry:
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


def test_date_availability_invalid_by_product_rule() -> None:
    selected_date = date.today() + timedelta(days=2)

    payload = get_date_availability(date=selected_date, providers=_provider_registry())

    assert payload.status == "invalid_date"
    assert payload.valid_by_product_rule is False
    assert payload.schedule_available is False


def test_date_availability_valid_with_no_schedule() -> None:
    selected_date = date.today()
    providers = _registry_with(
        schedule_provider=EmptyScheduleProvider(),
        projection_provider=StubProjectionProvider(),
        odds_provider=StubOddsProvider(),
    )

    payload = get_date_availability(date=selected_date, providers=providers)

    assert payload.status == "no_schedule"
    assert payload.valid_by_product_rule is True
    assert payload.schedule_available is False


def test_date_availability_valid_with_schedule_missing_projections() -> None:
    selected_date = date.today()
    providers = _registry_with(
        schedule_provider=StubScheduleProvider(),
        projection_provider=EmptyProjectionProvider(),
        odds_provider=StubOddsProvider(),
    )

    payload = get_date_availability(date=selected_date, providers=providers)

    assert payload.status == "missing_projections"
    assert payload.schedule_available is True
    assert payload.projections_available is False


def test_date_availability_valid_with_schedule_and_projections_missing_odds() -> None:
    selected_date = date.today()
    providers = _registry_with(
        schedule_provider=StubScheduleProvider(),
        projection_provider=StubProjectionProvider(),
        odds_provider=EmptyOddsProvider(),
    )

    payload = get_date_availability(date=selected_date, providers=providers)

    assert payload.status == "missing_odds"
    assert payload.schedule_available is True
    assert payload.projections_available is True
    assert payload.odds_available is False


def test_date_availability_ready_when_all_data_is_available() -> None:
    selected_date = date.today()

    payload = get_date_availability(date=selected_date, providers=_provider_registry())

    assert payload.status == "ready"
    assert payload.valid_by_product_rule is True
    assert payload.schedule_available is True
    assert payload.projections_available is True
    assert payload.odds_available is True


def test_games_route_real_schedule_provider_non_empty_with_upstream_payload() -> None:
    selected_date = date(2026, 3, 23)
    schedule_provider = NhlScheduleProvider()
    providers = _registry_with(
        schedule_provider=schedule_provider,
        projection_provider=EmptyProjectionProvider(),
        odds_provider=EmptyOddsProvider(),
    )
    payload = {
        "gameWeek": [
            {
                "date": "2026-03-23",
                "games": [
                    {
                        "id": 2026020101,
                        "gameDate": "2026-03-24",
                        "startTimeUTC": "2026-03-24T01:00:00Z",
                        "gameState": "FUT",
                        "awayTeam": {"commonName": {"default": "Devils"}},
                        "homeTeam": {"commonName": {"default": "Islanders"}},
                    }
                ],
            }
        ]
    }

    class _FakeResponse(io.StringIO):
        def __init__(self, raw_payload: dict) -> None:
            super().__init__(json.dumps(raw_payload))

        def getcode(self) -> int:
            return 200

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            self.close()

    with patch("app.services.real_services.urlopen", side_effect=lambda *args, **kwargs: _FakeResponse(payload)):
        response = get_games(date=selected_date, providers=providers)

    assert len(response.games) == 1


def test_games_route_includes_note_when_schedule_fetch_fails() -> None:
    selected_date = date(2026, 3, 23)
    schedule_provider = NhlScheduleProvider()
    providers = _registry_with(
        schedule_provider=schedule_provider,
        projection_provider=EmptyProjectionProvider(),
        odds_provider=EmptyOddsProvider(),
    )

    with patch("app.services.real_services.urlopen", side_effect=URLError("boom")):
        response = get_games(date=selected_date, providers=providers)

    assert response.games == []
    assert any("NHL schedule fetch failed for 2026-03-23" in note for note in response.notes)
