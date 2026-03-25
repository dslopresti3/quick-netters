from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.api.schemas import Recommendation
from app.services.odds import american_to_implied_probability, expected_value_per_unit


@dataclass(frozen=True)
class RecommendationPerformanceRow:
    date: str
    rank: int
    game_id: str
    player_id: str
    player_name: str
    model_probability: float
    market_odds: int
    recommendation_score: float
    confidence_score: float
    outcome_scored_first: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "rank": self.rank,
            "game_id": self.game_id,
            "player_id": self.player_id,
            "player_name": self.player_name,
            "model_probability": self.model_probability,
            "market_odds": self.market_odds,
            "recommendation_score": self.recommendation_score,
            "confidence_score": self.confidence_score,
            "outcome_scored_first": self.outcome_scored_first,
        }


def append_slate_rows(path: Path, selected_date: date, recommendations: list[Recommendation]) -> int:
    if not recommendations:
        return 0
    rows = load_performance_rows(path)
    slate_key = selected_date.isoformat()
    by_key: dict[tuple[str, str, str], RecommendationPerformanceRow] = {
        (row.date, row.game_id, row.player_id): row for row in rows
    }
    for idx, rec in enumerate(recommendations, start=1):
        key = (slate_key, rec.game_id, rec.player_id)
        existing = by_key.get(key)
        by_key[key] = RecommendationPerformanceRow(
            date=slate_key,
            rank=idx,
            game_id=rec.game_id,
            player_id=rec.player_id,
            player_name=rec.player_name,
            model_probability=rec.model_probability,
            market_odds=rec.market_odds,
            recommendation_score=float(rec.recommendation_score or 0.0),
            confidence_score=float(rec.confidence_score or 0.0),
            outcome_scored_first=(existing.outcome_scored_first if existing is not None else None),
        )
    save_performance_rows(path, list(by_key.values()))
    return len(recommendations)


