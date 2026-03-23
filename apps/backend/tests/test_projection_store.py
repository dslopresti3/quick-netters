import json
from datetime import date

import pytest

from app.api.routes import get_games
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

    assert rows == [("g-1", "p-1", "Player One", "Team One", 0.22)]


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


def test_recommendation_routes_integrate_with_store_backed_projections(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": "2026-03-23",
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

    payload = get_games(date=date(2026, 3, 23), providers=registry)
    target_game = next(game for game in payload.games if game.game_id == "g-nyr-vs-bos")

    assert payload.projections_available is True
    assert target_game.away_top_projected_scorer is not None
    assert target_game.away_top_projected_scorer.player_id == "p-artemi-panarin"
