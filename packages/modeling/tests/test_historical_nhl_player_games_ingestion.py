from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch

from quick_netters_modeling.historical.nhl_player_games_ingestion import ingest_historical_player_games


def test_ingest_historical_player_games_aligns_to_games_and_excludes_preseason(tmp_path: Path) -> None:
    games_csv = tmp_path / "processed" / "historical_games" / "nhl_games.csv"
    output_csv = tmp_path / "processed" / "historical_player_games" / "nhl_player_games.csv"
    raw_root = tmp_path / "raw" / "nhl_gamecenter"

    games_csv.parent.mkdir(parents=True, exist_ok=True)
    with games_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "season",
                "game_id",
                "game_date",
                "game_type",
                "game_type_code",
                "home_team",
                "away_team",
            ],
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    "season": "20252026",
                    "game_id": "200",
                    "game_date": "2025-10-20",
                    "game_type": "regular_season",
                    "game_type_code": "2",
                    "home_team": "Leafs",
                    "away_team": "Canadiens",
                },
                {
                    "season": "20252026",
                    "game_id": "201",
                    "game_date": "2025-10-21",
                    "game_type": "preseason",
                    "game_type_code": "1",
                    "home_team": "Leafs",
                    "away_team": "Senators",
                },
            ]
        )

    boxscore_payload = {
        "awayTeam": {"starter": 88, "goalies": [88]},
        "homeTeam": {"starter": 99, "goalies": [99]},
        "playerByGameStats": {
            "awayTeam": {
                "forwards": [
                    {
                        "playerId": 10,
                        "name": {"default": "Away Skater"},
                        "goals": 1,
                        "shots": 4,
                        "toi": "17:35",
                        "powerPlayToi": "03:22",
                        "points": 2,
                    }
                ],
                "goalies": [
                    {
                        "playerId": 88,
                        "name": {"default": "Away Goalie"},
                    }
                ],
            },
            "homeTeam": {
                "forwards": [
                    {
                        "playerId": 20,
                        "name": {"default": "Home Skater"},
                        "goals": 0,
                        "shots": 2,
                        "toi": "16:15",
                        "powerPlayToi": "01:10",
                        "points": 1,
                    }
                ],
                "goalies": [
                    {
                        "playerId": 99,
                        "name": {"default": "Home Goalie"},
                    }
                ],
            },
        },
    }

    calls: list[str] = []

    def _fake_fetch_json(*, url: str, timeout_seconds: int):  # noqa: ANN001
        calls.append(url)
        assert timeout_seconds > 0
        return boxscore_payload

    with patch("quick_netters_modeling.historical.nhl_player_games_ingestion.fetch_json", side_effect=_fake_fetch_json):
        result_one = ingest_historical_player_games(
            games_csv_path=games_csv,
            output_csv_path=output_csv,
            raw_snapshot_root=raw_root,
            season_keys=["20252026"],
        )
        result_two = ingest_historical_player_games(
            games_csv_path=games_csv,
            output_csv_path=output_csv,
            raw_snapshot_root=raw_root,
            season_keys=["20252026"],
        )

    assert calls == ["https://api-web.nhle.com/v1/gamecenter/200/boxscore"] * 2

    with output_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert {(row["season"], row["game_id"]) for row in rows} == {("20252026", "200")}
    away_row = next(row for row in rows if row["player_id"] == "10")
    home_row = next(row for row in rows if row["player_id"] == "20")

    assert away_row["team"] == "Canadiens"
    assert away_row["opponent"] == "Leafs"
    assert away_row["home_or_away"] == "away"
    assert away_row["opposing_goalie_id"] == "99"
    assert away_row["opposing_goalie_name"] == "Home Goalie"

    assert home_row["team"] == "Leafs"
    assert home_row["opponent"] == "Canadiens"
    assert home_row["home_or_away"] == "home"
    assert home_row["opposing_goalie_id"] == "88"
    assert home_row["opposing_goalie_name"] == "Away Goalie"

    assert result_one["games_scanned"] == 1
    assert result_one["total_rows"] == 4
    assert result_two["upserts"] == 0
