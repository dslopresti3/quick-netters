from __future__ import annotations

import math

from app.services.interfaces import PlayerHistoricalProduction


def estimate_anytime_goal_probability(history: PlayerHistoricalProduction) -> float | None:
    """Estimate anytime probability via intensity -> Poisson conversion."""

    games = max(float(history.season_games_played or 0.0), 0.0)
    season_goals_rate = _safe_rate(history.season_total_goals, games)
    season_shots_rate = _safe_rate(history.season_total_shots, games)
    recent_10_goals_rate = _safe_rate(history.recent_10_total_goals, min(games, 10.0))
    recent_5_goals_rate = _safe_rate(history.recent_5_total_goals, min(games, 5.0))
    recent_10_shots_rate = _safe_rate(history.recent_10_total_shots, min(games, 10.0))
    recent_5_shots_rate = _safe_rate(history.recent_5_total_shots, min(games, 5.0))

    projected_goals_rate = _first_present(
        history.projected_goals_per_game,
        _blend_rates((recent_5_goals_rate, 0.55), (recent_10_goals_rate, 0.30), (season_goals_rate, 0.15)),
        season_goals_rate,
    )
    projected_shots_rate = _first_present(
        history.projected_shots_per_game,
        _blend_rates((recent_5_shots_rate, 0.55), (recent_10_shots_rate, 0.30), (season_shots_rate, 0.15)),
        season_shots_rate,
    )
    if projected_goals_rate is None and projected_shots_rate is None:
        return None

    # Season baseline with explicit shrinkage for sparse samples.
    season_prior = 0.14
    season_conf = min(1.0, games / 35.0)
    stable_season_goals_rate = _blend(season_goals_rate, season_prior, season_conf)

    # Recent form is high-priority, but dampened more for low-sample players.
    recent_form_rate = _blend_rates((recent_5_goals_rate, 0.62), (recent_10_goals_rate, 0.38))
    shot_process_rate = _blend_rates((recent_5_shots_rate, 0.62), (recent_10_shots_rate, 0.38), (season_shots_rate, 0.20))
    if shot_process_rate is not None:
        process_goal_proxy = shot_process_rate * 0.095
    else:
        process_goal_proxy = None
    recent_signal = _blend_rates((recent_form_rate, 0.70), (process_goal_proxy, 0.30))
    recent_conf = min(1.0, games / 20.0) * min(1.0, float(history.recent_form_confidence or 0.85))

    # Usage/opportunity contributes through shot volume and PP proxy, with controlled influence.
    usage_signal = _blend_rates(
        (projected_shots_rate * 0.098 if projected_shots_rate is not None else None, 0.65),
        (season_shots_rate * 0.092 if season_shots_rate is not None else None, 0.35),
    )
    pp_rate = history.projected_pp_goals_per_60
    pp_usage_boost = 1.0 + min(max((float(pp_rate or 0.0) - 1.4) / 12.0, -0.04), 0.07)

    base_intensity = _blend_rates(
        (recent_signal, 0.50 * recent_conf),
        (projected_goals_rate, 0.24),
        (stable_season_goals_rate, 0.20),
        (usage_signal, 0.06),
    )
    if base_intensity is None:
        return None
    base_intensity *= pp_usage_boost

    # Opponent environment is intentionally light.
    opponent_ga = history.opponent_goals_allowed_per_game
    if opponent_ga is None:
        opponent_env_multiplier = 1.0
    else:
        opponent_env_multiplier = 1.0 + min(max((float(opponent_ga) - 3.0) * 0.035, -0.10), 0.10)

    # Matchup history only as shrunk + capped modifier.
    team_idx = _bounded(history.vs_opponent_team_goal_rate_index, low=0.7, high=1.3, fallback=1.0)
    team_conf = min(max(float(history.vs_opponent_team_confidence or 0.0), 0.0), 1.0)
    goalie_idx = _bounded(history.vs_opposing_goalie_goal_rate_index, low=0.7, high=1.3, fallback=1.0)
    goalie_conf = min(max(float(history.vs_opposing_goalie_confidence or 0.0), 0.0), 1.0)
    team_mod = 1.0 + ((team_idx - 1.0) * team_conf * 0.12)
    goalie_mod = 1.0 + ((goalie_idx - 1.0) * goalie_conf * 0.08)
    matchup_modifier = min(max(team_mod * goalie_mod, 0.93), 1.08)

    # Global stabilization to prevent hot low-sample players from spiking too high.
    confidence = min(1.0, (0.65 * min(1.0, games / 55.0)) + (0.35 * min(1.0, float(history.season_confidence or 0.0))))
    safety_prior_intensity = 0.11
    stabilized_intensity = _blend(base_intensity * opponent_env_multiplier * matchup_modifier, safety_prior_intensity, confidence)

    # Poisson probability of >=1 goal with realistic global bounds.
    probability = 1.0 - math.exp(-max(stabilized_intensity, 0.0))
    return min(max(probability, 0.005), 0.72)


def _safe_rate(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return max(float(numerator), 0.0) / float(denominator)


def _blend_rates(*weighted_values: tuple[float | None, float]) -> float | None:
    total_weight = 0.0
    weighted_sum = 0.0
    for value, weight in weighted_values:
        if value is None or weight <= 0:
            continue
        total_weight += weight
        weighted_sum += max(value, 0.0) * weight
    if total_weight <= 0:
        return None
    return weighted_sum / total_weight


def _blend(observed: float | None, prior: float, confidence: float) -> float:
    clamped_conf = min(max(confidence, 0.0), 1.0)
    if observed is None:
        return prior
    return (clamped_conf * max(observed, 0.0)) + ((1.0 - clamped_conf) * max(prior, 0.0))


def _first_present(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return max(float(value), 0.0)
    return None


def _bounded(value: float | None, *, low: float, high: float, fallback: float) -> float:
    if value is None:
        return fallback
    return min(max(float(value), low), high)
