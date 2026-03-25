from datetime import date
from pathlib import Path

from app.services.recommendation_performance import (
    RecommendationPerformanceRow,
    append_slate_rows,
    load_performance_rows,
    save_performance_rows,
    summarize_performance,
)


def test_summary_metrics_and_calibration_are_computed() -> None:
    rows = [
        RecommendationPerformanceRow("2026-03-20", 1, "g1", "p1", "Player 1", 0.24, 500, 70.0, 0.6, 1),
        RecommendationPerformanceRow("2026-03-20", 2, "g1", "p2", "Player 2", 0.14, 900, 60.0, 0.6, 0),
        RecommendationPerformanceRow("2026-03-21", 1, "g2", "p3", "Player 3", 0.18, 700, 65.0, 0.6, 0),
        RecommendationPerformanceRow("2026-03-21", 2, "g2", "p4", "Player 4", 0.08, 1200, 55.0, 0.55, 1),
    ]
    summary = summarize_performance(rows)

    assert summary["total_rows"] == 4
    assert summary["top_hit_rates"]["top1"] == 0.5
    assert summary["top_hit_rates"]["top3"] == 1.0
    assert summary["top_hit_rates"]["top5"] == 1.0
    assert summary["avg_implied_probability"] is not None
    assert summary["actual_hit_rate"] == 0.5
    assert summary["avg_ev_per_unit"] is not None
    assert summary["avg_realized_return_per_unit"] is not None
    assert summary["cumulative_ev"] is not None
    assert summary["cumulative_realized_return"] is not None
    assert summary["roi"] is not None
    assert summary["rolling_hit_rates"]
    assert summary["bias"]["label"] in {"overestimating", "underestimating", "well_calibrated"}
    assert summary["calibration"]
    assert any(bucket["bucket"] == "0.05-0.10" for bucket in summary["calibration"])


def test_append_slate_rows_upserts_by_date_game_player_key(tmp_path: Path) -> None:
    path = tmp_path / "perf.json"
    existing = [
        RecommendationPerformanceRow("2026-03-24", 1, "g1", "p1", "Player 1", 0.21, 500, 50.0, 0.6, None),
        RecommendationPerformanceRow("2026-03-25", 1, "g2", "p2", "Player 2", 0.19, 700, 55.0, 0.6, None),
    ]
    save_performance_rows(path, existing)

    from app.api.schemas import Recommendation
    from datetime import datetime, timezone

    new_recs = [
        Recommendation(
            game_id="g2",
            game_time=datetime.now(timezone.utc),
            away_team="A",
            home_team="B",
            player_id="p3",
            player_name="Player 3",
            model_probability=0.2,
            fair_odds=400,
            market_odds=800,
            edge=0.02,
            ev=0.1,
            confidence_score=0.6,
            recommendation_score=60.0,
        )
    ]
    inserted = append_slate_rows(path, date(2026, 3, 25), new_recs)
    rows = load_performance_rows(path)

    assert inserted == 1
    assert len(rows) == 3
    assert any(row.player_id == "p1" for row in rows)
    assert any(row.player_id == "p2" for row in rows)
    assert any(row.player_id == "p3" for row in rows)
