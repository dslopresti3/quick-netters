#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from quick_netters_modeling.historical.nhl_games_ingestion import (
    discover_supported_season_keys,
    ingest_historical_games,
    season_keys_from_args,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill historical NHL games for modeling")
    parser.add_argument("--data-root", default="packages/modeling/data", help="Root data directory")
    parser.add_argument("--season", help="Single season key, e.g. 20252026")
    parser.add_argument("--season-start", type=int, help="Start year for season range, e.g. 2019")
    parser.add_argument("--season-end", type=int, help="End year for season range, e.g. 2025")
    parser.add_argument("--all-supported", action="store_true", help="Auto-discover and backfill all supported seasons")
    parser.add_argument("--probe-start-year", type=int, default=1917, help="Discovery lower bound year")
    args = parser.parse_args()

    data_root = Path(args.data_root)
    output_csv_path = data_root / "processed" / "historical_games" / "nhl_games.csv"
    raw_snapshot_root = data_root / "raw" / "nhl_schedule"

    if args.all_supported:
        current_year = datetime.now(timezone.utc).year
        season_keys = discover_supported_season_keys(start_year=args.probe_start_year, end_year=current_year)
    else:
        season_keys = season_keys_from_args(
            season=args.season,
            season_start=args.season_start,
            season_end=args.season_end,
        )

    result = ingest_historical_games(
        output_csv_path=output_csv_path,
        raw_snapshot_root=raw_snapshot_root,
        season_keys=season_keys,
    )

    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
