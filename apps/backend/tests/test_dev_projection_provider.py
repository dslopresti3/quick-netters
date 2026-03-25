import json
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from app.api.schemas import GameSummary
from app.services.dev_projection_provider import ActiveRosterRepository, AutoGeneratingProjectionProvider, NhlApiActiveRosterRepository
from app.services.interfaces import PlayerHistoricalProduction, ScheduleProvider


class _StaticScheduleProvider(ScheduleProvider):
    def __init__(self, games_by_date: dict[date, list[GameSummary]]) -> None:
        self._games_by_date = games_by_date

    def fetch(self, selected_date: date) -> list[GameSummary]:
        return [game.model_copy(deep=True) for game in self._games_by_date.get(selected_date, [])]


class _RecordingScheduleProvider(_StaticScheduleProvider):
    def __init__(self, games_by_date: dict[date, list[GameSummary]], calls: list[str]) -> None:
        super().__init__(games_by_date)
        self._calls = calls

    def fetch(self, selected_date: date) -> list[GameSummary]:
        self._calls.append("schedule")
        return super().fetch(selected_date)


class _RecordingRosterRepository(ActiveRosterRepository):
    def __init__(self, roster_path, calls: list[str]) -> None:
        super().__init__(roster_path=roster_path)
        self._calls = calls

    def active_players_for_team(self, team_name: str):
        self._calls.append("roster")
        return super().active_players_for_team(team_name)


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


def test_does_not_reuse_existing_rows_when_no_schedule_is_available(tmp_path) -> None:
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
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    assert rows == []
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


def test_replaces_stale_dev_placeholder_rows_with_real_generated_rows(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": "2026-03-24",
                "game_id": "2025021120",
                "nhl_player_id": "dev-2025021120-away-maple-leafs-1",
                "player_name": "Maple Leafs Skater A",
                "team_name": "Toronto Maple Leafs",
                "active_team_name": "Toronto Maple Leafs",
                "is_active_roster": True,
                "model_probability": 0.16,
            },
            {
                "date": "2026-03-24",
                "game_id": "2025021120",
                "nhl_player_id": "dev-2025021120-home-bruins-1",
                "player_name": "Boston Bruins Skater A",
                "team_name": "Boston Bruins",
                "active_team_name": "Boston Bruins",
                "is_active_roster": True,
                "model_probability": 0.16,
            },
        ],
    )
    selected_date = date(2026, 3, 24)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2025021120",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
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
                    {"player_id": "8478402", "player_name": "Mitch Marner", "active_team_name": "Toronto Maple Leafs", "is_active_roster": True, "historical_season_first_goals": 8, "historical_season_games_played": 82},
                    {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "Boston Bruins", "is_active_roster": True, "historical_season_first_goals": 9, "historical_season_games_played": 82},
                    {"player_id": "8473419", "player_name": "Brad Marchand", "active_team_name": "Boston Bruins", "is_active_roster": True, "historical_season_first_goals": 6, "historical_season_games_played": 78}
                ]
            }
        ),
        encoding="utf-8",
    )

    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
        enable_dev_fallback=True,
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    assert rows
    assert all(not row.nhl_player_id.startswith("dev-") for row in rows)
    assert {row.player_name for row in rows} == {
        "Auston Matthews",
        "Mitch Marner",
        "David Pastrnak",
        "Brad Marchand",
    }

    persisted = json.loads(artifact.read_text(encoding="utf-8"))["projections"]
    rows_24 = [row for row in persisted if row.get("date") == "2026-03-24"]
    assert rows_24
    assert all(not str(row.get("player_id", "")).startswith("dev-") for row in rows_24)
    assert all("Skater" not in str(row.get("player_name", "")) for row in rows_24)


def test_regenerates_projection_rows_when_historical_store_is_newer(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    artifact.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "historical_first_goal_tracking": {
                    "20252026": {
                        "processed_game_ids": ["2026020001"],
                        "player_first_goal_totals": {"8479323": 8},
                        "player_first_period_goal_totals": {"8479323": 12},
                        "last_updated_on": "2026-03-24",
                    }
                },
                "projections": [
                    {
                        "date": "2026-03-24",
                        "projection_generated_on": "2026-03-23",
                        "game_id": "2026020001",
                        "nhl_player_id": "stale-player-1",
                        "player_name": "Stale Away",
                        "team_name": "NY Rangers",
                        "active_team_name": "NY Rangers",
                        "is_active_roster": True,
                        "position_code": "C",
                        "model_probability": 0.4,
                    },
                    {
                        "date": "2026-03-24",
                        "projection_generated_on": "2026-03-23",
                        "game_id": "2026020001",
                        "nhl_player_id": "stale-player-2",
                        "player_name": "Stale Home",
                        "team_name": "Boston Bruins",
                        "active_team_name": "Boston Bruins",
                        "is_active_roster": True,
                        "position_code": "C",
                        "model_probability": 0.6,
                    },
                ],
            }
        ),
        encoding="utf-8",
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
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(
        json.dumps(
            {
                "players": [
                    {"player_id": "8479323", "player_name": "Artemi Panarin", "active_team_name": "NY Rangers", "is_active_roster": True, "position_code": "LW", "historical_season_first_goals": 8, "historical_season_games_played": 82},
                    {"player_id": "8476459", "player_name": "Mika Zibanejad", "active_team_name": "NY Rangers", "is_active_roster": True, "position_code": "C", "historical_season_first_goals": 7, "historical_season_games_played": 81},
                    {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "Boston Bruins", "is_active_roster": True, "position_code": "RW", "historical_season_first_goals": 9, "historical_season_games_played": 82},
                    {"player_id": "8473419", "player_name": "Brad Marchand", "active_team_name": "Boston Bruins", "is_active_roster": True, "position_code": "LW", "historical_season_first_goals": 6, "historical_season_games_played": 78},
                ]
            }
        ),
        encoding="utf-8",
    )
    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    assert len(rows) == 4
    assert all(not row.nhl_player_id.startswith("stale-player") for row in rows)

    persisted_rows = [
        row
        for row in json.loads(artifact.read_text(encoding="utf-8"))["projections"]
        if row.get("date") == selected_date.isoformat()
    ]
    assert len(persisted_rows) == 4
    assert all(row.get("projection_generated_on") is not None for row in persisted_rows)
    assert all(not str(row.get("nhl_player_id", "")).startswith("stale-player") for row in persisted_rows)


