import json
from datetime import date
from datetime import datetime
from datetime import timezone

import pytest

from app.api.routes import get_games
from app.api.schemas import GameSummary
from app.services.interfaces import PlayerHistoricalProduction, PlayerProjectionCandidate, PlayerRosterEligibility
from app.services.projection_store import (
    JsonArtifactProjectionStore,
    ProjectionStoreValidationError,
    StoreBackedProjectionProvider,
)
from app.services.provider_wiring import ProviderRegistry
from app.services.real_services import EmptyOddsProvider
from app.services.mock_services import MockGamesService, ValueRecommendationService


def _write_artifact(path, projections):
    path.write_text(json.dumps({"schema_version": 1, "projections": projections}), encoding="utf-8")


def test_store_loads_rows_for_selected_date(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": "2026-03-23",
                "game_id": "g-1",
                "player_id": "p-1",
                "player_name": "Player One",
                "team_name": "Team One",
                "model_probability": 0.22,
            },
            {
                "date": "2026-03-24",
                "game_id": "g-2",
                "player_id": "p-2",
                "player_name": "Player Two",
                "team_name": "Team Two",
                "model_probability": 0.18,
            },
        ],
    )

    store = JsonArtifactProjectionStore(artifact)
    provider = StoreBackedProjectionProvider(store=store)

    rows = provider.fetch_player_first_goal_projections(date(2026, 3, 23))

    assert len(rows) == 1
    assert rows[0].game_id == "g-1"
    assert rows[0].nhl_player_id == "p-1"
    assert rows[0].roster_eligibility.active_team_name == "Team One"
    assert rows[0].roster_eligibility.is_active_roster is True


@pytest.mark.parametrize(
    ("row", "error_fragment"),
    [
        (
            {
                "date": "2026-03-23",
                "game_id": "g-1",
                "player_name": "Player One",
                "team_name": "Team One",
                "model_probability": 0.22,
            },
            "missing or empty 'player_id'",
        ),
        (
            {
                "date": "2026-03-23",
                "player_id": "p-1",
                "player_name": "Player One",
                "team_name": "Team One",
                "model_probability": 0.22,
            },
            "missing or empty 'game_id'",
        ),
        (
            {
                "date": "2026-03-23",
                "game_id": "g-1",
                "player_id": "p-1",
                "player_name": "Player One",
                "team_name": "Team One",
                "model_probability": 1.4,
            },
            "invalid 'model_probability'",
        ),
    ],
)
def test_store_validation_rejects_invalid_rows(tmp_path, row, error_fragment) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [row])

    store = JsonArtifactProjectionStore(artifact)

    with pytest.raises(ProjectionStoreValidationError, match=error_fragment):
        store.load_for_date(date(2026, 3, 23))


def test_store_validation_rejects_duplicate_rows(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    base_row = {
        "date": "2026-03-23",
        "game_id": "g-1",
        "player_id": "p-1",
        "player_name": "Player One",
        "team_name": "Team One",
        "model_probability": 0.22,
    }
    _write_artifact(artifact, [base_row, dict(base_row)])

    store = JsonArtifactProjectionStore(artifact)

    with pytest.raises(ProjectionStoreValidationError, match="Duplicate projection row"):
        store.load_for_date(date(2026, 3, 23))


def test_store_backed_provider_returns_empty_when_artifact_is_invalid(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": "2026-03-23",
                "game_id": "g-1",
                "player_id": "p-1",
                "player_name": "Player One",
                "team_name": "Team One",
                "model_probability": 2.0,
            }
        ],
    )
    provider = StoreBackedProjectionProvider(store=JsonArtifactProjectionStore(artifact))

    rows = provider.fetch_player_first_goal_projections(date(2026, 3, 23))

    assert rows == []


