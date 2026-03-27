from __future__ import annotations

from dataclasses import dataclass
import math
import os

from app.services.interfaces import PlayerHistoricalProduction


@dataclass(frozen=True)
class AnytimeModelConfig:
    season_prior_goal_rate: float = 0.14
    season_confidence_games: float = 35.0
    recent_confidence_games: float = 20.0
    recent_signal_weight: float = 0.50
    projected_goal_weight: float = 0.24
    season_baseline_weight: float = 0.20
    usage_weight: float = 0.06
    pp_baseline_goals_per_60: float = 1.4
    pp_boost_divisor: float = 12.0
    pp_boost_min: float = -0.04
    pp_boost_max: float = 0.07
    opponent_ga_baseline: float = 3.0
    opponent_ga_slope: float = 0.035
    opponent_env_min: float = -0.10
    opponent_env_max: float = 0.10
    team_matchup_weight: float = 0.12
    goalie_matchup_weight: float = 0.08
    matchup_modifier_min: float = 0.93
    matchup_modifier_max: float = 1.08
    safety_prior_intensity: float = 0.11
    season_stability_games: float = 55.0
    season_confidence_weight: float = 0.35
    min_probability: float = 0.005
    max_probability: float = 0.72
    longshot_guardrail_games: float = 16.0
    longshot_guardrail_probability_cap: float = 0.19
    longshot_guardrail_shrink_factor: float = 0.72


@dataclass(frozen=True)
class AnytimeProbabilityDiagnostics:
    recent_form_contribution: float
    season_baseline_contribution: float
    usage_opportunity_contribution: float
    matchup_history_contribution: float
    stabilization_effect: float
    expected_scoring_intensity: float
    anytime_probability: float


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def load_anytime_model_config() -> AnytimeModelConfig:
    return AnytimeModelConfig(
        season_prior_goal_rate=_env_float("ANYTIME_SEASON_PRIOR_GOAL_RATE", 0.14),
        season_confidence_games=max(_env_float("ANYTIME_SEASON_CONFIDENCE_GAMES", 35.0), 1.0),
        recent_confidence_games=max(_env_float("ANYTIME_RECENT_CONFIDENCE_GAMES", 20.0), 1.0),
        recent_signal_weight=max(_env_float("ANYTIME_RECENT_SIGNAL_WEIGHT", 0.50), 0.0),
        projected_goal_weight=max(_env_float("ANYTIME_PROJECTED_GOAL_WEIGHT", 0.24), 0.0),
        season_baseline_weight=max(_env_float("ANYTIME_SEASON_BASELINE_WEIGHT", 0.20), 0.0),
        usage_weight=max(_env_float("ANYTIME_USAGE_WEIGHT", 0.06), 0.0),
        pp_baseline_goals_per_60=_env_float("ANYTIME_PP_BASELINE_G60", 1.4),
        pp_boost_divisor=max(_env_float("ANYTIME_PP_BOOST_DIVISOR", 12.0), 1.0),
        pp_boost_min=_env_float("ANYTIME_PP_BOOST_MIN", -0.04),
        pp_boost_max=_env_float("ANYTIME_PP_BOOST_MAX", 0.07),
        opponent_ga_baseline=_env_float("ANYTIME_OPP_GA_BASELINE", 3.0),
        opponent_ga_slope=_env_float("ANYTIME_OPP_GA_SLOPE", 0.035),
        opponent_env_min=_env_float("ANYTIME_OPP_ENV_MIN", -0.10),
        opponent_env_max=_env_float("ANYTIME_OPP_ENV_MAX", 0.10),
        team_matchup_weight=max(_env_float("ANYTIME_TEAM_MATCHUP_WEIGHT", 0.12), 0.0),
        goalie_matchup_weight=max(_env_float("ANYTIME_GOALIE_MATCHUP_WEIGHT", 0.08), 0.0),
        matchup_modifier_min=_env_float("ANYTIME_MATCHUP_MOD_MIN", 0.93),
        matchup_modifier_max=_env_float("ANYTIME_MATCHUP_MOD_MAX", 1.08),
        safety_prior_intensity=max(_env_float("ANYTIME_SAFETY_PRIOR_INTENSITY", 0.11), 0.001),
        season_stability_games=max(_env_float("ANYTIME_STABILITY_GAMES", 55.0), 1.0),
        season_confidence_weight=min(max(_env_float("ANYTIME_SEASON_CONF_WEIGHT", 0.35), 0.0), 1.0),
        min_probability=max(_env_float("ANYTIME_MIN_PROBABILITY", 0.005), 0.0),
        max_probability=min(max(_env_float("ANYTIME_MAX_PROBABILITY", 0.72), 0.01), 0.99),
        longshot_guardrail_games=max(_env_float("ANYTIME_GUARDRAIL_MIN_GAMES", 16.0), 1.0),
        longshot_guardrail_probability_cap=max(_env_float("ANYTIME_GUARDRAIL_PROB_CAP", 0.19), 0.01),
        longshot_guardrail_shrink_factor=min(max(_env_float("ANYTIME_GUARDRAIL_SHRINK", 0.72), 0.05), 1.0),
    )


def estimate_anytime_goal_probability(history: PlayerHistoricalProduction) -> float | None:
    diagnostics = estimate_anytime_goal_probability_diagnostics(history)
    if diagnostics is None:
        return None
    return diagnostics.anytime_probability


