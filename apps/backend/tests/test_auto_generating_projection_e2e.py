import json
from datetime import date, datetime, timezone

from app.api.routes import get_games
from app.api.schemas import GameSummary
from app.services.dev_projection_provider import AutoGeneratingProjectionProvider
from app.services.interfaces import ScheduleProvider
from app.services.mock_services import ValueRecommendationService
from app.services.projection_store import JsonArtifactProjectionStore, StoreBackedProjectionProvider
from app.services.provider_wiring import ProviderRegistry
from app.services.real_services import EmptyOddsProvider


class _StaticScheduleProvider(ScheduleProvider):
    def __init__(self, games_by_date: dict[date, list[GameSummary]]) -> None:
        self._games_by_date = games_by_date

    def fetch(self, selected_date: date) -> list[GameSummary]:
        return [game.model_copy(deep=True) for game in self._games_by_date.get(selected_date, [])]


def _build_registry(artifact_path, schedule_provider: ScheduleProvider) -> ProviderRegistry:
    base_projection_provider = StoreBackedProjectionProvider(store=JsonArtifactProjectionStore(artifact_path))
    projection_provider = AutoGeneratingProjectionProvider(
        base_provider=base_projection_provider,
        schedule_provider=schedule_provider,
        artifact_path=artifact_path,
    )
    odds_provider = EmptyOddsProvider()
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


def test_get_games_returns_generated_projections_for_2026_03_24_and_2026_03_25(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    artifact.write_text(json.dumps({"schema_version": 1, "projections": []}), encoding="utf-8")
    schedule_provider = _StaticScheduleProvider(
        {
            date(2026, 3, 24): [
                GameSummary(
                    game_id="2026032401",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
                    away_team="NY Rangers",
                    home_team="Boston Bruins",
                )
            ],
            date(2026, 3, 25): [
                GameSummary(
                    game_id="2026032501",
                    game_time=datetime(2026, 3, 25, 23, 0, tzinfo=timezone.utc),
                    away_team="Colorado Avalanche",
                    home_team="Dallas Stars",
                )
            ],
        }
    )
    registry = _build_registry(artifact, schedule_provider)

    payload_24 = get_games(date=date(2026, 3, 24), providers=registry)
    assert payload_24.projections_available is True
    assert len(payload_24.games) == 1
    assert payload_24.games[0].away_top_projected_scorer is not None
    assert payload_24.games[0].home_top_projected_scorer is not None

    artifact_after_24 = json.loads(artifact.read_text(encoding="utf-8"))
    rows_24 = [row for row in artifact_after_24["projections"] if row.get("date") == "2026-03-24"]
    assert len(rows_24) == 6

    payload_25 = get_games(date=date(2026, 3, 25), providers=registry)
    assert payload_25.projections_available is True
    assert len(payload_25.games) == 1
    assert payload_25.games[0].away_top_projected_scorer is not None
    assert payload_25.games[0].home_top_projected_scorer is not None

    artifact_after_25 = json.loads(artifact.read_text(encoding="utf-8"))
    rows_25 = [row for row in artifact_after_25["projections"] if row.get("date") == "2026-03-25"]
    assert len(rows_25) == 6

    payload_24_second = get_games(date=date(2026, 3, 24), providers=registry)
    assert payload_24_second.projections_available is True
    artifact_after_24_second = json.loads(artifact.read_text(encoding="utf-8"))
    assert artifact_after_24_second == artifact_after_25