def test_schedule_is_pulled_before_active_roster_generation(tmp_path) -> None:
    calls: list[str] = []
    selected_date = date(2026, 3, 24)
    schedule_provider = _RecordingScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032401",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
                    away_team="NY Rangers",
                    home_team="Boston Bruins",
                )
            ]
        },
        calls=calls,
    )
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(
        json.dumps(
            {
                "players": [
                    {"player_id": "8479323", "player_name": "Artemi Panarin", "active_team_name": "NY Rangers", "is_active_roster": True},
                    {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "Boston Bruins", "is_active_roster": True},
                ]
            }
        ),
        encoding="utf-8",
    )
    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=tmp_path / "projections.json",
        roster_repository=_RecordingRosterRepository(roster_path=roster_path, calls=calls),
    )

    provider.fetch_player_first_goal_projections(selected_date)

    assert calls
    assert calls[0] == "schedule"


def test_traded_player_uses_player_owned_first_goal_history_but_only_current_team_is_eligible(tmp_path) -> None:
    selected_date = date(2026, 3, 25)
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": "2026-03-20",
                "game_id": "old-game",
                "nhl_player_id": "8480820",
                "player_name": "Mikko Rantanen",
                "team_name": "Colorado Avalanche",
                "active_team_name": "Colorado Avalanche",
                "is_active_roster": True,
                "historical_season_first_goals": 9,
                "model_probability": 0.11,
            }
        ],
    )
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032501",
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
                    {"player_id": "8480820", "player_name": "Mikko Rantanen", "active_team_name": "Dallas Stars", "is_active_roster": True, "historical_season_first_goals": 1},
                    {"player_id": "8477492", "player_name": "Nathan MacKinnon", "active_team_name": "Colorado Avalanche", "is_active_roster": True, "historical_season_first_goals": 8},
                ]
            }
        ),
        encoding="utf-8",
    )
    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    rantanen = next(row for row in rows if row.nhl_player_id == "8480820")
    assert rantanen.roster_eligibility.active_team_name == "Dallas Stars"
    assert rantanen.projected_team_name == "Dallas Stars"
    assert rantanen.historical_production.season_first_goals == 9


def test_real_mode_projection_pipeline_order_is_schedule_then_roster_then_history_then_projection(tmp_path) -> None:
    calls: list[str] = []
    selected_date = date(2026, 3, 24)
    schedule_provider = _RecordingScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032401",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
                    away_team="NY Rangers",
                    home_team="Boston Bruins",
                )
            ]
        },
        calls=calls,
    )
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(
        json.dumps(
            {
                "players": [
                    {"player_id": "8479323", "player_name": "Artemi Panarin", "active_team_name": "NY Rangers", "is_active_roster": True},
                    {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "Boston Bruins", "is_active_roster": True},
                ]
            }
        ),
        encoding="utf-8",
    )
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])
    def _recording_history_loader(selected_date, eligible_player_ids, path):  # noqa: ANN001
        calls.append("history")
        from app.services.dev_projection_provider import _load_player_first_goal_history_from_artifact

        return _load_player_first_goal_history_from_artifact(selected_date=selected_date, eligible_player_ids=eligible_player_ids, path=path)

    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=_RecordingRosterRepository(roster_path=roster_path, calls=calls),
        history_loader=_recording_history_loader,
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    assert rows
    assert calls[0] == "schedule"
    assert "roster" in calls
    assert calls.index("history") > calls.index("roster")


def test_history_load_is_filtered_to_active_roster_eligible_player_ids(tmp_path) -> None:
    selected_date = date(2026, 3, 24)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032401",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
                    away_team="NY Rangers",
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
                    {"player_id": "8479323", "player_name": "Artemi Panarin", "active_team_name": "NY Rangers", "is_active_roster": True},
                    {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "Boston Bruins", "is_active_roster": True},
                    {"player_id": "inactive", "player_name": "Inactive Skater", "active_team_name": "NY Rangers", "is_active_roster": False},
                ]
            }
        ),
        encoding="utf-8",
    )
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {"date": "2026-03-20", "nhl_player_id": "8479323", "historical_season_first_goals": 8},
            {"date": "2026-03-20", "nhl_player_id": "8477956", "historical_season_first_goals": 9},
            {"date": "2026-03-20", "nhl_player_id": "old-not-eligible", "historical_season_first_goals": 99},
        ],
    )
    seen_ids: set[str] = set()

    def _capturing_history_loader(selected_date, eligible_player_ids, path):  # noqa: ANN001
        seen_ids.update(eligible_player_ids)
        from app.services.dev_projection_provider import _load_player_first_goal_history_from_artifact

        return _load_player_first_goal_history_from_artifact(selected_date=selected_date, eligible_player_ids=eligible_player_ids, path=path)

    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
        history_loader=_capturing_history_loader,
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    assert rows
    assert seen_ids == {"8479323", "8477956"}


def test_history_loader_receives_normalized_string_player_ids(tmp_path) -> None:
    selected_date = date(2026, 3, 24)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032401",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
                    away_team="NY Rangers",
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
                    {"player_id": 8479323, "player_name": "Artemi Panarin", "active_team_name": "NY Rangers", "is_active_roster": True},
                    {"player_id": " 8477956 ", "player_name": "David Pastrnak", "active_team_name": "Boston Bruins", "is_active_roster": True},
                ]
            }
        ),
        encoding="utf-8",
    )
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])
    seen_ids: set[str] = set()

    def _capturing_history_loader(_selected_date, eligible_player_ids, _path):  # noqa: ANN001
        seen_ids.update(eligible_player_ids)
        return {}

    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
        history_loader=_capturing_history_loader,
    )

    provider.fetch_player_first_goal_projections(selected_date)

    assert seen_ids == {"8479323", "8477956"}
    assert all(isinstance(player_id, str) for player_id in seen_ids)


