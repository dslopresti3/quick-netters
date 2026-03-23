from __future__ import annotations

import argparse
from pathlib import Path

from .config import SeasonConfig
from .pipeline import HistoricalDataPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Quick Netters historical data pipeline")
    parser.add_argument("--data-root", default="packages/modeling/data", help="Root data directory")
    parser.add_argument("--current-season", required=True, type=int, help="Current season year")

    args = parser.parse_args()

    config = SeasonConfig(current_season=args.current_season)
    pipeline = HistoricalDataPipeline(data_root=Path(args.data_root), season_config=config)
    outputs = pipeline.run()

    for table_name, paths in outputs.items():
        for path in paths:
            print(f"[{table_name}] {path}")


if __name__ == "__main__":
    main()
