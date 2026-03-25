import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.services.nhl_api_data import (
    backfill_current_regular_season_first_goal_derived_data,
    fetch_player_first_goal_history,
    fetch_team_roster_current,
    load_stored_first_goal_derived_history,
    refresh_incremental_first_goal_derived_data,
    team_abbrev_for_name,
)


def test_fetch_team_roster_current_uses_nhl_roster_endpoint() -> None:
    seen: dict[str, str] = {}

    def _fake_fetch_json(*, url: str, headers=None, timeout_seconds=10, opener=None):  # noqa: ANN001
        seen["url"] = url
        return {
            "forwards": [
                {
                    "id": 8478402,
                    "firstName": {"default": "Mitch"},
                    "lastName": {"default": "Marner"},
                    "currentTeamAbbrev": "TOR",
                    "positionCode": "RW",
                }
            ]
        }

    with patch("app.services.nhl_api_data.fetch_json", side_effect=_fake_fetch_json):
        rows = fetch_team_roster_current("TOR")

    assert seen["url"] == "https://api-web.nhle.com/v1/roster/TOR/current"
    assert rows[0].player_id == "8478402"
    assert rows[0].position_code == "RW"


def test_fetch_player_first_goal_history_uses_nhl_player_game_log_endpoint() -> None:
    seen: dict[str, str] = {}

    def _fake_fetch_json(*, url: str, headers=None, timeout_seconds=10, opener=None):  # noqa: ANN001
        seen["url"] = url
        return {
            "gameLog": [
                {"firstGoals": 1},
                {"firstGoal": True, "goals": 2, "shots": 6, "firstPeriodGoals": 1},
                {"isFirstGoal": True, "goals": 1, "shots": 3},
                {},
            ]
        }

    with patch("app.services.nhl_api_data.fetch_json", side_effect=_fake_fetch_json):
        history = fetch_player_first_goal_history("8478402", date(2026, 3, 24))

    assert seen["url"] == "https://api-web.nhle.com/v1/player/8478402/game-log/20252026/2"
    assert history.season_first_goals == 3.0
    assert history.season_games_played == 4.0
    assert history.season_total_goals == 3.0
    assert history.season_total_shots == 9.0
    assert history.season_first_period_goals == 1.0


def test_team_abbrev_for_name_resolves_schedule_common_names() -> None:
    assert team_abbrev_for_name("Rangers") == "NYR"
    assert team_abbrev_for_name("Bruins") == "BOS"
    assert team_abbrev_for_name("Canadiens") == "MTL"


def test_refresh_incremental_first_goal_derived_data_tracks_processed_games_without_double_counting(tmp_path: Path) -> None:
    artifact = tmp_path / "projections.json"
    artifact.write_text(json.dumps({"schema_version": 1, "projections": []}), encoding="utf-8")

    fetch_calls: list[str] = []

    def _fake_fetch_json(*, url: str, headers=None, timeout_seconds=10, opener=None):  # noqa: ANN001
        fetch_calls.append(url)
        if "/schedule/" in url:
            return {
                "games": [
                    {"id": 2026032401, "gameState": "OFF"},
                    {"id": 2026032402, "gameState": "LIVE"},
                ]
            }
        if "2026032401" in url and "/play-by-play" in url:
            return {
                "plays": [
                    {
                        "typeDescKey": "goal",
                        "sortOrder": 10,
                        "periodDescriptor": {"number": 1},
                        "details": {"scoringPlayerId": 8478402},
                    },
                    {
                        "typeDescKey": "goal",
                        "sortOrder": 12,
                        "periodDescriptor": {"number": 1},
                        "details": {"scoringPlayerId": 8477956},
                    },
                    {
                        "typeDescKey": "goal",
                        "sortOrder": 20,
                        "periodDescriptor": {"number": 2},
                        "details": {"scoringPlayerId": 8478402},
                    },
                ]
            }
        return {"games": []}

    with patch("app.services.nhl_api_data.fetch_json", side_effect=_fake_fetch_json):
        refresh_incremental_first_goal_derived_data(selected_date=date(2026, 3, 25), artifact_path=artifact)
        refresh_incremental_first_goal_derived_data(selected_date=date(2026, 3, 25), artifact_path=artifact)

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    season_store = payload["historical_first_goal_tracking"]["20252026"]
    assert season_store["processed_game_ids"] == ["2026032401"]
    assert season_store["player_first_goal_totals"]["8478402"] == 1.0
    assert season_store["player_first_period_goal_totals"]["8478402"] == 1.0
    assert season_store["player_first_period_goal_totals"]["8477956"] == 1.0
    assert sum(1 for call in fetch_calls if "2026032401/play-by-play" in call) == 1