def load_performance_rows(path: Path) -> list[RecommendationPerformanceRow]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_rows = payload.get("rows", [])
    if not isinstance(raw_rows, list):
        return []
    rows: list[RecommendationPerformanceRow] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        try:
            rows.append(
                RecommendationPerformanceRow(
                    date=str(raw["date"]),
                    rank=int(raw["rank"]),
                    game_id=str(raw["game_id"]),
                    player_id=str(raw["player_id"]),
                    player_name=str(raw["player_name"]),
                    model_probability=float(raw["model_probability"]),
                    market_odds=int(raw["market_odds"]),
                    recommendation_score=float(raw["recommendation_score"]),
                    confidence_score=float(raw["confidence_score"]),
                    outcome_scored_first=(
                        None if raw.get("outcome_scored_first") is None else int(raw.get("outcome_scored_first"))
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return rows


def save_performance_rows(path: Path, rows: list[RecommendationPerformanceRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = [row.to_dict() for row in sorted(rows, key=lambda r: (r.date, r.rank, r.player_id))]
    path.write_text(json.dumps({"schema_version": 1, "rows": serialized}, indent=2) + "\n", encoding="utf-8")


def resolve_outcomes_for_date(path: Path, selected_date: date) -> int:
    rows = load_performance_rows(path)
    if not rows:
        return 0
    slate_key = selected_date.isoformat()
    game_first_scorer_cache: dict[str, str | None] = {}
    updated: list[RecommendationPerformanceRow] = []
    changes = 0
    for row in rows:
        if row.date != slate_key:
            updated.append(row)
            continue
        if row.game_id not in game_first_scorer_cache:
            game_first_scorer_cache[row.game_id] = fetch_first_goal_scorer_player_id(row.game_id)
        scorer_id = game_first_scorer_cache[row.game_id]
        outcome = 1 if scorer_id is not None and scorer_id == row.player_id else 0
        if row.outcome_scored_first != outcome:
            changes += 1
        updated.append(
            RecommendationPerformanceRow(
                date=row.date,
                rank=row.rank,
                game_id=row.game_id,
                player_id=row.player_id,
                player_name=row.player_name,
                model_probability=row.model_probability,
                market_odds=row.market_odds,
                recommendation_score=row.recommendation_score,
                confidence_score=row.confidence_score,
                outcome_scored_first=outcome,
            )
        )
    save_performance_rows(path, updated)
    return changes


def fetch_first_goal_scorer_player_id(game_id: str) -> str | None:
    url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
    request = Request(url, headers={"User-Agent": "quick-netters/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError):
        return None

    plays = payload.get("plays", [])
    if not isinstance(plays, list):
        return None
    goal_events = [play for play in plays if isinstance(play, dict) and play.get("typeDescKey") == "goal"]
    if not goal_events:
        return None
    first_goal = min(goal_events, key=lambda play: int(play.get("sortOrder", 10**9)))
    details = first_goal.get("details", {})
    scorer_id = details.get("scoringPlayerId")
    if scorer_id is None:
        return None
    return str(scorer_id).strip()


def summarize_performance(rows: list[RecommendationPerformanceRow]) -> dict[str, Any]:
    resolved = [row for row in rows if row.outcome_scored_first is not None]
    if not resolved:
        return {
            "total_rows": 0,
            "top_hit_rates": {"top1": None, "top3": None, "top5": None},
            "avg_implied_probability": None,
            "actual_hit_rate": None,
            "avg_ev_per_unit": None,
            "avg_realized_return_per_unit": None,
            "calibration": [],
            "rolling_hit_rates": [],
            "cumulative_ev": None,
            "cumulative_realized_return": None,
            "roi": None,
            "bias": {"predicted_avg": None, "actual_avg": None, "delta": None, "label": "insufficient_data"},
            "rank_bucket_performance": [],
            "market_odds_bucket_performance": [],
            "edge_quality": [],
        }

    by_date: dict[str, list[RecommendationPerformanceRow]] = {}
    for row in resolved:
        by_date.setdefault(row.date, []).append(row)
    for slate_rows in by_date.values():
        slate_rows.sort(key=lambda row: row.rank)

    top_hit_rates: dict[str, float | None] = {}
    for top_n, label in ((1, "top1"), (3, "top3"), (5, "top5")):
        hits = 0
        total = 0
        for slate_rows in by_date.values():
            candidates = [row for row in slate_rows if row.rank <= top_n]
            if not candidates:
                continue
            total += 1
            hits += 1 if any((row.outcome_scored_first or 0) == 1 for row in candidates) else 0
        top_hit_rates[label] = (hits / total) if total else None

    implied_values: list[float] = []
    ev_values: list[float] = []
    realized_values: list[float] = []
    for row in resolved:
        implied = american_to_implied_probability(row.market_odds)
        if implied is not None:
            implied_values.append(implied)
        ev = expected_value_per_unit(row.model_probability, row.market_odds)
        if ev is not None:
            ev_values.append(ev)
        realized_values.append(_realized_return_per_unit(row.market_odds, outcome=row.outcome_scored_first or 0))

    calibration = _build_calibration_table(resolved)
    rolling_hit_rates = _build_rolling_hit_rates(by_date)
    actual_hit_rate = sum((row.outcome_scored_first or 0) for row in resolved) / len(resolved)
    avg_predicted = sum(row.model_probability for row in resolved) / len(resolved)
    delta = avg_predicted - actual_hit_rate
    bias_label = "overestimating" if delta > 0.01 else ("underestimating" if delta < -0.01 else "well_calibrated")
    return {
        "total_rows": len(resolved),
        "top_hit_rates": top_hit_rates,
        "avg_implied_probability": (sum(implied_values) / len(implied_values)) if implied_values else None,
        "actual_hit_rate": actual_hit_rate,
        "avg_ev_per_unit": (sum(ev_values) / len(ev_values)) if ev_values else None,
        "avg_realized_return_per_unit": (sum(realized_values) / len(realized_values)) if realized_values else None,
        "cumulative_ev": sum(ev_values) if ev_values else None,
        "cumulative_realized_return": sum(realized_values) if realized_values else None,
        "roi": (sum(realized_values) / len(realized_values)) if realized_values else None,
        "calibration": calibration,
        "rolling_hit_rates": rolling_hit_rates,
        "bias": {
            "predicted_avg": avg_predicted,
            "actual_avg": actual_hit_rate,
            "delta": delta,
            "label": bias_label,
        },
        "rank_bucket_performance": _bucket_performance_by_rank(resolved),
        "market_odds_bucket_performance": _bucket_performance_by_market_odds(resolved),
        "edge_quality": _bucket_performance_by_edge(resolved),
    }


def _build_calibration_table(rows: list[RecommendationPerformanceRow]) -> list[dict[str, Any]]:
    buckets: dict[tuple[float, float], list[RecommendationPerformanceRow]] = {}
    for row in rows:
        bucket_size = 0.05
        start = min(0.95, max(0.0, (int(row.model_probability / bucket_size) * bucket_size)))
        end = min(1.0, start + bucket_size)
        buckets.setdefault((start, end), []).append(row)

    table: list[dict[str, Any]] = []
    for (start, end), bucket_rows in sorted(buckets.items()):
        avg_pred = sum(row.model_probability for row in bucket_rows) / len(bucket_rows)
        actual = sum((row.outcome_scored_first or 0) for row in bucket_rows) / len(bucket_rows)
        table.append(
            {
                "bucket": f"{start:.2f}-{end:.2f}",
                "count": len(bucket_rows),
                "avg_predicted_probability": round(avg_pred, 4),
                "actual_hit_rate": round(actual, 4),
            }
        )
    return table


def _build_rolling_hit_rates(by_date: dict[str, list[RecommendationPerformanceRow]]) -> list[dict[str, Any]]:
    running_top1_hits = 0
    running_top3_hits = 0
    running_top5_hits = 0
    seen = 0
    out: list[dict[str, Any]] = []
    for slate_date in sorted(by_date.keys()):
        rows = sorted(by_date[slate_date], key=lambda row: row.rank)
        seen += 1
        running_top1_hits += 1 if any((row.outcome_scored_first or 0) == 1 for row in rows if row.rank <= 1) else 0
        running_top3_hits += 1 if any((row.outcome_scored_first or 0) == 1 for row in rows if row.rank <= 3) else 0
        running_top5_hits += 1 if any((row.outcome_scored_first or 0) == 1 for row in rows if row.rank <= 5) else 0
        out.append(
            {
                "date": slate_date,
                "top1_hit_rate": running_top1_hits / seen,
                "top3_hit_rate": running_top3_hits / seen,
                "top5_hit_rate": running_top5_hits / seen,
            }
        )
    return out


def _bucket_performance_by_rank(rows: list[RecommendationPerformanceRow]) -> list[dict[str, Any]]:
    rank_buckets = [
        ("rank_1", lambda rank: rank == 1),
        ("rank_2_3", lambda rank: 2 <= rank <= 3),
        ("rank_4_5", lambda rank: 4 <= rank <= 5),
        ("rank_6_10", lambda rank: 6 <= rank <= 10),
    ]
    return [_performance_row(label, [row for row in rows if predicate(row.rank)]) for label, predicate in rank_buckets]


def _bucket_performance_by_market_odds(rows: list[RecommendationPerformanceRow]) -> list[dict[str, Any]]:
    odds_buckets = [
        ("<=+500", lambda odds: odds <= 500),
        ("+501_to_+1000", lambda odds: 501 <= odds <= 1000),
        ("+1001_to_+1500", lambda odds: 1001 <= odds <= 1500),
        ("+1501_to_+2000", lambda odds: 1501 <= odds <= 2000),
        ("+2001_plus", lambda odds: odds >= 2001),
    ]
    return [_performance_row(label, [row for row in rows if predicate(row.market_odds)]) for label, predicate in odds_buckets]


def _bucket_performance_by_edge(rows: list[RecommendationPerformanceRow]) -> list[dict[str, Any]]:
    def edge(row: RecommendationPerformanceRow) -> float:
        implied = american_to_implied_probability(row.market_odds)
        if implied is None:
            return 0.0
        return row.model_probability - implied

    edge_buckets = [
        ("0.00-0.03", lambda value: 0.00 <= value < 0.03),
        ("0.03-0.06", lambda value: 0.03 <= value < 0.06),
        ("0.06-0.10", lambda value: 0.06 <= value < 0.10),
        ("0.10_plus", lambda value: value >= 0.10),
    ]
    out = []
    for label, predicate in edge_buckets:
        bucket_rows = [row for row in rows if predicate(edge(row))]
        out.append(_performance_row(label, bucket_rows))
    return out


def _performance_row(bucket: str, rows: list[RecommendationPerformanceRow]) -> dict[str, Any]:
    if not rows:
        return {
            "bucket": bucket,
            "count": 0,
            "hit_rate": None,
            "avg_model_probability": None,
            "avg_implied_probability": None,
            "avg_ev": None,
            "realized_return": None,
            "roi": None,
        }

    implied_values = [american_to_implied_probability(row.market_odds) for row in rows]
    implied_values = [value for value in implied_values if value is not None]
    ev_values = [expected_value_per_unit(row.model_probability, row.market_odds) for row in rows]
    ev_values = [value for value in ev_values if value is not None]
    realized = [_realized_return_per_unit(row.market_odds, outcome=row.outcome_scored_first or 0) for row in rows]
    return {
        "bucket": bucket,
        "count": len(rows),
        "hit_rate": sum((row.outcome_scored_first or 0) for row in rows) / len(rows),
        "avg_model_probability": sum(row.model_probability for row in rows) / len(rows),
        "avg_implied_probability": (sum(implied_values) / len(implied_values)) if implied_values else None,
        "avg_ev": (sum(ev_values) / len(ev_values)) if ev_values else None,
        "realized_return": sum(realized),
        "roi": sum(realized) / len(rows),
    }


def _realized_return_per_unit(market_odds: int, outcome: int) -> float:
    if outcome == 0:
        return -1.0
    if market_odds > 0:
        return market_odds / 100.0
    return 100.0 / abs(market_odds)