def test_equal_history_players_use_ascending_name_tiebreaker_not_descending(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])
    selected_date = date(2026, 3, 25)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032501",
                    game_time=datetime(2026, 3, 25, 23, 0, tzinfo=timezone.utc),
                    away_team="Boston Bruins",
                    home_team="Buffalo Sabres",
                )
            ]
        }
    )
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(
        json.dumps(
            {
                "players": [
                    {"player_id": "a1", "player_name": "Viktor Arvidsson", "active_team_name": "Boston Bruins", "is_active_roster": True},
                    {"player_id": "a2", "player_name": "Brad Marchand", "active_team_name": "Boston Bruins", "is_active_roster": True},
                    {"player_id": "b1", "player_name": "Zach Metsa", "active_team_name": "Buffalo Sabres", "is_active_roster": True},
                    {"player_id": "b2", "player_name": "Tage Thompson", "active_team_name": "Buffalo Sabres", "is_active_roster": True},
                ]
            }
        ),
        encoding="utf-8",
    )
    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
        history_loader=lambda selected_date, eligible_player_ids, path: {},
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    bruins_rows = [row for row in rows if row.projected_team_name == "Boston Bruins"]
    sabres_rows = [row for row in rows if row.projected_team_name == "Buffalo Sabres"]
    assert bruins_rows[0].player_name == "Brad Marchand"
    assert sabres_rows[0].player_name == "Tage Thompson"


def test_candidate_filtering_excludes_goalies_and_non_current_team_players(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])
    selected_date = date(2026, 3, 24)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032401",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
                    away_team="NY Rangers",
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
                    {"player_id": "8479323", "player_name": "Artemi Panarin", "active_team_name": "NY Rangers", "is_active_roster": True, "position_code": "LW"},
                    {"player_id": "goalie-1", "player_name": "Igor Shesterkin", "active_team_name": "NY Rangers", "is_active_roster": True, "position_code": "G"},
                    {"player_id": "trade-1", "player_name": "Old Ranger", "active_team_name": "Chicago Blackhawks", "is_active_roster": True, "position_code": "C"},
                    {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "Boston Bruins", "is_active_roster": True, "position_code": "RW"},
                ]
            }
        ),
        encoding="utf-8",
    )
    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    assert {row.player_name for row in rows} == {"Artemi Panarin", "David Pastrnak"}
    assert all((row.roster_eligibility.position_code or "") != "G" for row in rows)


def test_first_goal_scoring_is_not_flat_and_uses_first_goal_history_weight(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])
    selected_date = date(2026, 3, 24)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032402",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
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
                    {"player_id": "p1", "player_name": "Alpha", "active_team_name": "Toronto Maple Leafs", "is_active_roster": True, "position_code": "C"},
                    {"player_id": "p2", "player_name": "Beta", "active_team_name": "Toronto Maple Leafs", "is_active_roster": True, "position_code": "LW"},
                    {"player_id": "p3", "player_name": "Gamma", "active_team_name": "Boston Bruins", "is_active_roster": True, "position_code": "RW"},
                    {"player_id": "p4", "player_name": "Delta", "active_team_name": "Boston Bruins", "is_active_roster": True, "position_code": "C"},
                ]
            }
        ),
        encoding="utf-8",
    )
    history = {
        "p1": PlayerHistoricalProduction(season_first_goals=8, season_total_goals=20, season_total_shots=180, season_games_played=60),
        "p2": PlayerHistoricalProduction(season_first_goals=0, season_total_goals=20, season_total_shots=180, season_games_played=60),
        "p3": PlayerHistoricalProduction(season_first_goals=6, season_total_goals=18, season_total_shots=150, season_games_played=60),
        "p4": PlayerHistoricalProduction(season_first_goals=1, season_total_goals=18, season_total_shots=150, season_games_played=60),
    }
    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
        history_loader=lambda _date, _ids, _path: history,
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    probs = [row.model_probability for row in rows]
    assert len(set(probs)) > 2
    alpha = next(row for row in rows if row.nhl_player_id == "p1")
    beta = next(row for row in rows if row.nhl_player_id == "p2")
    assert alpha.model_probability > beta.model_probability


def test_top_projected_players_are_plausible_forwards(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])
    selected_date = date(2026, 3, 24)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032403",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
                    away_team="Edmonton Oilers",
                    home_team="Toronto Maple Leafs",
                )
            ]
        }
    )
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(
        json.dumps(
            {
                "players": [
                    {"player_id": "mcd", "player_name": "Connor McDavid", "active_team_name": "Edmonton Oilers", "is_active_roster": True, "position_code": "C"},
                    {"player_id": "bouch", "player_name": "Evan Bouchard", "active_team_name": "Edmonton Oilers", "is_active_roster": True, "position_code": "D"},
                    {"player_id": "mat", "player_name": "Auston Matthews", "active_team_name": "Toronto Maple Leafs", "is_active_roster": True, "position_code": "C"},
                    {"player_id": "rielly", "player_name": "Morgan Rielly", "active_team_name": "Toronto Maple Leafs", "is_active_roster": True, "position_code": "D"},
                ]
            }
        ),
        encoding="utf-8",
    )
    history = {
        "mcd": PlayerHistoricalProduction(season_first_goals=7, season_total_goals=45, season_total_shots=260, season_games_played=70),
        "bouch": PlayerHistoricalProduction(season_first_goals=0, season_total_goals=14, season_total_shots=150, season_games_played=70),
        "mat": PlayerHistoricalProduction(season_first_goals=9, season_total_goals=50, season_total_shots=280, season_games_played=70),
        "rielly": PlayerHistoricalProduction(season_first_goals=0, season_total_goals=8, season_total_shots=120, season_games_played=70),
    }
    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
        history_loader=lambda _date, _ids, _path: history,
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    oilers_rows = [row for row in rows if row.projected_team_name == "Edmonton Oilers"]
    leafs_rows = [row for row in rows if row.projected_team_name == "Toronto Maple Leafs"]
    assert oilers_rows[0].player_name == "Connor McDavid"
    assert leafs_rows[0].player_name == "Auston Matthews"


