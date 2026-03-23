from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from quick_netters_modeling.first_goal import (
    FirstGoalModelConfig,
    FirstGoalProbabilityPipeline,
    PlayerGameSample,
    ScheduledGame,
    ScheduledLineupPlayer,
    TeamGameSample,
)


class FirstGoalPipelineTests(unittest.TestCase):
    def test_probabilities_are_structured_and_normalized_by_game(self) -> None:
        pipeline = FirstGoalProbabilityPipeline(config=FirstGoalModelConfig())

        team_games = [
            TeamGameSample("g1", date(2025, 10, 1), 2025, 1, 2, True, True),
            TeamGameSample("g1", date(2025, 10, 1), 2025, 2, 1, False, False),
            TeamGameSample("g2", date(2026, 1, 2), 2026, 1, 3, False, False),
            TeamGameSample("g2", date(2026, 1, 2), 2026, 3, 1, True, True),
        ]
        player_games = [
            PlayerGameSample("g1", date(2025, 10, 1), 2025, 1, 11, True, toi_minutes=18.0),
            PlayerGameSample("g1", date(2025, 10, 1), 2025, 1, 12, False, toi_minutes=16.0),
            PlayerGameSample("g2", date(2026, 1, 2), 2026, 1, 11, False, toi_minutes=18.0),
            PlayerGameSample("g2", date(2026, 1, 2), 2026, 1, 12, False, toi_minutes=16.0),
            PlayerGameSample("g3", date(2026, 1, 3), 2026, 3, 31, True, toi_minutes=19.0),
            PlayerGameSample("g3", date(2026, 1, 3), 2026, 3, 32, False, toi_minutes=15.0),
        ]

        scheduled_games = [ScheduledGame("upcoming", date(2026, 3, 24), 2026, 1, 3)]
        lineups = [
            ScheduledLineupPlayer("upcoming", 1, 11, 18.0),
            ScheduledLineupPlayer("upcoming", 1, 12, 16.0),
            ScheduledLineupPlayer("upcoming", 3, 31, 19.0),
            ScheduledLineupPlayer("upcoming", 3, 32, 15.0),
        ]

        results = pipeline.predict(team_games, player_games, scheduled_games, lineups)

        self.assertEqual(len(results), 4)
        self.assertTrue(all(row.game_id == "upcoming" for row in results))

        total_probability = sum(row.player_first_goal_probability for row in results)
        self.assertAlmostEqual(total_probability, 1.0, places=6)

    def test_config_loads_from_json(self) -> None:
        config_path = Path("packages/modeling/config/first_goal_model_config.json")
        config = FirstGoalModelConfig.from_json(config_path)
        self.assertGreater(config.season_weights.current_season, 0)
        self.assertGreater(config.shrinkage.team_prior_strength, 0)
        self.assertGreater(config.season_weights.in_season_ramp_games, 0)

    def test_early_season_weights_reduce_reaction_to_tiny_current_samples(self) -> None:
        pipeline = FirstGoalProbabilityPipeline(config=FirstGoalModelConfig())

        team_games = [
            TeamGameSample("ls1", date(2025, 11, 1), 2025, 1, 2, True, True),
            TeamGameSample("ls1", date(2025, 11, 1), 2025, 2, 1, False, False),
            TeamGameSample("ls2", date(2025, 11, 5), 2025, 1, 2, False, True),
            TeamGameSample("ls2", date(2025, 11, 5), 2025, 2, 1, True, False),
            TeamGameSample("cs1", date(2026, 10, 4), 2026, 1, 2, True, False),
            TeamGameSample("cs1", date(2026, 10, 4), 2026, 2, 1, False, True),
            TeamGameSample("cs2", date(2026, 11, 1), 2026, 1, 3, True, False),
            TeamGameSample("cs2", date(2026, 11, 1), 2026, 3, 1, False, True),
            TeamGameSample("cs3", date(2026, 11, 8), 2026, 1, 4, True, False),
            TeamGameSample("cs3", date(2026, 11, 8), 2026, 4, 1, False, True),
        ]
        player_games = [
            PlayerGameSample("p_ls1", date(2025, 11, 1), 2025, 1, 11, True),
            PlayerGameSample("p_ls2", date(2025, 11, 5), 2025, 1, 12, True),
            PlayerGameSample("p_cs1", date(2026, 10, 4), 2026, 1, 11, False),
            PlayerGameSample("p_cs2", date(2026, 10, 4), 2026, 2, 21, True),
        ]
        lineups = [
            ScheduledLineupPlayer("early", 1, 11, 20.0),
            ScheduledLineupPlayer("early", 1, 12, 18.0),
            ScheduledLineupPlayer("early", 2, 21, 20.0),
            ScheduledLineupPlayer("early", 2, 22, 18.0),
            ScheduledLineupPlayer("late", 1, 11, 20.0),
            ScheduledLineupPlayer("late", 1, 12, 18.0),
            ScheduledLineupPlayer("late", 2, 21, 20.0),
            ScheduledLineupPlayer("late", 2, 22, 18.0),
        ]
        scheduled_games = [
            ScheduledGame("early", date(2026, 10, 5), 2026, 1, 2),
            ScheduledGame("late", date(2026, 12, 1), 2026, 1, 2),
        ]

        results = pipeline.predict(team_games, player_games, scheduled_games, lineups)
        by_game = {
            game_id: [r for r in results if r.game_id == game_id]
            for game_id in {"early", "late"}
        }

        early_team_prob = by_game["early"][0].team_first_goal_probability
        late_team_prob = by_game["late"][0].team_first_goal_probability
        self.assertGreater(early_team_prob, late_team_prob)

    def test_player_share_regresses_toward_prior_baseline_for_small_current_sample(self) -> None:
        config = FirstGoalModelConfig.from_dict(
            {
                "minimum_samples": {"team_games": 1, "player_games": 1, "team_first_goals": 1},
                "shrinkage": {"player_prior_strength": 0.1, "player_current_baseline_games": 10},
            }
        )
        pipeline = FirstGoalProbabilityPipeline(config=config)

        team_games = [
            TeamGameSample("ls1", date(2025, 11, 1), 2025, 1, 2, True, True),
            TeamGameSample("ls1", date(2025, 11, 1), 2025, 2, 1, False, False),
            TeamGameSample("cs1", date(2026, 10, 2), 2026, 1, 2, True, True),
            TeamGameSample("cs1", date(2026, 10, 2), 2026, 2, 1, False, False),
        ]
        player_games = [
            PlayerGameSample("ls1", date(2025, 11, 1), 2025, 1, 11, True),
            PlayerGameSample("ls2", date(2025, 11, 5), 2025, 1, 11, True),
            PlayerGameSample("ls3", date(2025, 11, 10), 2025, 1, 12, False),
            PlayerGameSample("ls4", date(2025, 11, 12), 2025, 1, 12, False),
            PlayerGameSample("cs1", date(2026, 10, 2), 2026, 1, 11, False),
            PlayerGameSample("cs1", date(2026, 10, 2), 2026, 1, 12, True),
        ]
        scheduled_games = [ScheduledGame("upcoming", date(2026, 10, 3), 2026, 1, 2)]
        lineups = [
            ScheduledLineupPlayer("upcoming", 1, 11, 20.0),
            ScheduledLineupPlayer("upcoming", 1, 12, 20.0),
            ScheduledLineupPlayer("upcoming", 2, 21, 20.0),
            ScheduledLineupPlayer("upcoming", 2, 22, 20.0),
        ]

        results = pipeline.predict(team_games, player_games, scheduled_games, lineups)
        team_one = [r for r in results if r.team_id == 1]
        by_player = {r.player_id: r for r in team_one}

        self.assertGreater(
            by_player[11].player_share_given_team_first,
            by_player[12].player_share_given_team_first,
        )


if __name__ == "__main__":
    unittest.main()
