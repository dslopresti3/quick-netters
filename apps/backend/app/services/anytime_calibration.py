from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.interfaces import PlayerProjectionCandidate
from app.services.probabilities import AnytimeProbabilityDiagnostics, estimate_anytime_goal_probability_diagnostics


@dataclass(frozen=True)
class AnytimeCalibrationConfig:
    outlier_probability_threshold: float = 0.42
    matchup_boost_threshold: float = 0.02
    small_sample_games_threshold: float = 12.0
    small_sample_probability_threshold: float = 0.20
    top_players_limit: int = 15


def summarize_anytime_calibration(
    projections: list[PlayerProjectionCandidate],
    *,
    config: AnytimeCalibrationConfig | None = None,
) -> dict[str, Any]:
    calibration = config or AnytimeCalibrationConfig()

    rows: list[tuple[PlayerProjectionCandidate, AnytimeProbabilityDiagnostics]] = []
    for projection in projections:
        diagnostics = estimate_anytime_goal_probability_diagnostics(projection.historical_production)
        if diagnostics is None:
            continue
        rows.append((projection, diagnostics))

    probabilities = [diagnostics.anytime_probability for _, diagnostics in rows]
    matchup_boost_rows = [
        _calibration_row(projection, diagnostics)
        for projection, diagnostics in rows
        if diagnostics.matchup_history_contribution >= calibration.matchup_boost_threshold
    ]
    suspicious_outliers = [
        _calibration_row(projection, diagnostics)
        for projection, diagnostics in rows
        if diagnostics.anytime_probability >= calibration.outlier_probability_threshold
    ]
    small_sample_high_prob = [
        _calibration_row(projection, diagnostics)
        for projection, diagnostics in rows
        if float(projection.historical_production.season_games_played or 0.0) < calibration.small_sample_games_threshold
        and diagnostics.anytime_probability >= calibration.small_sample_probability_threshold
    ]

    top_projected = sorted(
        (_calibration_row(projection, diagnostics) for projection, diagnostics in rows),
        key=lambda row: row["anytime_probability"],
        reverse=True,
    )[: calibration.top_players_limit]

    return {
        "candidate_count": len(rows),
        "probability_distribution": _distribution_summary(probabilities),
        "top_projected_players": top_projected,
        "suspicious_outliers": suspicious_outliers,
        "large_matchup_boost_players": matchup_boost_rows,
        "small_sample_high_probability_players": small_sample_high_prob,
    }


def _distribution_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "p25": None, "median": None, "p75": None, "max": None, "mean": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p25": _quantile(ordered, 0.25),
        "median": _quantile(ordered, 0.5),
        "p75": _quantile(ordered, 0.75),
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
    }


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    remainder = index - lower
    return values[lower] + ((values[upper] - values[lower]) * remainder)


def _calibration_row(projection: PlayerProjectionCandidate, diagnostics: AnytimeProbabilityDiagnostics) -> dict[str, Any]:
    return {
        "game_id": projection.game_id,
        "player_id": projection.nhl_player_id,
        "player_name": projection.player_name,
        "team": projection.projected_team_name,
        "season_games_played": float(projection.historical_production.season_games_played or 0.0),
        "anytime_probability": diagnostics.anytime_probability,
        "expected_scoring_intensity": diagnostics.expected_scoring_intensity,
        "recent_form_contribution": diagnostics.recent_form_contribution,
        "season_baseline_contribution": diagnostics.season_baseline_contribution,
        "usage_opportunity_contribution": diagnostics.usage_opportunity_contribution,
        "matchup_history_contribution": diagnostics.matchup_history_contribution,
        "stabilization_effect": diagnostics.stabilization_effect,
    }