def test_team_layer_probabilities_favor_stronger_offense_and_weaker_opponent_defense(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])
    selected_date = date(2026, 3, 24)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032404",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
                    away_team="High Octane",
                    home_team="Low Event",
                )
            ]
        }
    )
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(
        json.dumps(
            {
                "players": [
                    {"player_id": "ho-1", "player_name": "High One", "active_team_name": "High Octane", "is_active_roster": True, "position_code": "C"},
                    {"player_id": "ho-2", "player_name": "High Two", "active_team_name": "High Octane", "is_active_roster": True, "position_code": "LW"},
                    {"player_id": "le-1", "player_name": "Low One", "active_team_name": "Low Event", "is_active_roster": True, "position_code": "C"},
                    {"player_id": "le-2", "player_name": "Low Two", "active_team_name": "Low Event", "is_active_roster": True, "position_code": "LW"},
                ]
            }
        ),
        encoding="utf-8",
    )
    history = {
        "ho-1": PlayerHistoricalProduction(season_first_goals=8, season_total_goals=42, season_total_shots=250, season_games_played=70, season_first_period_goals=10),
        "ho-2": PlayerHistoricalProduction(season_first_goals=6, season_total_goals=34, season_total_shots=210, season_games_played=70, season_first_period_goals=8),
        "le-1": PlayerHistoricalProduction(season_first_goals=2, season_total_goals=14, season_total_shots=120, season_games_played=70, season_first_period_goals=2),
        "le-2": PlayerHistoricalProduction(season_first_goals=1, season_total_goals=9, season_total_shots=90, season_games_played=70, season_first_period_goals=1),
    }
    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
        history_loader=lambda _date, _ids, _path: history,
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    high_team_prob = sum(row.model_probability for row in rows if row.projected_team_name == "High Octane")
    low_team_prob = sum(row.model_probability for row in rows if row.projected_team_name == "Low Event")
    assert high_team_prob > low_team_prob


def test_recent_spike_does_not_overwhelm_stable_player_baseline(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])
    selected_date = date(2026, 3, 24)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032406",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
                    away_team="Balanced Team",
                    home_team="Opponent Team",
                )
            ]
        }
    )
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(
        json.dumps(
            {
                "players": [
                    {"player_id": "stable-1", "player_name": "Stable Producer", "active_team_name": "Balanced Team", "is_active_roster": True, "position_code": "C"},
                    {"player_id": "spike-1", "player_name": "Spike Producer", "active_team_name": "Balanced Team", "is_active_roster": True, "position_code": "LW"},
                    {"player_id": "opp-1", "player_name": "Opp One", "active_team_name": "Opponent Team", "is_active_roster": True, "position_code": "C"},
                    {"player_id": "opp-2", "player_name": "Opp Two", "active_team_name": "Opponent Team", "is_active_roster": True, "position_code": "LW"},
                ]
            }
        ),
        encoding="utf-8",
    )
    history = {
        "stable-1": PlayerHistoricalProduction(
            season_first_goals=7,
            season_total_goals=30,
            season_total_shots=210,
            season_games_played=70,
            recent_5_first_goals=1,
            recent_10_first_goals=1,
            recent_5_total_shots=18,
            recent_10_total_shots=34,
        ),
        "spike-1": PlayerHistoricalProduction(
            season_first_goals=1,
            season_total_goals=8,
            season_total_shots=65,
            season_games_played=70,
            recent_5_first_goals=3,
            recent_10_first_goals=4,
            recent_5_total_shots=7,
            recent_10_total_shots=12,
        ),
        "opp-1": PlayerHistoricalProduction(season_first_goals=3, season_total_goals=14, season_total_shots=120, season_games_played=70),
        "opp-2": PlayerHistoricalProduction(season_first_goals=2, season_total_goals=12, season_total_shots=100, season_games_played=70),
    }
    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
        history_loader=lambda _date, _ids, _path: history,
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)
    stable = next(row for row in rows if row.nhl_player_id == "stable-1")
    spike = next(row for row in rows if row.nhl_player_id == "spike-1")
    assert stable.model_probability > spike.model_probability


def test_recent_history_merge_uses_latest_values_instead_of_peak_max(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": "2026-03-20",
                "game_id": "g1",
                "nhl_player_id": "p1",
                "player_id": "p1",
                "player_name": "Player One",
                "team_name": "Team A",
                "active_team_name": "Team A",
                "is_active_roster": True,
                "model_probability": 0.1,
                "historical_season_first_goals": 6,
                "historical_season_games_played": 70,
                "historical_recent_5_first_goals": 4,
                "historical_recent_10_first_goals": 5,
            },
            {
                "date": "2026-03-24",
                "game_id": "g2",
                "nhl_player_id": "p1",
                "player_id": "p1",
                "player_name": "Player One",
                "team_name": "Team A",
                "active_team_name": "Team A",
                "is_active_roster": True,
                "model_probability": 0.1,
                "historical_season_first_goals": 6,
                "historical_season_games_played": 70,
                "historical_recent_5_first_goals": 1,
                "historical_recent_10_first_goals": 2,
            },
        ],
    )

    from app.services.dev_projection_provider import _load_player_first_goal_history_from_artifact

    history = _load_player_first_goal_history_from_artifact(
        selected_date=date(2026, 3, 25),
        eligible_player_ids={"p1"},
        path=artifact,
    )

    assert history["p1"].recent_5_first_goals == 1
    assert history["p1"].recent_10_first_goals == 2


