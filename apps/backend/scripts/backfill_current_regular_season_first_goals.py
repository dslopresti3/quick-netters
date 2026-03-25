from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from app.services.nhl_api_data import backfill_current_regular_season_first_goal_derived_data
from app.services.projection_store import build_real_projection_data_source_from_env


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-time backfill for active NHL regular season first-goal derived tracking."
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Selected ISO date used to resolve active season (default: today).",
    )
    parser.add_argument(
        "--artifact-path",
        default=None,
        help="Optional override for projection artifact path (defaults to BACKEND_PROJECTION_ARTIFACT_PATH or app default).",
    )
    args = parser.parse_args()

    selected_date = date.fromisoformat(args.date)
    artifact_path = (
        Path(args.artifact_path).expanduser().resolve()
        if isinstance(args.artifact_path, str) and args.artifact_path.strip()
        else build_real_projection_data_source_from_env().artifact_path
    )

    result = backfill_current_regular_season_first_goal_derived_data(
        selected_date=selected_date,
        artifact_path=artifact_path,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
