from app.services.anytime_calibration import AnytimeCalibrationConfig, summarize_anytime_calibration
from app.services.interfaces import PlayerHistoricalProduction, PlayerProjectionCandidate, PlayerRosterEligibility


def _projection(player_id: str, name: str, games: float, goals: float, shots: float, *, matchup_idx: float = 1.0) -> PlayerProjectionCandidate:
    return PlayerProjectionCandidate(
        game_id="g1",
        nhl_player_id=player_id,
        player_name=name,
        projected_team_name="Team A",
        model_probability=0.05,
        first_goal_probability=0.05,
        historical_production=PlayerHistoricalProduction(
            season_games_played=games,
            season_total_goals=goals,
            season_total_shots=shots,
            recent_5_total_goals=min(goals, 4),
            recent_10_total_goals=min(goals, 6),
            recent_5_total_shots=min(shots, 22),
            recent_10_total_shots=min(shots, 40),
            vs_opponent_team_goal_rate_index=matchup_idx,
            vs_opponent_team_confidence=1.0,
        ),
        roster_eligibility=PlayerRosterEligibility(active_team_name="Team A", is_active_roster=True),
    )


def test_calibration_report_identifies_outliers_and_small_sample_players() -> None:
    projections = [
        _projection("p1", "Elite", games=67, goals=38, shots=250, matchup_idx=1.2),
        _projection("p2", "Depth", games=64, goals=8, shots=80, matchup_idx=1.0),
        _projection("p3", "New Hot", games=5, goals=5, shots=18, matchup_idx=1.35),
    ]

    summary = summarize_anytime_calibration(
        projections,
        config=AnytimeCalibrationConfig(
            outlier_probability_threshold=0.20,
            small_sample_games_threshold=8.0,
            small_sample_probability_threshold=0.12,
            matchup_boost_threshold=0.001,
        ),
    )

    assert summary["candidate_count"] == 3
    assert summary["probability_distribution"]["count"] == 3
    assert summary["top_projected_players"]
    assert any(row["player_id"] == "p3" for row in summary["small_sample_high_probability_players"])
    assert summary["large_matchup_boost_players"]
