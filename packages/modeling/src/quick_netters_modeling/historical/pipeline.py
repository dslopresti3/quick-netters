from __future__ import annotations

from pathlib import Path

from .aggregates import build_game_table, build_player_game_table, build_team_game_table
from .config import SeasonConfig
from .features import build_feature_rows
from .ingest import load_moneypuck_shots_csv, load_odds_market
from .io_utils import write_csv
from .normalize import normalize_shot_rows
from .paths import DataPaths
from .schemas import GAME_PK, PLAYER_GAME_PK, SHOT_EVENT_PK, TEAM_GAME_PK
from .validation import (
    validate_no_duplicate_keys,
    validate_no_missing_values,
    validate_required_columns,
)


class HistoricalDataPipeline:
    """Build normalized historical assets for Quick Netters hockey workflows."""

    def __init__(self, data_root: Path, season_config: SeasonConfig):
        self.paths = DataPaths(data_root)
        self.config = season_config

    def run(self) -> dict[str, list[Path]]:
        self.paths.ensure_layout(self.config.historical_seasons)
        outputs: dict[str, list[Path]] = {
            "shot_events": [],
            "games": [],
            "player_games": [],
            "team_games": [],
            "features": [],
        }

        for season in self.config.historical_seasons:
            shots_path = self.paths.raw_source_season_dir("moneypuck", season) / "shots.csv"
            odds_path = self.paths.raw_source_season_dir("odds", season) / "odds.json"

            if not shots_path.exists():
                continue

            shot_rows = load_moneypuck_shots_csv(shots_path, season)
            shots = normalize_shot_rows(shot_rows)
            shot_dicts = [s.to_row() for s in shots]

            validate_required_columns(
                shot_dicts,
                ("season", "game_id", "event_id", "event_time_utc", "team_id", "shooter_id"),
                "shot_events",
            )
            validate_no_missing_values(shot_dicts, ("game_id", "event_id"), "shot_events")
            validate_no_duplicate_keys(shot_dicts, SHOT_EVENT_PK, "shot_events")

            shot_out = self.paths.processed_table_season_path("shot_events", season)
            write_csv(shot_out, shot_dicts)
            outputs["shot_events"].append(shot_out)

            games = build_game_table(shots)
            validate_required_columns(games, ("season", "game_id", "home_team_id", "away_team_id"), "games")
            validate_no_duplicate_keys(games, GAME_PK, "games")

            games_out = self.paths.processed_table_season_path("games", season)
            write_csv(games_out, games)
            outputs["games"].append(games_out)

            player_games = build_player_game_table(shots)
            validate_required_columns(player_games, ("season", "game_id", "player_id", "team_id"), "player_games")
            validate_no_duplicate_keys(player_games, PLAYER_GAME_PK, "player_games")

            player_out = self.paths.processed_table_season_path("player_games", season)
            write_csv(player_out, player_games)
            outputs["player_games"].append(player_out)

            team_games = build_team_game_table(shots)
            validate_required_columns(team_games, ("season", "game_id", "team_id", "opponent_team_id"), "team_games")
            validate_no_duplicate_keys(team_games, TEAM_GAME_PK, "team_games")

            team_out = self.paths.processed_table_season_path("team_games", season)
            write_csv(team_out, team_games)
            outputs["team_games"].append(team_out)

            odds_rows = load_odds_market(odds_path) if odds_path.exists() else []
            features = build_feature_rows(team_games, odds_rows)
            features_out = self.paths.processed_features_path(season)
            write_csv(features_out, features)
            outputs["features"].append(features_out)

        return outputs
