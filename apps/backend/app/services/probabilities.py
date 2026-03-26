from __future__ import annotations

import math

from app.services.interfaces import PlayerHistoricalProduction


def estimate_anytime_goal_probability(history: PlayerHistoricalProduction) -> float | None:
    """Estimate probability a skater scores at least one goal in a game."""

    season_rate = _safe_rate(history.season_total_goals, history.season_games_played)
    recent_10_rate = _safe_rate(history.recent_10_total_goals, 10.0)
    recent_5_rate = _safe_rate(history.recent_5_total_goals, 5.0)

    expected_goals_per_game: float | None = None
    if season_rate is not None and recent_10_rate is not None:
        expected_goals_per_game = 0.75 * season_rate + 0.25 * recent_10_rate
    elif season_rate is not None:
        expected_goals_per_game = season_rate
    elif recent_10_rate is not None:
        expected_goals_per_game = recent_10_rate

    if expected_goals_per_game is None and recent_5_rate is not None:
        expected_goals_per_game = recent_5_rate

    if expected_goals_per_game is None:
        shots_per_game = _safe_rate(history.season_total_shots, history.season_games_played)
        if shots_per_game is not None:
            # League-average conversion prior for sparse-goal histories.
            expected_goals_per_game = shots_per_game * 0.095

    if expected_goals_per_game is None:
        return None

    # Poisson probability of >=1 goal: 1 - exp(-lambda).
    probability = 1.0 - math.exp(-max(expected_goals_per_game, 0.0))
    return min(max(probability, 0.001), 0.98)


def _safe_rate(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return max(float(numerator), 0.0) / float(denominator)