def test_history_loader_accepts_first_goal_alias_fields(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": "2026-03-24",
                "game_id": "g1",
                "nhl_player_id": "p1",
                "player_id": "p1",
                "player_name": "Player One",
                "team_name": "Team A",
                "active_team_name": "Team A",
                "is_active_roster": True,
                "model_probability": 0.12,
                "first_goals_this_year": 5,
                "historical_season_games_played": 66,
            },
            {
                "date": "2026-03-23",
                "game_id": "g0",
                "nhl_player_id": "p2",
                "player_id": "p2",
                "player_name": "Player Two",
                "team_name": "Team A",
                "active_team_name": "Team A",
                "is_active_roster": True,
                "model_probability": 0.11,
                "season_first_goals": 4,
                "historical_season_games_played": 60,
            },
        ],
    )

    from app.services.dev_projection_provider import _load_player_first_goal_history_from_artifact

    history = _load_player_first_goal_history_from_artifact(
        selected_date=date(2026, 3, 25),
        eligible_player_ids={"p1", "p2"},
        path=artifact,
    )

    assert history["p1"].season_first_goals == 5
    assert history["p2"].season_first_goals == 4


def test_history_loader_accepts_total_goal_alias_fields(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": "2026-03-24",
                "game_id": "g1",
                "nhl_player_id": "8476459",
                "player_id": "8476459",
                "player_name": "Mika Zibanejad",
                "team_name": "NY Rangers",
                "active_team_name": "NY Rangers",
                "is_active_roster": True,
                "model_probability": 0.2,
                "goals_this_year": 29,
                "first_goals_this_year": 7,
                "historical_season_games_played": 74,
            }
        ],
    )

    from app.services.dev_projection_provider import _load_player_first_goal_history_from_artifact

    history = _load_player_first_goal_history_from_artifact(
        selected_date=date(2026, 3, 25),
        eligible_player_ids={"8476459"},
        path=artifact,
    )

    assert history["8476459"].season_total_goals == 29
    assert history["8476459"].season_first_goals == 7


def test_history_loader_merges_stored_first_goal_history_and_keeps_total_goals(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NHL_HISTORY_MAX_LIVE_REQUESTS_PER_GAMES", "0")
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": "2026-03-24",
                "game_id": "g1",
                "nhl_player_id": "8476459",
                "player_id": "8476459",
                "player_name": "Mika Zibanejad",
                "team_name": "NY Rangers",
                "active_team_name": "NY Rangers",
                "is_active_roster": True,
                "model_probability": 0.2,
                "goals_this_year": 29,
                "first_goals_this_year": 6,
                "historical_season_games_played": 74,
            }
        ],
    )
    with (
        patch("app.services.dev_projection_provider.refresh_incremental_first_goal_derived_data"),
        patch(
            "app.services.dev_projection_provider.load_stored_first_goal_derived_history",
            return_value={"8476459": PlayerHistoricalProduction(season_first_goals=7)},
        ),
    ):
        from app.services.dev_projection_provider import load_player_first_goal_history_from_nhl_api

        history = load_player_first_goal_history_from_nhl_api(
            selected_date=date(2026, 3, 25),
            eligible_player_ids={"8476459"},
            path=artifact,
        )

    assert history["8476459"].season_total_goals == 29
    assert history["8476459"].season_first_goals == 7


def test_history_loader_fetches_live_totals_when_cached_has_only_first_goal_data(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NHL_HISTORY_MAX_LIVE_REQUESTS_PER_GAMES", "10")
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])

    with (
        patch("app.services.dev_projection_provider.refresh_incremental_first_goal_derived_data"),
        patch(
            "app.services.dev_projection_provider.load_stored_first_goal_derived_history",
            return_value={"8476459": PlayerHistoricalProduction(season_first_goals=7)},
        ),
        patch(
            "app.services.dev_projection_provider.fetch_player_first_goal_history",
            return_value=PlayerHistoricalProduction(
                season_first_goals=2,
                season_total_goals=29,
                season_games_played=74,
            ),
        ) as fetch_mock,
    ):
        from app.services.dev_projection_provider import load_player_first_goal_history_from_nhl_api

        history = load_player_first_goal_history_from_nhl_api(
            selected_date=date(2026, 3, 25),
            eligible_player_ids={"8476459"},
            path=artifact,
        )

    fetch_mock.assert_called_once_with(player_id="8476459", selected_date=date(2026, 3, 25))
    assert history["8476459"].season_total_goals == 29
    # Preserve first-goal total from incremental derived data.
    assert history["8476459"].season_first_goals == 7


def test_projection_row_loader_accepts_first_goal_alias_fields(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": "2026-03-25",
                "game_id": "g1",
                "nhl_player_id": "p1",
                "player_id": "p1",
                "player_name": "Player One",
                "team_name": "Team A",
                "active_team_name": "Team A",
                "is_active_roster": True,
                "position_code": "C",
                "model_probability": 0.21,
                "first_goals_this_year": 3,
            },
            {
                "date": "2026-03-25",
                "game_id": "g1",
                "nhl_player_id": "p2",
                "player_id": "p2",
                "player_name": "Player Two",
                "team_name": "Team A",
                "active_team_name": "Team A",
                "is_active_roster": True,
                "position_code": "LW",
                "model_probability": 0.19,
                "season_first_goals": 2,
            },
        ],
    )

    from app.services.dev_projection_provider import _load_projection_rows_for_date_from_artifact

    rows = _load_projection_rows_for_date_from_artifact(artifact, date(2026, 3, 25))
    by_id = {row.nhl_player_id: row for row in rows}

    assert by_id["p1"].historical_production.season_first_goals == 3
    assert by_id["p2"].historical_production.season_first_goals == 2


