from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

from app.services.provider_wiring import build_provider_registry_from_env
from app.services.recommendation_performance import (
    append_slate_rows,
    load_performance_rows,
    resolve_outcomes_for_date,
    summarize_performance,
)

DEFAULT_TRACKING_PATH = Path("apps/backend/app/data/performance/recommendation_performance.json")


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _record(args: argparse.Namespace) -> None:
    selected_date = _parse_date(args.date)
    providers = build_provider_registry_from_env()
    rows = providers.recommendation_service._build_ranked_recommendations(selected_date)  # noqa: SLF001
    stored = append_slate_rows(args.path, selected_date, rows)
    print(f"stored_rows={stored} date={selected_date.isoformat()} path={args.path}")


def _resolve(args: argparse.Namespace) -> None:
    selected_date = _parse_date(args.date)
    updated = resolve_outcomes_for_date(args.path, selected_date)
    print(f"updated_rows={updated} date={selected_date.isoformat()} path={args.path}")


def _report(args: argparse.Namespace) -> None:
    rows = load_performance_rows(args.path)
    if args.date_from:
        rows = [row for row in rows if row.date >= args.date_from]
    if args.date_to:
        rows = [row for row in rows if row.date <= args.date_to]
    summary = summarize_performance(rows)

    print("=== Recommendation Performance Summary ===")
    print(f"N={summary['total_rows']}")
    print(f"top1_hit_rate={summary['top_hit_rates']['top1']}")
    print(f"top3_hit_rate={summary['top_hit_rates']['top3']}")
    print(f"top5_hit_rate={summary['top_hit_rates']['top5']}")
    print(f"avg_implied_probability={summary['avg_implied_probability']}")
    print(f"actual_hit_rate={summary['actual_hit_rate']}")
    print(f"avg_ev_per_unit={summary['avg_ev_per_unit']}")
    print(f"avg_realized_return_per_unit={summary['avg_realized_return_per_unit']}")
    print(f"cumulative_ev={summary['cumulative_ev']}")
    print(f"cumulative_realized_return={summary['cumulative_realized_return']}")
    print(f"roi={summary['roi']}")
    print("--- Model Bias ---")
    print(
        f"predicted_avg={summary['bias']['predicted_avg']} "
        f"actual_avg={summary['bias']['actual_avg']} "
        f"delta={summary['bias']['delta']} "
        f"label={summary['bias']['label']}"
    )
    print("--- Rolling hit rates ---")
    for row in summary["rolling_hit_rates"]:
        print(
            f"{row['date']}: top1={row['top1_hit_rate']:.4f} "
            f"top3={row['top3_hit_rate']:.4f} top5={row['top5_hit_rate']:.4f}"
        )
    print("--- Calibration ---")
    for row in summary["calibration"]:
        print(
            f"{row['bucket']}: count={row['count']} "
            f"pred={row['avg_predicted_probability']} actual={row['actual_hit_rate']}"
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track and report recommendation performance over time.")
    parser.add_argument("--path", type=Path, default=DEFAULT_TRACKING_PATH)
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record", help="Store a recommendation slate snapshot.")
    record.add_argument("--date", required=True, help="YYYY-MM-DD")
    record.set_defaults(func=_record)

    resolve = sub.add_parser("resolve", help="Resolve first-goal outcomes for a recorded date.")
    resolve.add_argument("--date", required=True, help="YYYY-MM-DD")
    resolve.set_defaults(func=_resolve)

    report = sub.add_parser("report", help="Print summary metrics and calibration table.")
    report.add_argument("--date-from", dest="date_from")
    report.add_argument("--date-to", dest="date_to")
    report.set_defaults(func=_report)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.date_from:
        args.date_from = _parse_date(args.date_from).isoformat()
    if args.date_to:
        args.date_to = _parse_date(args.date_to).isoformat()
    args.func(args)


if __name__ == "__main__":
    main()
