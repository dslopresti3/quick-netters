from app.services.interfaces import PlayerHistoricalProduction
from app.services.probabilities import estimate_anytime_goal_probability, estimate_anytime_goal_probability_diagnostics


def test_anytime_probability_respects_player_tiers() -> None:
    top_scorer = PlayerHistoricalProduction(
        season_games_played=66,
        season_total_goals=42,
        season_total_shots=255,
        recent_5_total_goals=5,
        recent_10_total_goals=8,
        recent_5_total_shots=26,
        recent_10_total_shots=51,
    )
    mid_tier = PlayerHistoricalProduction(
        season_games_played=68,
        season_total_goals=24,
        season_total_shots=185,
        recent_5_total_goals=2,
        recent_10_total_goals=3,
        recent_5_total_shots=17,
        recent_10_total_shots=31,
    )
    depth_player = PlayerHistoricalProduction(
        season_games_played=62,
        season_total_goals=8,
        season_total_shots=78,
        recent_5_total_goals=0,
        recent_10_total_goals=1,
        recent_5_total_shots=5,
        recent_10_total_shots=11,
    )

    top_p = estimate_anytime_goal_probability(top_scorer)
    mid_p = estimate_anytime_goal_probability(mid_tier)
    depth_p = estimate_anytime_goal_probability(depth_player)

    assert top_p is not None and mid_p is not None and depth_p is not None
    assert top_p > mid_p > depth_p
    assert top_p < 0.6
    assert depth_p > 0.03


def test_anytime_probability_shrinks_low_sample_hot_streak() -> None:
    hot_low_sample = PlayerHistoricalProduction(
        season_games_played=6,
        season_total_goals=6,
        season_total_shots=22,
        recent_5_total_goals=5,
        recent_10_total_goals=6,
        recent_5_total_shots=20,
        recent_10_total_shots=22,
    )
    established_elite = PlayerHistoricalProduction(
        season_games_played=65,
        season_total_goals=40,
        season_total_shots=245,
        recent_5_total_goals=4,
        recent_10_total_goals=7,
        recent_5_total_shots=24,
        recent_10_total_shots=47,
    )

    low_sample_p = estimate_anytime_goal_probability(hot_low_sample)
    elite_p = estimate_anytime_goal_probability(established_elite)

    assert low_sample_p is not None and elite_p is not None
    assert low_sample_p < elite_p
    assert low_sample_p < 0.35


def test_matchup_history_modifier_is_lightweight() -> None:
    baseline = PlayerHistoricalProduction(
        season_games_played=58,
        season_total_goals=22,
        season_total_shots=175,
        recent_5_total_goals=2,
        recent_10_total_goals=4,
        recent_5_total_shots=16,
        recent_10_total_shots=30,
    )
    extreme_matchup = PlayerHistoricalProduction(
        season_games_played=58,
        season_total_goals=22,
        season_total_shots=175,
        recent_5_total_goals=2,
        recent_10_total_goals=4,
        recent_5_total_shots=16,
        recent_10_total_shots=30,
        vs_opponent_team_goal_rate_index=1.8,
        vs_opponent_team_confidence=1.0,
        vs_opposing_goalie_goal_rate_index=1.8,
        vs_opposing_goalie_confidence=1.0,
    )

    baseline_p = estimate_anytime_goal_probability(baseline)
    matchup_p = estimate_anytime_goal_probability(extreme_matchup)

    assert baseline_p is not None and matchup_p is not None
    assert matchup_p > baseline_p
    assert (matchup_p - baseline_p) < 0.05


def test_anytime_diagnostics_exposes_component_breakdown() -> None:
    history = PlayerHistoricalProduction(
        season_games_played=61,
        season_total_goals=26,
        season_total_shots=190,
        recent_5_total_goals=3,
        recent_10_total_goals=4,
        recent_5_total_shots=17,
        recent_10_total_shots=31,
        projected_pp_goals_per_60=2.1,
        vs_opponent_team_goal_rate_index=1.15,
        vs_opponent_team_confidence=0.8,
    )

    diagnostics = estimate_anytime_goal_probability_diagnostics(history)

    assert diagnostics is not None
    assert diagnostics.recent_form_contribution > 0
    assert diagnostics.season_baseline_contribution > 0
    assert diagnostics.usage_opportunity_contribution > 0
    assert diagnostics.expected_scoring_intensity > 0
    assert 0 < diagnostics.anytime_probability < 1