def test_team_recent_form_is_dampened_and_cannot_dominate_team_probability(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])
    selected_date = date(2026, 3, 25)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032501",
                    game_time=datetime(2026, 3, 25, 23, 0, tzinfo=timezone.utc),
                    away_team="Stable Team",
                    home_team="Hot Team",
                )
            ]
        }
    )
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(
        json.dumps(
            {
                "players": [
                    {"player_id": "s1", "player_name": "Stable One", "active_team_name": "Stable Team", "is_active_roster": True, "position_code": "C"},
                    {"player_id": "s2", "player_name": "Stable Two", "active_team_name": "Stable Team", "is_active_roster": True, "position_code": "LW"},
                    {"player_id": "h1", "player_name": "Hot One", "active_team_name": "Hot Team", "is_active_roster": True, "position_code": "C"},
                    {"player_id": "h2", "player_name": "Hot Two", "active_team_name": "Hot Team", "is_active_roster": True, "position_code": "LW"},
                ]
            }
        ),
        encoding="utf-8",
    )
    history = {
        # stronger stable baseline
        "s1": PlayerHistoricalProduction(season_first_goals=6, season_total_goals=32, season_total_shots=220, season_games_played=70, recent_5_total_shots=8, recent_10_total_shots=16),
        "s2": PlayerHistoricalProduction(season_first_goals=5, season_total_goals=28, season_total_shots=200, season_games_played=70, recent_5_total_shots=8, recent_10_total_shots=16),
        # weaker baseline but inflated recent activity
        "h1": PlayerHistoricalProduction(season_first_goals=2, season_total_goals=14, season_total_shots=110, season_games_played=70, recent_5_total_shots=35, recent_10_total_shots=60, recent_5_first_goals=3, recent_10_first_goals=4),
        "h2": PlayerHistoricalProduction(season_first_goals=1, season_total_goals=11, season_total_shots=95, season_games_played=70, recent_5_total_shots=30, recent_10_total_shots=55, recent_5_first_goals=2, recent_10_first_goals=3),
    }
    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
        history_loader=lambda _date, _ids, _path: history,
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)
    stable_team_prob = sum(row.model_probability for row in rows if row.projected_team_name == "Stable Team")
    hot_team_prob = sum(row.model_probability for row in rows if row.projected_team_name == "Hot Team")

    assert stable_team_prob > hot_team_prob


def test_recent_forms_are_hard_clamped_before_scoring() -> None:
    from app.services.dev_projection_provider import _player_model_features

    features = _player_model_features(
        PlayerHistoricalProduction(
            season_games_played=10,
            season_total_shots=20,
            recent_5_total_shots=500,
            recent_10_total_shots=1000,
            recent_5_first_period_shots=200,
            recent_10_first_period_shots=400,
            recent_5_first_goals=20,
            recent_10_first_goals=40,
            recent_5_total_goals=30,
            recent_10_total_goals=60,
        )
    )

    assert features.recent_process_form <= 2.0
    assert features.recent_outcome_form <= 0.8


def test_recent_adjustments_are_added_after_stable_multiplier() -> None:
    from app.services.dev_projection_provider import _DEFAULT_TEMPLATE, _player_first_goal_score
    from app.services.dev_projection_provider import _PlayerModelFeatures

    base_features = _PlayerModelFeatures(
        games_played=82.0,
        first_goals_per_game=0.06,
        goals_per_game=0.30,
        first_period_goals_per_game=0.08,
        first_period_shots_per_game=0.20,
        shots_per_game=3.0,
        recent_process_form=0.0,
        recent_outcome_form=0.0,
        stability_score=1.0,
        offensive_tier_multiplier=1.8,
    )
    hot_recent = _PlayerModelFeatures(
        games_played=82.0,
        first_goals_per_game=0.06,
        goals_per_game=0.30,
        first_period_goals_per_game=0.08,
        first_period_shots_per_game=0.20,
        shots_per_game=3.0,
        recent_process_form=2.0,
        recent_outcome_form=0.8,
        stability_score=1.0,
        offensive_tier_multiplier=1.8,
    )

    base_score = _player_first_goal_score(base_features, _DEFAULT_TEMPLATE)
    hot_score = _player_first_goal_score(hot_recent, _DEFAULT_TEMPLATE)

    expected_recent_lift = (
        _DEFAULT_TEMPLATE.player_recent_process_weight * hot_recent.recent_process_form
        + _DEFAULT_TEMPLATE.player_recent_outcome_weight * hot_recent.recent_outcome_form
    )
    assert hot_score - base_score == pytest.approx(expected_recent_lift, abs=1e-9)


def test_low_end_zero_first_goal_profile_gets_downgraded_vs_elite_before_after() -> None:
    from app.services.dev_projection_provider import _DEFAULT_TEMPLATE, _player_first_goal_score
    from app.services.dev_projection_provider import _PlayerModelFeatures

    eyssimont_like = _PlayerModelFeatures(
        games_played=70.0,
        first_goals_per_game=0.0,
        goals_per_game=0.14,
        first_period_goals_per_game=0.0,
        first_period_shots_per_game=0.15,
        shots_per_game=1.6,
        recent_process_form=1.4,
        recent_outcome_form=0.1,
        stability_score=1.0,
        offensive_tier_multiplier=0.95,
    )
    elite_scorer = _PlayerModelFeatures(
        games_played=70.0,
        first_goals_per_game=0.08,
        goals_per_game=0.50,
        first_period_goals_per_game=0.06,
        first_period_shots_per_game=0.40,
        shots_per_game=4.3,
        recent_process_form=1.0,
        recent_outcome_form=0.3,
        stability_score=1.0,
        offensive_tier_multiplier=1.55,
    )

    def _legacy_score(features: _PlayerModelFeatures) -> float:
        stable_baseline = (
            _DEFAULT_TEMPLATE.player_first_goal_weight * features.first_goals_per_game
            + _DEFAULT_TEMPLATE.player_total_goal_weight * features.goals_per_game
            + _DEFAULT_TEMPLATE.player_first_period_goal_weight * features.first_period_goals_per_game
            + _DEFAULT_TEMPLATE.player_first_period_shot_weight * features.first_period_shots_per_game
            + _DEFAULT_TEMPLATE.player_shots_per_game_weight * features.shots_per_game
        )
        recent_process_adjustment = _DEFAULT_TEMPLATE.player_recent_process_weight * features.recent_process_form
        recent_outcome_adjustment = _DEFAULT_TEMPLATE.player_recent_outcome_weight * features.recent_outcome_form
        return max(
            (stable_baseline * features.offensive_tier_multiplier) + recent_process_adjustment + recent_outcome_adjustment,
            _DEFAULT_TEMPLATE.min_player_share_floor,
        )

    before_scores = {
        "michael_eyssimont_like": _legacy_score(eyssimont_like),
        "elite_scorer": _legacy_score(elite_scorer),
    }
    after_scores = {
        "michael_eyssimont_like": _player_first_goal_score(eyssimont_like, _DEFAULT_TEMPLATE),
        "elite_scorer": _player_first_goal_score(elite_scorer, _DEFAULT_TEMPLATE),
    }

    assert after_scores["elite_scorer"] > after_scores["michael_eyssimont_like"]
    assert after_scores["michael_eyssimont_like"] < before_scores["michael_eyssimont_like"]
    assert (after_scores["elite_scorer"] / after_scores["michael_eyssimont_like"]) > (
        before_scores["elite_scorer"] / before_scores["michael_eyssimont_like"]
    )