def estimate_anytime_goal_probability_diagnostics(history: PlayerHistoricalProduction) -> AnytimeProbabilityDiagnostics | None:
    """Estimate anytime probability with component diagnostics."""
    config = load_anytime_model_config()

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
    season_prior = config.season_prior_goal_rate
    season_conf = min(1.0, games / config.season_confidence_games)
    stable_season_goals_rate = _blend(season_goals_rate, season_prior, season_conf)

    # Recent form is high-priority, but dampened more for low-sample players.
    recent_form_rate = _blend_rates((recent_5_goals_rate, 0.62), (recent_10_goals_rate, 0.38))
    shot_process_rate = _blend_rates((recent_5_shots_rate, 0.62), (recent_10_shots_rate, 0.38), (season_shots_rate, 0.20))
    if shot_process_rate is not None:
        process_goal_proxy = shot_process_rate * 0.095
    else:
        process_goal_proxy = None
    recent_signal = _blend_rates((recent_form_rate, 0.70), (process_goal_proxy, 0.30))
    recent_conf = min(1.0, games / config.recent_confidence_games) * min(1.0, float(history.recent_form_confidence or 0.85))

    # Usage/opportunity contributes through shot volume and PP proxy, with controlled influence.
    usage_signal = _blend_rates(
        (projected_shots_rate * 0.098 if projected_shots_rate is not None else None, 0.65),
        (season_shots_rate * 0.092 if season_shots_rate is not None else None, 0.35),
    )
    pp_rate = history.projected_pp_goals_per_60
    pp_usage_boost = 1.0 + min(
        max((float(pp_rate or 0.0) - config.pp_baseline_goals_per_60) / config.pp_boost_divisor, config.pp_boost_min),
        config.pp_boost_max,
    )

    pre_pp_intensity = _blend_rates(
        (recent_signal, config.recent_signal_weight * recent_conf),
        (projected_goals_rate, config.projected_goal_weight),
        (stable_season_goals_rate, config.season_baseline_weight),
        (usage_signal, config.usage_weight),
    )
    if pre_pp_intensity is None:
        return None
    base_intensity = pre_pp_intensity * pp_usage_boost

    # Opponent environment is intentionally light.
    opponent_ga = history.opponent_goals_allowed_per_game
    if opponent_ga is None:
        opponent_env_multiplier = 1.0
    else:
        opponent_env_multiplier = 1.0 + min(
            max((float(opponent_ga) - config.opponent_ga_baseline) * config.opponent_ga_slope, config.opponent_env_min),
            config.opponent_env_max,
        )

    # Matchup history only as shrunk + capped modifier.
    team_idx = _bounded(history.vs_opponent_team_goal_rate_index, low=0.7, high=1.3, fallback=1.0)
    team_conf = min(max(float(history.vs_opponent_team_confidence or 0.0), 0.0), 1.0)
    goalie_idx = _bounded(history.vs_opposing_goalie_goal_rate_index, low=0.7, high=1.3, fallback=1.0)
    goalie_conf = min(max(float(history.vs_opposing_goalie_confidence or 0.0), 0.0), 1.0)
    team_mod = 1.0 + ((team_idx - 1.0) * team_conf * config.team_matchup_weight)
    goalie_mod = 1.0 + ((goalie_idx - 1.0) * goalie_conf * config.goalie_matchup_weight)
    matchup_modifier = min(max(team_mod * goalie_mod, config.matchup_modifier_min), config.matchup_modifier_max)

    # Global stabilization to prevent hot low-sample players from spiking too high.
    season_weight = config.season_confidence_weight
    sample_weight = 1.0 - season_weight
    confidence = min(
        1.0,
        (sample_weight * min(1.0, games / config.season_stability_games)) + (season_weight * min(1.0, float(history.season_confidence or 0.0))),
    )
    safety_prior_intensity = config.safety_prior_intensity
    pre_stabilized_intensity = base_intensity * opponent_env_multiplier * matchup_modifier
    stabilized_intensity = _blend(pre_stabilized_intensity, safety_prior_intensity, confidence)

    if games < config.longshot_guardrail_games and stabilized_intensity > config.longshot_guardrail_probability_cap:
        stabilized_intensity = (
            config.longshot_guardrail_probability_cap
            + ((stabilized_intensity - config.longshot_guardrail_probability_cap) * config.longshot_guardrail_shrink_factor)
        )

    # Poisson probability of >=1 goal with realistic global bounds.
    probability = 1.0 - math.exp(-max(stabilized_intensity, 0.0))
    clipped_probability = min(max(probability, config.min_probability), config.max_probability)

    recent_form_contribution = (recent_signal or 0.0) * (config.recent_signal_weight * recent_conf) * pp_usage_boost
    season_baseline_contribution = (stable_season_goals_rate or 0.0) * config.season_baseline_weight * pp_usage_boost
    usage_contribution = (usage_signal or 0.0) * config.usage_weight * pp_usage_boost
    matchup_contribution = (base_intensity * opponent_env_multiplier * matchup_modifier) - (base_intensity * opponent_env_multiplier)
    stabilization_effect = stabilized_intensity - pre_stabilized_intensity

    return AnytimeProbabilityDiagnostics(
        recent_form_contribution=round(recent_form_contribution, 6),
        season_baseline_contribution=round(season_baseline_contribution, 6),
        usage_opportunity_contribution=round(usage_contribution, 6),
        matchup_history_contribution=round(matchup_contribution, 6),
        stabilization_effect=round(stabilization_effect, 6),
        expected_scoring_intensity=round(stabilized_intensity, 6),
        anytime_probability=round(clipped_probability, 6),
    )


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
