from __future__ import annotations

import argparse
from datetime import date, datetime
import json

from app.services.anytime_calibration import AnytimeCalibrationConfig, summarize_anytime_calibration
from app.services.provider_wiring import build_provider_registry_from_env


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Anytime model calibration diagnostics for one slate.")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--outlier-probability-threshold", type=float, default=0.42)
    parser.add_argument("--matchup-boost-threshold", type=float, default=0.02)
    parser.add_argument("--small-sample-games-threshold", type=float, default=12.0)
    parser.add_argument("--small-sample-probability-threshold", type=float, default=0.20)
    parser.add_argument("--top-players-limit", type=int, default=15)
    parser.add_argument("--json", action="store_true", help="Print raw JSON payload")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    selected_date = _parse_date(args.date)
    providers = build_provider_registry_from_env()
    projections = providers.projection_provider.fetch_player_first_goal_projections(selected_date)

    payload = summarize_anytime_calibration(
        projections,
        config=AnytimeCalibrationConfig(
            outlier_probability_threshold=args.outlier_probability_threshold,
            matchup_boost_threshold=args.matchup_boost_threshold,
            small_sample_games_threshold=args.small_sample_games_threshold,
            small_sample_probability_threshold=args.small_sample_probability_threshold,
            top_players_limit=args.top_players_limit,
        ),
    )

    if args.json:
        print(json.dumps(payload, indent=2))
        return

    print("=== Anytime Calibration Report ===")
    print(f"date={selected_date.isoformat()} candidates={payload['candidate_count']}")
    print(f"probability_distribution={json.dumps(payload['probability_distribution'])}")
    print(f"top_projected_players={len(payload['top_projected_players'])}")
    print(f"suspicious_outliers={len(payload['suspicious_outliers'])}")
    print(f"large_matchup_boost_players={len(payload['large_matchup_boost_players'])}")
    print(f"small_sample_high_probability_players={len(payload['small_sample_high_probability_players'])}")


if __name__ == "__main__":
    main()
