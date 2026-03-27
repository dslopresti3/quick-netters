from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch

from quick_netters_modeling.historical.nhl_games_ingestion import (
    _normalize_schedule_games,
    ingest_historical_games,
)


def test_normalize_schedule_games_includes_regular_and_postseason_only() -> None:
    rows = _normalize_schedule_games(
        season_key="20252026",
        endpoint="https://api-web.nhle.com/v1/schedule-season/20252026",
        ingested_at_utc="2026-03-27T00:00:00+00:00",
        games=[
            {
                "id": 1,
                "season": 20252026,
                "startTimeUTC": "2025-10-10T00:00:00Z",
                "gameType": 1,
                "awayTeam": {"commonName": {"default": "Canadiens"}, "score": 1},
                "homeTeam": {"commonName": {"default": "Leafs"}, "score": 2},
            },
            {
                "id": 2,
                "season": 20252026,
                "startTimeUTC": "2025-10-11T00:00:00Z",
                "gameType": 2,
                "gameState": "FINAL",
                "awayTeam": {"commonName": {"default": "Rangers"}, "score": 3},
                "homeTeam": {"commonName": {"default": "Devils"}, "score": 4},
            },
            {
                "id": 3,
                "season": 20252026,
                "startTimeUTC": "2026-04-20T00:00:00Z",
                "gameType": 3,
                "gameState": "OFF",
                "awayTeam": {"commonName": {"default": "Oilers"}, "score": 2},
                "homeTeam": {"commonName": {"default": "Kings"}, "score": 1},
            },
        ],
    )

    assert [row.game_id for row in rows] == ["2", "3"]
    assert [row.game_type for row in rows] == ["regular_season", "postseason"]
    assert all(row.game_type_code in {2, 3} for row in rows)


def test_ingest_historical_games_merges_by_season_game_id_and_excludes_preseason(tmp_path: Path) -> None:
    output_csv = tmp_path / "processed" / "historical_games" / "nhl_games.csv"
    raw_root = tmp_path / "raw" / "nhl_schedule"

    payload = {
        "games": [
            {
                "id": 10,
                "season": 20252026,
                "startTimeUTC": "2025-10-12T00:00:00Z",
                "gameType": 2,
                "gameState": "FINAL",
                "awayTeam": {"commonName": {"default": "Team A"}, "score": 1},
                "homeTeam": {"commonName": {"default": "Team B"}, "score": 2},
            },
            {
                "id": 11,
                "season": 20252026,
                "startTimeUTC": "2025-10-13T00:00:00Z",
                "gameType": 1,
                "gameState": "OFF",
                "awayTeam": {"commonName": {"default": "Team C"}, "score": 1},
                "homeTeam": {"commonName": {"default": "Team D"}, "score": 2},
            },
            {
                "id": 12,
                "season": 20252026,
                "startTimeUTC": "2026-05-02T00:00:00Z",
                "gameType": 3,
                "gameState": "OFF",
                "awayTeam": {"commonName": {"default": "Team E"}, "score": 5},
                "homeTeam": {"commonName": {"default": "Team F"}, "score": 6},
            },
        ]
    }

    def _fake_fetch_json(*, url: str, headers=None, timeout_seconds=10, opener=None):  # noqa: ANN001
        assert url.endswith("/schedule-season/20252026")
        return payload

    with patch("quick_netters_modeling.historical.nhl_games_ingestion.fetch_json", side_effect=_fake_fetch_json):
        result_one = ingest_historical_games(
            output_csv_path=output_csv,
            raw_snapshot_root=raw_root,
            season_keys=["20252026"],
        )
        result_two = ingest_historical_games(
            output_csv_path=output_csv,
            raw_snapshot_root=raw_root,
            season_keys=["20252026"],
        )

    with output_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert [row["game_id"] for row in rows] == ["10", "12"]
    assert {row["game_type"] for row in rows} == {"regular_season", "postseason"}
    assert all(row["game_type_code"] in {"2", "3"} for row in rows)
    assert result_one["excluded_preseason_games"] == 1
    assert result_one["included_regular_season_games"] == 1
    assert result_one["included_postseason_games"] == 1
    assert result_two["upserts"] == 0