def test_no_placeholder_rows_emitted_in_real_mode(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])
    selected_date = date(2026, 3, 24)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032405",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
                    away_team="NY Rangers",
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
                    {"player_id": "8479323", "player_name": "Artemi Panarin", "active_team_name": "NY Rangers", "is_active_roster": True, "position_code": "LW"},
                    {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "Boston Bruins", "is_active_roster": True, "position_code": "RW"},
                ]
            }
        ),
        encoding="utf-8",
    )
    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
        enable_dev_fallback=False,
        history_loader=lambda _date, _ids, _path: {},
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    assert rows
    assert all(not row.nhl_player_id.startswith("dev-") for row in rows)
    assert all("Skater" not in row.player_name for row in rows)


def test_history_loader_fetches_live_history_by_default_when_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("NHL_HISTORY_MAX_LIVE_REQUESTS_PER_GAMES", raising=False)
    monkeypatch.delenv("NHL_HISTORY_MAX_LIVE_REQUESTS_PER_GAME", raising=False)

    calls: list[str] = []

    def _fake_fetch(player_id: str, selected_date: date) -> PlayerHistoricalProduction:
        calls.append(player_id)
        return PlayerHistoricalProduction(season_first_goals=1.0, season_games_played=10.0)

    with (
        patch("app.services.dev_projection_provider.refresh_incremental_first_goal_derived_data"),
        patch("app.services.dev_projection_provider.load_stored_first_goal_derived_history", return_value={}),
        patch("app.services.dev_projection_provider.fetch_player_first_goal_history", side_effect=_fake_fetch),
    ):
        from app.services.dev_projection_provider import load_player_first_goal_history_from_nhl_api

        history = load_player_first_goal_history_from_nhl_api(
            selected_date=date(2026, 3, 25),
            eligible_player_ids={"8477956", "8478402"},
            path=tmp_path / "missing-artifact.json",
        )

    assert set(calls) == {"8477956", "8478402"}
    assert history["8477956"].season_first_goals == 1.0


def test_history_loader_prefers_stored_incremental_first_goal_totals(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("NHL_HISTORY_MAX_LIVE_REQUESTS_PER_GAMES", raising=False)
    monkeypatch.delenv("NHL_HISTORY_MAX_LIVE_REQUESTS_PER_GAME", raising=False)

    with (
        patch("app.services.dev_projection_provider.refresh_incremental_first_goal_derived_data"),
        patch(
            "app.services.dev_projection_provider.load_stored_first_goal_derived_history",
            return_value={
                "8477956": PlayerHistoricalProduction(season_first_goals=4.0, season_first_period_goals=6.0),
            },
        ),
        patch(
            "app.services.dev_projection_provider.fetch_player_first_goal_history",
            return_value=PlayerHistoricalProduction(season_first_goals=1.0, season_first_period_goals=2.0, season_games_played=10.0),
        ),
    ):
        from app.services.dev_projection_provider import load_player_first_goal_history_from_nhl_api

        history = load_player_first_goal_history_from_nhl_api(
            selected_date=date(2026, 3, 25),
            eligible_player_ids={"8477956"},
            path=tmp_path / "missing-artifact.json",
        )

    assert history["8477956"].season_first_goals == 4.0
    assert history["8477956"].season_first_period_goals == 6.0


def test_real_mode_common_team_names_generate_rows_with_nhl_api_rosters(tmp_path, monkeypatch) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])
    selected_date = date(2026, 3, 24)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032401",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
                    away_team="Rangers",
                    home_team="Bruins",
                )
            ]
        }
    )

    def _fake_roster(team_abbrev: str):
        if team_abbrev == "NYR":
            return [
                type("P", (), {"player_id": "8479323", "player_name": "Artemi Panarin", "active_team_name": "NYR"})(),
            ]
        if team_abbrev == "BOS":
            return [
                type("P", (), {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "BOS"})(),
            ]
        return []

    monkeypatch.setattr("app.services.dev_projection_provider.fetch_team_roster_current", _fake_roster)

    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=NhlApiActiveRosterRepository(),
        history_loader=lambda _date, eligible_ids, _path: {
            player_id: PlayerHistoricalProduction(season_first_goals=3.0, season_games_played=60.0)
            for player_id in eligible_ids
        },
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    assert {row.player_name for row in rows} == {"Artemi Panarin", "David Pastrnak"}
    assert all(not row.nhl_player_id.startswith("dev-") for row in rows)