def test_load_stored_first_goal_derived_history_returns_player_history(tmp_path: Path) -> None:
    artifact = tmp_path / "projections.json"
    artifact.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "projections": [],
                "historical_first_goal_tracking": {
                    "20252026": {
                        "processed_game_ids": ["2026032401"],
                        "player_first_goal_totals": {"8478402": 2},
                        "player_first_period_goal_totals": {"8478402": 5, "8477956": 1},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    history = load_stored_first_goal_derived_history(
        selected_date=date(2026, 3, 25),
        eligible_player_ids={"8478402", "8477956", "8471234"},
        artifact_path=artifact,
    )

    assert history["8478402"].season_first_goals == 2.0
    assert history["8478402"].season_first_period_goals == 5.0
    assert history["8477956"].season_first_goals is None
    assert history["8477956"].season_first_period_goals == 1.0
    assert "8471234" not in history


def test_backfill_current_regular_season_first_goal_derived_data_filters_to_regular_season_and_is_idempotent(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "projections.json"
    artifact.write_text(json.dumps({"schema_version": 1, "projections": []}), encoding="utf-8")

    pbp_fetches: list[str] = []

    def _fake_fetch_json(*, url: str, headers=None, timeout_seconds=10, opener=None):  # noqa: ANN001
        if "/schedule/" in url:
            if url.endswith("/2025-09-01"):
                return {
                    "games": [
                        {"id": 2025090101, "season": 20252026, "gameType": 1, "gameState": "OFF"},
                    ]
                }
            if url.endswith("/2025-09-02"):
                return {
                    "games": [
                        {"id": 2025090201, "season": 20252026, "gameType": 2, "gameState": "OFF"},
                    ]
                }
            if url.endswith("/2025-09-03"):
                return {
                    "games": [
                        {"id": 2025090301, "season": 20252026, "gameType": 3, "gameState": "OFF"},
                    ]
                }
            if url.endswith("/2025-09-04"):
                return {
                    "games": [
                        {"id": 2025090401, "season": 20242025, "gameType": 2, "gameState": "OFF"},
                    ]
                }
            return {"games": []}
        if "/play-by-play" in url:
            pbp_fetches.append(url)
            return {
                "plays": [
                    {
                        "typeDescKey": "goal",
                        "sortOrder": 10,
                        "periodDescriptor": {"number": 1},
                        "details": {"scoringPlayerId": 8478402},
                    },
                    {
                        "typeDescKey": "goal",
                        "sortOrder": 20,
                        "periodDescriptor": {"number": 1},
                        "details": {"scoringPlayerId": 8477956},
                    },
                ]
            }
        return {"games": []}

    with patch("app.services.nhl_api_data.fetch_json", side_effect=_fake_fetch_json):
        result_1 = backfill_current_regular_season_first_goal_derived_data(
            selected_date=date(2025, 9, 4),
            artifact_path=artifact,
        )
        result_2 = backfill_current_regular_season_first_goal_derived_data(
            selected_date=date(2025, 9, 4),
            artifact_path=artifact,
        )

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    season_store = payload["historical_first_goal_tracking"]["20252026"]
    assert season_store["processed_game_ids"] == ["2025090201"]
    assert season_store["player_first_goal_totals"] == {"8478402": 1.0}
    assert season_store["player_first_period_goal_totals"] == {"8478402": 1.0, "8477956": 1.0}
    assert result_1["newly_processed_game_ids"] == ["2025090201"]
    assert result_2["newly_processed_game_ids"] == []
    assert result_1["failed_game_ids"] == []
    assert result_2["failed_game_ids"] == []
    assert sum(1 for value in pbp_fetches if "2025090201/play-by-play" in value) == 1


def test_backfill_current_regular_season_first_goal_derived_data_continues_when_single_game_fails(
    tmp_path: Path, capsys
) -> None:
    artifact = tmp_path / "projections.json"
    artifact.write_text(json.dumps({"schema_version": 1, "projections": []}), encoding="utf-8")

    def _fake_fetch_json(*, url: str, headers=None, timeout_seconds=10, opener=None):  # noqa: ANN001
        if "/schedule/" in url and url.endswith("/2025-09-01"):
            return {
                "games": [
                    {"id": 2025090101, "season": 20252026, "gameType": 2, "gameState": "OFF"},
                    {"id": 2025090102, "season": 20252026, "gameType": 2, "gameState": "OFF"},
                ]
            }
        if "/play-by-play" in url and "2025090101" in url:
            raise TimeoutError("simulated timeout")
        if "/play-by-play" in url and "2025090102" in url:
            return {
                "plays": [
                    {
                        "typeDescKey": "goal",
                        "sortOrder": 10,
                        "periodDescriptor": {"number": 1},
                        "details": {"scoringPlayerId": 8478402},
                    }
                ]
            }
        return {"games": []}

    with patch("app.services.nhl_api_data.fetch_json", side_effect=_fake_fetch_json):
        result = backfill_current_regular_season_first_goal_derived_data(
            selected_date=date(2025, 9, 1),
            artifact_path=artifact,
        )

    captured = capsys.readouterr()
    assert "Backfill schedule scan progress: scanned_dates=1 current_date=2025-09-01" in captured.out
    assert "Backfill candidates prepared: total_candidates=2" in captured.out
    assert "Backfill game start: 1/2 game_id=2025090101 processed=0 skipped=0 failed=0" in captured.out
    assert "Backfill game start: 2/2 game_id=2025090102 processed=0 skipped=0 failed=1" in captured.out
    assert "Backfill game failed: game_id=2025090101 error=simulated timeout" in captured.out
    assert "Backfill progress: 2/2 game_id=2025090102 processed=1 skipped=0 failed=1" in captured.out
    assert "Backfill summary: total_candidates=2 processed=1 skipped=0 failed=1" in captured.out

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    season_store = payload["historical_first_goal_tracking"]["20252026"]
    assert season_store["processed_game_ids"] == ["2025090102"]
    assert result["newly_processed_game_ids"] == ["2025090102"]
    assert result["failed_game_ids"] == ["2025090101"]
