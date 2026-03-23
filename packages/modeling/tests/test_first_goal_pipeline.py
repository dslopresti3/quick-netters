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


if __name__ == "__main__":
    unittest.main()
