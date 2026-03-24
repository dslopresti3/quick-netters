import json
from datetime import date, datetime, timezone

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