def test_single_letter_wing_positions_are_not_filtered_out_of_candidate_pool(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])
    selected_date = date(2026, 3, 24)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032409",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
                    away_team="Boston Bruins",
                    home_team="Tampa Bay Lightning",
                )
            ]
        }
    )
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(
        json.dumps(
            {
                "players": [
                    {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "Boston Bruins", "is_active_roster": True, "position_code": "R"},
                    {"player_id": "8473419", "player_name": "Brad Marchand", "active_team_name": "Boston Bruins", "is_active_roster": True, "position_code": "L"},
                    {"player_id": "8480801", "player_name": "Pavel Zacha", "active_team_name": "Boston Bruins", "is_active_roster": True, "position_code": "C"},
                    {"player_id": "8480880", "player_name": "Michael Eyssimont", "active_team_name": "Tampa Bay Lightning", "is_active_roster": True, "position_code": "R"},
                    {"player_id": "8476453", "player_name": "Andrei Vasilevskiy", "active_team_name": "Tampa Bay Lightning", "is_active_roster": True, "position_code": "G"},
                ]
            }
        ),
        encoding="utf-8",
    )
    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
        history_loader=lambda _date, _ids, _path: {},
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)
    names = {row.player_name for row in rows}

    assert "David Pastrnak" in names
    assert "Brad Marchand" in names
    assert "Pavel Zacha" in names
    assert "Andrei Vasilevskiy" not in names


def test_candidate_pool_includes_defensemen_not_only_forwards(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    _write_artifact(artifact, [])
    selected_date = date(2026, 3, 24)
    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032410",
                    game_time=datetime(2026, 3, 24, 23, 30, tzinfo=timezone.utc),
                    away_team="Boston Bruins",
                    home_team="NY Rangers",
                )
            ]
        }
    )
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(
        json.dumps(
            {
                "players": [
                    {"player_id": "8479323", "player_name": "Artemi Panarin", "active_team_name": "NY Rangers", "is_active_roster": True, "position_code": "LW"},
                    {"player_id": "8478402", "player_name": "Adam Fox", "active_team_name": "NY Rangers", "is_active_roster": True, "position_code": "D"},
                    {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "Boston Bruins", "is_active_roster": True, "position_code": "RW"},
                ]
            }
        ),
        encoding="utf-8",
    )
    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
        history_loader=lambda _date, _ids, _path: {},
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)
    names = {row.player_name for row in rows}

    assert "Adam Fox" in names


def test_nhl_api_roster_repository_drops_players_with_mismatched_active_team(monkeypatch) -> None:
    def _fake_roster(team_abbrev: str):
        if team_abbrev == "BOS":
            return [
                type("P", (), {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "BOS", "position_code": "R"})(),
                type("P", (), {"player_id": "8473419", "player_name": "Brad Marchand", "active_team_name": "FLA", "position_code": "L"})(),
            ]
        if team_abbrev == "FLA":
            return [
                type("P", (), {"player_id": "8473419", "player_name": "Brad Marchand", "active_team_name": "FLA", "position_code": "L"})(),
            ]
        return []

    monkeypatch.setattr("app.services.dev_projection_provider.fetch_team_roster_current", _fake_roster)

    repository = NhlApiActiveRosterRepository()

    bruins_players = {player.player_name for player in repository.active_players_for_team("Boston Bruins")}
    panthers_players = {player.player_name for player in repository.active_players_for_team("Florida Panthers")}

    assert "David Pastrnak" in bruins_players
    assert "Brad Marchand" not in bruins_players
    assert "Brad Marchand" in panthers_players


def test_today_always_regenerates_and_ignores_cached_projection_rows(tmp_path) -> None:
    selected_date = date.today()
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": selected_date.isoformat(),
                "game_id": "2026032501",
                "nhl_player_id": "stale-player",
                "player_name": "Stale Cached Player",
                "team_name": "Boston Bruins",
                "active_team_name": "Boston Bruins",
                "is_active_roster": True,
                "model_probability": 0.19,
            }
        ],
    )

    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032501",
                    game_time=datetime(2026, 3, 25, 23, 0, tzinfo=timezone.utc),
                    away_team="Boston Bruins",
                    home_team="Florida Panthers",
                )
            ]
        }
    )
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(
        json.dumps(
            {
                "players": [
                    {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "Boston Bruins", "is_active_roster": True, "position_code": "R"},
                    {"player_id": "8473419", "player_name": "Brad Marchand", "active_team_name": "Florida Panthers", "is_active_roster": True, "position_code": "L"},
                ]
            }
        ),
        encoding="utf-8",
    )
    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
        history_loader=lambda _date, _ids, _path: {},
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    names = {row.player_name for row in rows}
    assert "Stale Cached Player" not in names
    assert "David Pastrnak" in names
    assert "Brad Marchand" in names


def test_past_date_reuses_cached_projection_rows(tmp_path) -> None:
    selected_date = date(2026, 3, 24)
    artifact = tmp_path / "projections.json"
    _write_artifact(
        artifact,
        [
            {
                "date": selected_date.isoformat(),
                "game_id": "2026032401",
                "nhl_player_id": "cached-player",
                "player_name": "Cached Past Player",
                "team_name": "Boston Bruins",
                "active_team_name": "Boston Bruins",
                "is_active_roster": True,
                "position_code": "RW",
                "historical_season_total_goals": 30,
                "historical_season_total_shots": 210,
                "model_probability": 0.21,
            },
            {
                "date": selected_date.isoformat(),
                "game_id": "2026032401",
                "nhl_player_id": "cached-player-2",
                "player_name": "Cached Past Player 2",
                "team_name": "Florida Panthers",
                "active_team_name": "Florida Panthers",
                "is_active_roster": True,
                "position_code": "C",
                "historical_season_total_goals": 24,
                "historical_season_total_shots": 180,
                "model_probability": 0.18,
            },
        ],
    )
    calls: list[str] = []

    class _RosterRepo(ActiveRosterRepository):
        def active_players_for_team(self, team_name: str):
            calls.append(team_name)
            return super().active_players_for_team(team_name)

    schedule_provider = _StaticScheduleProvider(
        {
            selected_date: [
                GameSummary(
                    game_id="2026032401",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
                    away_team="Boston Bruins",
                    home_team="Florida Panthers",
                )
            ]
        }
    )
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(json.dumps({"players": []}), encoding="utf-8")
    provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact,
        roster_repository=_RosterRepo(roster_path=roster_path),
        history_loader=lambda _date, _ids, _path: {},
    )

    rows = provider.fetch_player_first_goal_projections(selected_date)

    assert {row.player_name for row in rows} == {"Cached Past Player", "Cached Past Player 2"}
    assert calls == []
