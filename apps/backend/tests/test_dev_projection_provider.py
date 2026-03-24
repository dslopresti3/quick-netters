import json
from datetime import date, datetime, timezone

from app.api.schemas import GameSummary
from app.services.dev_projection_provider import ActiveRosterRepository, AutoGeneratingProjectionProvider
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
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(json.dumps({"players": [
        {"player_id": "8479323", "player_name": "Artemi Panarin", "active_team_name": "NY Rangers", "is_active_roster": True, "historical_season_first_goals": 8, "historical_season_games_played": 82},
        {"player_id": "8476459", "player_name": "Mika Zibanejad", "active_team_name": "NY Rangers", "is_active_roster": True, "historical_season_first_goals": 7, "historical_season_games_played": 81},
        {"player_id": "8475184", "player_name": "Chris Kreider", "active_team_name": "NY Rangers", "is_active_roster": True, "historical_season_first_goals": 6, "historical_season_games_played": 80},
        {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "Boston Bruins", "is_active_roster": True, "historical_season_first_goals": 9, "historical_season_games_played": 82},
        {"player_id": "8473419", "player_name": "Brad Marchand", "active_team_name": "Boston Bruins", "is_active_roster": True, "historical_season_first_goals": 6, "historical_season_games_played": 78},
        {"player_id": "8482089", "player_name": "Pavel Zacha", "active_team_name": "Boston Bruins", "is_active_roster": True, "historical_season_first_goals": 4, "historical_season_games_played": 80}
    ]}), encoding="utf-8")
    provider = AutoGeneratingProjectionProvider(
        base_provider=base_provider,
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
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
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(json.dumps({"players": [
        {"player_id": "8479323", "player_name": "Artemi Panarin", "active_team_name": "NY Rangers", "is_active_roster": True, "historical_season_first_goals": 8, "historical_season_games_played": 82},
        {"player_id": "8476459", "player_name": "Mika Zibanejad", "active_team_name": "NY Rangers", "is_active_roster": True, "historical_season_first_goals": 7, "historical_season_games_played": 81},
        {"player_id": "8475184", "player_name": "Chris Kreider", "active_team_name": "NY Rangers", "is_active_roster": True, "historical_season_first_goals": 6, "historical_season_games_played": 80},
        {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "Boston Bruins", "is_active_roster": True, "historical_season_first_goals": 9, "historical_season_games_played": 82},
        {"player_id": "8473419", "player_name": "Brad Marchand", "active_team_name": "Boston Bruins", "is_active_roster": True, "historical_season_first_goals": 6, "historical_season_games_played": 78},
        {"player_id": "8482089", "player_name": "Pavel Zacha", "active_team_name": "Boston Bruins", "is_active_roster": True, "historical_season_first_goals": 4, "historical_season_games_played": 80}
    ]}), encoding="utf-8")
    provider = AutoGeneratingProjectionProvider(
        base_provider=base_provider,
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    assert len(rows) == 1
    persisted = json.loads(artifact.read_text(encoding="utf-8"))["projections"]
    assert len(persisted) == 1


def test_generated_rows_use_real_player_identities_and_not_dev_placeholders(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])
    selected_date = date(2026, 3, 24)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026020002",
                    game_time=datetime(2026, 3, 24, 23, 30, tzinfo=timezone.utc),
                    away_team="Toronto Maple Leafs",
                    home_team="Boston Bruins",
                )
            ]
        }
    )
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(
        json.dumps(
            {
                "players": [
                    {"player_id": "8477939", "player_name": "Auston Matthews", "active_team_name": "Toronto Maple Leafs", "is_active_roster": True, "historical_season_first_goals": 10, "historical_season_games_played": 81},
                    {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "Boston Bruins", "is_active_roster": True, "historical_season_first_goals": 9, "historical_season_games_played": 82}
                ]
            }
        ),
        encoding="utf-8",
    )

    provider = AutoGeneratingProjectionProvider(
        base_provider=StoreBackedProjectionProvider(store=JsonArtifactProjectionStore(artifact)),
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    assert rows
    assert all(not row.nhl_player_id.startswith("dev-") for row in rows)
    assert {row.player_name for row in rows} == {"Auston Matthews", "David Pastrnak"}


def test_only_active_roster_players_and_current_team_eligibility_are_generated(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])
    selected_date = date(2026, 3, 25)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026020099",
                    game_time=datetime(2026, 3, 25, 23, 0, tzinfo=timezone.utc),
                    away_team="Colorado Avalanche",
                    home_team="Dallas Stars",
                )
            ]
        }
    )
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(
        json.dumps(
            {
                "players": [
                    {"player_id": "8480820", "player_name": "Mikko Rantanen", "active_team_name": "Dallas Stars", "is_active_roster": True, "historical_season_first_goals": 7, "historical_season_games_played": 82},
                    {"player_id": "8477492", "player_name": "Nathan MacKinnon", "active_team_name": "Colorado Avalanche", "is_active_roster": True, "historical_season_first_goals": 8, "historical_season_games_played": 82},
                    {"player_id": "retired-1", "player_name": "Inactive Depth", "active_team_name": "Colorado Avalanche", "is_active_roster": False, "historical_season_first_goals": 1, "historical_season_games_played": 20}
                ]
            }
        ),
        encoding="utf-8",
    )

    provider = AutoGeneratingProjectionProvider(
        base_provider=StoreBackedProjectionProvider(store=JsonArtifactProjectionStore(artifact)),
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    assert {row.player_name for row in rows} == {"Mikko Rantanen", "Nathan MacKinnon"}
    rantanen = next(row for row in rows if row.player_name == "Mikko Rantanen")
    assert rantanen.projected_team_name == "Dallas Stars"
    assert rantanen.roster_eligibility.active_team_name == "Dallas Stars"
    assert all(row.player_name != "Inactive Depth" for row in rows)