def test_recommendation_routes_integrate_with_store_backed_projections(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    selected_date = date.today()
    _write_artifact(
        artifact,
        [
            {
                "date": selected_date.isoformat(),
                "game_id": "g-nyr-vs-bos",
                "player_id": "p-artemi-panarin",
                "player_name": "Artemi Panarin",
                "team_name": "NY Rangers",
                "model_probability": 0.34,
            }
        ],
    )

    schedule_provider = MockGamesService()
    projection_provider = StoreBackedProjectionProvider(store=JsonArtifactProjectionStore(artifact))
    odds_provider = EmptyOddsProvider()
    registry = ProviderRegistry(
        schedule_provider=schedule_provider,
        projection_provider=projection_provider,
        odds_provider=odds_provider,
        recommendation_service=ValueRecommendationService(
            schedule_provider=schedule_provider,
            projection_provider=projection_provider,
            odds_provider=odds_provider,
        ),
    )

    payload = get_games(date=selected_date, providers=registry)
    target_game = next(game for game in payload.games if game.game_id == "g-nyr-vs-bos")

    assert payload.projections_available is True
    assert target_game.away_top_projected_scorer is not None
    assert target_game.away_top_projected_scorer.player_id == "p-artemi-panarin"


def test_attach_top_projected_scorers_preserves_games_when_projections_missing(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    selected_date = date.today()
    _write_artifact(
        artifact,
        [
            {
                "date": selected_date.isoformat(),
                "game_id": "g-nyr-vs-bos",
                "player_id": "p-away-top",
                "player_name": "Away Top",
                "team_name": "NY Rangers",
                "model_probability": 0.32,
            },
            {
                "date": selected_date.isoformat(),
                "game_id": "g-nyr-vs-bos",
                "player_id": "p-home-top",
                "player_name": "Home Top",
                "team_name": "Boston Bruins",
                "model_probability": 0.41,
            },
        ],
    )

    schedule_provider = MockGamesService()
    projection_provider = StoreBackedProjectionProvider(store=JsonArtifactProjectionStore(artifact))
    odds_provider = EmptyOddsProvider()
    registry = ProviderRegistry(
        schedule_provider=schedule_provider,
        projection_provider=projection_provider,
        odds_provider=odds_provider,
        recommendation_service=ValueRecommendationService(
            schedule_provider=schedule_provider,
            projection_provider=projection_provider,
            odds_provider=odds_provider,
        ),
    )

    payload = get_games(date=selected_date, providers=registry)
    games_by_id = {game.game_id: game for game in payload.games}

    assert len(payload.games) == 3
    assert payload.projections_available is True
    assert games_by_id["g-col-vs-dal"].away_top_projected_scorer is None
    assert games_by_id["g-col-vs-dal"].home_top_projected_scorer is None
    assert games_by_id["g-nyr-vs-bos"].away_top_projected_scorer is not None
    assert games_by_id["g-nyr-vs-bos"].home_top_projected_scorer is not None


def test_attach_top_projected_scorers_attaches_highest_probability_per_team(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    selected_date = date.today()
    _write_artifact(
        artifact,
        [
            {
                "date": selected_date.isoformat(),
                "game_id": "g-nyr-vs-bos",
                "player_id": "p-away-second",
                "player_name": "Away Second",
                "team_name": "NY Rangers",
                "model_probability": 0.15,
            },
            {
                "date": selected_date.isoformat(),
                "game_id": "g-nyr-vs-bos",
                "player_id": "p-away-top",
                "player_name": "Away Top",
                "team_name": "NY Rangers",
                "model_probability": 0.33,
            },
            {
                "date": selected_date.isoformat(),
                "game_id": "g-nyr-vs-bos",
                "player_id": "p-home-top",
                "player_name": "Home Top",
                "team_name": "Boston Bruins",
                "model_probability": 0.41,
            },
        ],
    )

    schedule_provider = MockGamesService()
    projection_provider = StoreBackedProjectionProvider(store=JsonArtifactProjectionStore(artifact))
    odds_provider = EmptyOddsProvider()
    service = ValueRecommendationService(
        schedule_provider=schedule_provider,
        projection_provider=projection_provider,
        odds_provider=odds_provider,
    )

    games = schedule_provider.fetch(selected_date)
    enriched_games = service.attach_top_projected_scorers(selected_date, games)
    games_by_id = {game.game_id: game for game in enriched_games}

    assert len(enriched_games) == 3
    assert games_by_id["g-nyr-vs-bos"].away_top_projected_scorer is not None
    assert games_by_id["g-nyr-vs-bos"].away_top_projected_scorer.player_id == "p-away-top"
    assert games_by_id["g-nyr-vs-bos"].home_top_projected_scorer is not None
    assert games_by_id["g-nyr-vs-bos"].home_top_projected_scorer.player_id == "p-home-top"


def test_games_stay_visible_when_no_projection_rows_exist_for_date(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])

    schedule_provider = MockGamesService()
    projection_provider = StoreBackedProjectionProvider(store=JsonArtifactProjectionStore(artifact))
    odds_provider = EmptyOddsProvider()
    registry = ProviderRegistry(
        schedule_provider=schedule_provider,
        projection_provider=projection_provider,
        odds_provider=odds_provider,
        recommendation_service=ValueRecommendationService(
            schedule_provider=schedule_provider,
            projection_provider=projection_provider,
            odds_provider=odds_provider,
        ),
    )

    selected_date = date.today()
    payload = get_games(date=selected_date, providers=registry)

    assert len(payload.games) == 3
    assert payload.projections_available is False
    assert all(game.away_top_projected_scorer is None for game in payload.games)
    assert all(game.home_top_projected_scorer is None for game in payload.games)


def test_store_backed_projection_artifact_attaches_team_leaders_for_game_2025021119_with_team_alias_match(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    selected_date = date.today()
    _write_artifact(
        artifact,
        [
            {
                "date": selected_date.isoformat(),
                "game_id": "2025021119",
                "player_id": "p-away-top",
                "player_name": "Away Top",
                "team_name": "Blackhawks",
                "model_probability": 0.26,
            },
            {
                "date": selected_date.isoformat(),
                "game_id": "2025021119",
                "player_id": "p-away-secondary",
                "player_name": "Away Secondary",
                "team_name": "Blackhawks",
                "model_probability": 0.13,
            },
            {
                "date": selected_date.isoformat(),
                "game_id": "2025021119",
                "player_id": "p-home-top",
                "player_name": "Home Top",
                "team_name": "Wild",
                "model_probability": 0.31,
            },
            {
                "date": selected_date.isoformat(),
                "game_id": "2025021119",
                "player_id": "p-home-secondary",
                "player_name": "Home Secondary",
                "team_name": "Wild",
                "model_probability": 0.18,
            },
        ],
    )

    class _SingleGameScheduleProvider:
        def fetch(self, selected_date: date) -> list[GameSummary]:
            if selected_date != date.today():
                return []
            return [
                GameSummary(
                    game_id="2025021119",
                    game_time=datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc),
                    away_team="Chicago",
                    home_team="Minnesota",
                    status="FUT",
                )
            ]

    schedule_provider = _SingleGameScheduleProvider()
    projection_provider = StoreBackedProjectionProvider(store=JsonArtifactProjectionStore(artifact))
    odds_provider = EmptyOddsProvider()
    registry = ProviderRegistry(
        schedule_provider=schedule_provider,
        projection_provider=projection_provider,
        odds_provider=odds_provider,
        recommendation_service=ValueRecommendationService(
            schedule_provider=schedule_provider,
            projection_provider=projection_provider,
            odds_provider=odds_provider,
        ),
    )

    payload = get_games(date=selected_date, providers=registry)

    assert payload.projections_available is True
    assert len(payload.games) == 1
    assert payload.games[0].away_top_projected_scorer is not None
    assert payload.games[0].away_top_projected_scorer.player_id == "p-away-top"
    assert payload.games[0].home_top_projected_scorer is not None
    assert payload.games[0].home_top_projected_scorer.player_id == "p-home-top"


def test_projection_availability_false_when_rows_are_invalid_or_unmatched() -> None:
    class _InvalidProjectionProvider:
        def fetch_player_first_goal_projections(self, selected_date: date):
            return [
                PlayerProjectionCandidate(
                    game_id="g-nyr-vs-bos",
                    nhl_player_id="p-0",
                    player_name="No Player",
                    projected_team_name="NY Rangers",
                    model_probability=0.22,
                    historical_production=PlayerHistoricalProduction(),
                    roster_eligibility=PlayerRosterEligibility(active_team_name="No Team"),
                ),
                PlayerProjectionCandidate(
                    game_id="g-nyr-vs-bos",
                    nhl_player_id="p-1",
                    player_name="Bad Probability",
                    projected_team_name="NY Rangers",
                    model_probability=1.2,
                    historical_production=PlayerHistoricalProduction(),
                    roster_eligibility=PlayerRosterEligibility(active_team_name="NY Rangers"),
                ),
                PlayerProjectionCandidate(
                    game_id="g-col-vs-dal",
                    nhl_player_id="p-2",
                    player_name="Blank Team",
                    projected_team_name="Colorado Avalanche",
                    model_probability=0.23,
                    historical_production=PlayerHistoricalProduction(),
                    roster_eligibility=PlayerRosterEligibility(active_team_name=""),
                ),
            ]

    schedule_provider = MockGamesService()
    projection_provider = _InvalidProjectionProvider()
    odds_provider = EmptyOddsProvider()
    service = ValueRecommendationService(
        schedule_provider=schedule_provider,
        projection_provider=projection_provider,  # type: ignore[arg-type]
        odds_provider=odds_provider,
    )

    selected_date = date.today()
    games = schedule_provider.fetch(selected_date)
    enriched_games = service.attach_top_projected_scorers(selected_date, games)

    assert len(enriched_games) == 3
    assert service.projections_available(selected_date) is False
    assert all(game.away_top_projected_scorer is None for game in enriched_games)
    assert all(game.home_top_projected_scorer is None for game in enriched_games)


def test_traded_player_keeps_historical_totals_but_only_new_team_is_eligible(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": "2026-03-23",
                "game_id": "g-col-vs-dal",
                "nhl_player_id": "nhl-1001",
                "player_name": "Trade Player",
                "team_name": "NY Rangers",
                "active_team_name": "Boston Bruins",
                "is_active_roster": True,
                "historical_season_first_goals": 7,
                "historical_season_games_played": 59,
                "model_probability": 0.35,
            },
            {
                "date": "2026-03-23",
                "game_id": "g-nyr-vs-bos",
                "nhl_player_id": "nhl-1001",
                "player_name": "Trade Player",
                "team_name": "Boston Bruins",
                "active_team_name": "Boston Bruins",
                "is_active_roster": True,
                "historical_season_first_goals": 7,
                "historical_season_games_played": 59,
                "model_probability": 0.35,
            },
        ],
    )

    provider = StoreBackedProjectionProvider(store=JsonArtifactProjectionStore(artifact))
    rows = provider.fetch_player_first_goal_projections(date(2026, 3, 23))
    traded_player_rows = [row for row in rows if row.nhl_player_id == "nhl-1001"]
    assert len(traded_player_rows) == 2
    assert all(row.historical_production.season_first_goals == 7 for row in traded_player_rows)
    assert all(row.historical_production.season_games_played == 59 for row in traded_player_rows)

    schedule_provider = MockGamesService()
    odds_provider = EmptyOddsProvider()
    service = ValueRecommendationService(
        schedule_provider=schedule_provider,
        projection_provider=provider,
        odds_provider=odds_provider,
    )

    selected_date = date.today()
    games = schedule_provider.fetch(selected_date)
    game = next(item for item in service.attach_top_projected_scorers(date(2026, 3, 23), games) if item.game_id == "g-nyr-vs-bos")
    assert game.away_top_projected_scorer is None
    assert game.home_top_projected_scorer is not None
    assert game.home_top_projected_scorer.player_id == "nhl-1001"


def test_inactive_non_roster_player_is_excluded_from_top_scorer_and_recommendations(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": "2026-03-23",
                "game_id": "g-nyr-vs-bos",
                "nhl_player_id": "nhl-inactive",
                "player_name": "Inactive Player",
                "team_name": "Boston Bruins",
                "active_team_name": "Boston Bruins",
                "is_active_roster": False,
                "model_probability": 0.9,
            }
        ],
    )

    schedule_provider = MockGamesService()
    projection_provider = StoreBackedProjectionProvider(store=JsonArtifactProjectionStore(artifact))
    odds_provider = EmptyOddsProvider()
    service = ValueRecommendationService(
        schedule_provider=schedule_provider,
        projection_provider=projection_provider,
        odds_provider=odds_provider,
    )

    selected_date = date.today()
    games = schedule_provider.fetch(selected_date)
    game = next(item for item in service.attach_top_projected_scorers(date(2026, 3, 23), games) if item.game_id == "g-nyr-vs-bos")
    assert game.away_top_projected_scorer is None
    assert game.home_top_projected_scorer is None
    assert service.fetch_daily(date(2026, 3, 23)) == []
