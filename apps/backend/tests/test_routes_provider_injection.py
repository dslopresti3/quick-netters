from datetime import date, datetime, time, timedelta, timezone
from urllib.error import URLError
from unittest.mock import patch

import pytest
from app.api.routes import get_daily_recommendations, get_date_availability, get_game_recommendations, get_games
from app.api.schemas import GameSummary
from fastapi import HTTPException
from app.services.interfaces import (
    OddsProvider,
    PlayerHistoricalProduction,
    PlayerProjectionCandidate,
    PlayerRosterEligibility,
    ProjectionProvider,
    ScheduleProvider,
)
from app.services.recommendation_service import ValueRecommendationService
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


def test_games_route_excludes_goalies_from_top_projected_scorer() -> None:
    class _GoalieProjectionProvider(ProjectionProvider):
        def fetch_player_first_goal_projections(self, selected_date: date) -> list[PlayerProjectionCandidate]:
            return [
                PlayerProjectionCandidate(
                    game_id="g-custom-vs-test",
                    nhl_player_id="goalie-1",
                    player_name="Goalie Candidate",
                    projected_team_name="Custom Home",
                    model_probability=0.9,
                    historical_production=PlayerHistoricalProduction(),
                    roster_eligibility=PlayerRosterEligibility(
                        active_team_name="Custom Home",
                        is_active_roster=True,
                        position_code="G",
                    ),
                ),
                PlayerProjectionCandidate(
                    game_id="g-custom-vs-test",
                    nhl_player_id="skater-1",
                    player_name="Skater Candidate",
                    projected_team_name="Custom Home",
                    model_probability=0.2,
                    historical_production=PlayerHistoricalProduction(),
                    roster_eligibility=PlayerRosterEligibility(
                        active_team_name="Custom Home",
                        is_active_roster=True,
                        position_code="C",
                    ),
                ),
            ]

    selected_date = date.today()
    schedule_provider = StubScheduleProvider()
    projection_provider = _GoalieProjectionProvider()
    odds_provider = StubOddsProvider()
    providers = _registry_with(
        schedule_provider=schedule_provider,
        projection_provider=projection_provider,
        odds_provider=odds_provider,
    )

    payload = get_games(date=selected_date, providers=providers)

    assert payload.games[0].home_top_projected_scorer is not None
    assert payload.games[0].home_top_projected_scorer.player_id == "skater-1"


def test_games_route_defaults_display_time_to_america_new_york() -> None:
    selected_date = date(2026, 3, 24)
    payload = get_games(date=selected_date, providers=_provider_registry())

    assert payload.games[0].display_timezone == "America/New_York"
    assert payload.games[0].display_game_time == "2026-03-24 03:00 PM"


def test_games_route_uses_requested_display_timezone_when_valid() -> None:
    selected_date = date(2026, 3, 24)
    payload = get_games(date=selected_date, timezone="America/Los_Angeles", providers=_provider_registry())

    assert payload.games[0].display_timezone == "America/Los_Angeles"
    assert payload.games[0].display_game_time == "2026-03-24 12:00 PM"


def test_daily_recommendations_route_uses_injected_recommendation_dependencies() -> None:
    selected_date = date.today()

    payload = get_daily_recommendations(date=selected_date, providers=_provider_registry())

    assert payload.recommendations[0].game_id == "g-custom-vs-test"
    assert payload.recommendations[0].player_id == "p-custom"
    assert payload.recommendations[0].team_name == "Custom Home"
    assert payload.recommendations[0].implied_probability is not None


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
                                "key": "player_goal_scorer_first",
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
    assert payload.recommendations[0].team_name == "Custom Home"


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
    selected_date = date.today()
    schedule_provider = NhlScheduleProvider()
    providers = _registry_with(
        schedule_provider=schedule_provider,
        projection_provider=EmptyProjectionProvider(),
        odds_provider=EmptyOddsProvider(),
    )
    payload = {
        "gameWeek": [
            {
                "date": selected_date.isoformat(),
                "games": [
                    {
                        "id": 2026020101,
                        "gameDate": selected_date.isoformat(),
                        "startTimeUTC": datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc).isoformat(),
                        "gameState": "FUT",
                        "awayTeam": {"commonName": {"default": "Devils"}},
                        "homeTeam": {"commonName": {"default": "Islanders"}},
                    }
                ],
            }
        ]
    }

    with patch("app.services.real_services.fetch_json", return_value=payload):
        response = get_games(date=selected_date, providers=providers)

    assert len(response.games) == 1


def test_games_route_includes_note_when_schedule_fetch_fails() -> None:
    selected_date = date.today()
    schedule_provider = NhlScheduleProvider()
    providers = _registry_with(
        schedule_provider=schedule_provider,
        projection_provider=EmptyProjectionProvider(),
        odds_provider=EmptyOddsProvider(),
    )

    with patch("app.services.real_services.fetch_json", side_effect=URLError("boom")):
        with pytest.raises(HTTPException) as exc_info:
            get_games(date=selected_date, providers=providers)

    assert exc_info.value.status_code == 503
    assert f"NHL schedule fetch failed for {selected_date.isoformat()}" in str(exc_info.value.detail)
