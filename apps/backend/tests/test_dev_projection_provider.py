import json
from datetime import date, datetime, timezone

from app.api.schemas import GameSummary
from app.services.dev_projection_provider import AutoGeneratingProjectionProvider
from app.services.interfaces import ScheduleProvider
from app.services.projection_store import JsonArtifactProjectionStore, StoreBackedProjectionProvider


class _StaticScheduleProvider(ScheduleProvider):
    def __init__(self, games_by_date: dict[date, list[GameSummary]]) -> None:
        self._games_by_date = games_by_date

    def fetch(self, selected_date: date) -> list[GameSummary]:
        return [game.model_copy(deep=True) for game in self._games_by_date.get(selected_date, [])]


def _write_artifact(path, projections):
    path.write_text(json.dumps({"schema_version": 1, "projections": projections}), encoding="utf-8")


def test_auto_generates_rows_for_missing_date_and_persists_artifact(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": "2026-03-23",
                "game_id": "g-existing",
                "nhl_player_id": "existing-player-1",
                "player_name": "Existing Skater",
                "team_name": "Existing Team",
                "active_team_name": "Existing Team",
                "is_active_roster": True,
                "model_probability": 0.16,
            }
        ],
    )
    selected_date = date(2026, 3, 24)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026020001",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
                    away_team="NY Rangers",
                    home_team="Boston Bruins",
                )
            ]
        }
    )
    base_provider = StoreBackedProjectionProvider(store=JsonArtifactProjectionStore(artifact))
    provider = AutoGeneratingProjectionProvider(
        base_provider=base_provider,
        schedule_provider=schedule_provider,
        artifact_path=artifact,
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    assert len(rows) == 6
    assert all(row.game_id == "2026020001" for row in rows)
    assert all(row.roster_eligibility.is_active_roster for row in rows)

    persisted = json.loads(artifact.read_text(encoding="utf-8"))["projections"]
    assert len([row for row in persisted if row.get("date") == "2026-03-24"]) == 6
    assert len([row for row in persisted if row.get("date") == "2026-03-23"]) == 1

    rows_second_fetch = provider.fetch_player_first_goal_projections(selected_date)
    assert len(rows_second_fetch) == 6
    persisted_second_fetch = json.loads(artifact.read_text(encoding="utf-8"))["projections"]
    assert persisted_second_fetch == persisted


def test_uses_existing_rows_without_regenerating(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": "2026-03-24",
                "game_id": "2026020001",
                "nhl_player_id": "existing-player-1",
                "player_name": "Existing Skater",
                "team_name": "NY Rangers",
                "active_team_name": "NY Rangers",
                "is_active_roster": True,
                "model_probability": 0.16,
            }
        ],
    )
    selected_date = date(2026, 3, 24)
    schedule_provider = _StaticScheduleProvider({selected_date: []})
    base_provider = StoreBackedProjectionProvider(store=JsonArtifactProjectionStore(artifact))
    provider = AutoGeneratingProjectionProvider(
        base_provider=base_provider,
        schedule_provider=schedule_provider,
        artifact_path=artifact,
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    assert len(rows) == 1
    persisted = json.loads(artifact.read_text(encoding="utf-8"))["projections"]
    assert len(persisted) == 1
