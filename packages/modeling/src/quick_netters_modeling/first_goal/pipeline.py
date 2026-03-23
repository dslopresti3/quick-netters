from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from .config import FirstGoalModelConfig
from .schemas import (
    PlayerFirstGoalPrediction,
    PlayerGameSample,
    ScheduledGame,
    ScheduledLineupPlayer,
    TeamGameSample,
)


@dataclass(slots=True)
class _TeamRateStats:
    weighted_games: float = 0.0
    weighted_first_goals: float = 0.0


@dataclass(slots=True)
class _PlayerRateStats:
    weighted_games: float = 0.0
    weighted_first_goals: float = 0.0
    current_season_games: float = 0.0
    current_season_first_goals: float = 0.0
    prior_season_games: float = 0.0
    prior_season_first_goals: float = 0.0


class FirstGoalProbabilityPipeline:
    """Stable v1 first-goal scorer pipeline using two-layer empirical rates.

    Layer 1: team first-goal probability.
    Layer 2: player share conditional on team scoring first.
    """

    def __init__(self, config: FirstGoalModelConfig):
        self.config = config

    def predict(
        self,
        team_games: list[TeamGameSample],
        player_games: list[PlayerGameSample],
        scheduled_games: list[ScheduledGame],
        scheduled_lineups: list[ScheduledLineupPlayer],
    ) -> list[PlayerFirstGoalPrediction]:
        lineup_by_game_team: dict[tuple[str, int], list[ScheduledLineupPlayer]] = defaultdict(list)
        for row in scheduled_lineups:
            if row.is_expected_active:
                lineup_by_game_team[(row.game_id, row.team_id)].append(row)

        model_cache: dict[tuple[int, date], tuple[dict[int, float], dict[int, dict[int, _PlayerRateStats]]]] = {}
        predictions: list[PlayerFirstGoalPrediction] = []
        for game in scheduled_games:
            cache_key = (game.season, game.game_date)
            if cache_key not in model_cache:
                game_team_samples = self._samples_for_game_date(team_games, game.season, game.game_date)
                game_player_samples = self._samples_for_game_date(player_games, game.season, game.game_date)
                model_cache[cache_key] = (
                    self._build_team_rates(game_team_samples, current_season=game.season),
                    self._build_team_player_stats(game_player_samples, current_season=game.season),
                )
            team_rates, team_player_stats = model_cache[cache_key]

            home_lineup = lineup_by_game_team.get((game.game_id, game.home_team_id), [])
            away_lineup = lineup_by_game_team.get((game.game_id, game.away_team_id), [])

            # v1 behavior: if projected lineups are required, only score games with both sides populated.
            if self.config.feature_toggles.use_projected_lineup and (not home_lineup or not away_lineup):
                continue

            p_home_first = self._estimate_team_first_goal_probability(
                home_team_id=game.home_team_id,
                away_team_id=game.away_team_id,
                team_rates=team_rates,
            )

            predictions.extend(
                self._predict_players_for_team(
                    game=game,
                    team_id=game.home_team_id,
                    opponent_team_id=game.away_team_id,
                    team_first_probability=p_home_first,
                    lineup=home_lineup,
                    team_player_stats=team_player_stats,
                )
            )
            predictions.extend(
                self._predict_players_for_team(
                    game=game,
                    team_id=game.away_team_id,
                    opponent_team_id=game.home_team_id,
                    team_first_probability=1.0 - p_home_first,
                    lineup=away_lineup,
                    team_player_stats=team_player_stats,
                )
            )

        return predictions

    def _samples_for_game_date(self, samples: list, current_season: int, game_date: date) -> list:
        return [
            row
            for row in samples
            if row.season in {current_season - 1, current_season}
            and (row.season < current_season or row.game_date < game_date)
        ]

    def _season_weight(self, season: int, current_season: int, current_games_per_team: float) -> float:
        if season not in {current_season, current_season - 1}:
            return 0.0

        ramp_games = max(1.0, float(self.config.season_weights.in_season_ramp_games))
        progress = min(1.0, max(0.0, current_games_per_team / ramp_games))

        last_multiplier = (
            (1.0 - progress) * self.config.season_weights.early_season_last_season_multiplier
            + progress
        )
        current_multiplier = (
            (1.0 - progress) * self.config.season_weights.early_season_current_season_multiplier
            + progress
        )
        return (
            self.config.season_weights.current_season * current_multiplier
            if season == current_season
            else self.config.season_weights.last_season * last_multiplier
        )

    def _build_team_rates(self, team_games: list[TeamGameSample], current_season: int) -> dict[int, float]:
        if not team_games:
            return {}

        current_rows = [row for row in team_games if row.season == current_season]
        current_teams = {row.team_id for row in current_rows}
        current_games_per_team = (
            len(current_rows) / len(current_teams)
            if current_teams
            else 0.0
        )

        by_team: dict[int, list[TeamGameSample]] = defaultdict(list)
        for row in team_games:
            by_team[row.team_id].append(row)

        league_games = 0.0
        league_first_goals = 0.0
        for row in team_games:
            w = self._season_weight(row.season, current_season, current_games_per_team)
            league_games += w
            league_first_goals += w * (1.0 if row.scored_first else 0.0)
        league_rate = (league_first_goals / league_games) if league_games else 0.5

        rates: dict[int, float] = {}
        for team_id, rows in by_team.items():
            long_stats = self._team_rate_from_rows(rows, current_season, current_games_per_team)
            recent_rows = sorted(rows, key=lambda x: x.game_date, reverse=True)[: self.config.rolling_windows.team_games]
            recent_stats = self._team_rate_from_rows(recent_rows, current_season, current_games_per_team)

            long_rate = (
                long_stats.weighted_first_goals / long_stats.weighted_games
                if long_stats.weighted_games
                else league_rate
            )
            recent_rate = (
                recent_stats.weighted_first_goals / recent_stats.weighted_games
                if recent_stats.weighted_games
                else long_rate
            )

            blended = (
                (1.0 - self.config.rolling_windows.team_recent_weight) * long_rate
                + self.config.rolling_windows.team_recent_weight * recent_rate
            )

            prior = self.config.shrinkage.team_prior_strength
            shrunk = (
                (blended * long_stats.weighted_games) + (league_rate * prior)
            ) / (long_stats.weighted_games + prior)

            # extra regression for tiny team sample sizes
            min_games = float(max(1, self.config.minimum_samples.team_games))
            sample_ratio = min(1.0, long_stats.weighted_games / min_games)
            rates[team_id] = (sample_ratio * shrunk) + ((1.0 - sample_ratio) * league_rate)

        return rates

    def _team_rate_from_rows(
        self,
        rows: list[TeamGameSample],
        current_season: int,
        current_games_per_team: float,
    ) -> _TeamRateStats:
        stats = _TeamRateStats()
        for row in rows:
            w = self._season_weight(row.season, current_season, current_games_per_team)
            stats.weighted_games += w
            stats.weighted_first_goals += w * (1.0 if row.scored_first else 0.0)
        return stats

    def _estimate_team_first_goal_probability(
        self,
        home_team_id: int,
        away_team_id: int,
        team_rates: dict[int, float],
    ) -> float:
        home_rate = team_rates.get(home_team_id, 0.5)
        away_rate = team_rates.get(away_team_id, 0.5)

        if self.config.home_away.enabled:
            adv = max(-0.4, min(0.4, self.config.home_away.home_ice_advantage))
            home_rate *= 1.0 + adv
            away_rate *= 1.0 - adv

        denominator = home_rate + away_rate
        if denominator <= 0:
            return 0.5
        return max(0.001, min(0.999, home_rate / denominator))

    def _build_team_player_stats(
        self,
        player_games: list[PlayerGameSample],
        current_season: int,
    ) -> dict[int, dict[int, _PlayerRateStats]]:
        if not player_games:
            return {}

        current_rows = [row for row in player_games if row.season == current_season]
        current_players = {(row.team_id, row.player_id) for row in current_rows}
        current_games_per_player = (
            len(current_rows) / len(current_players)
            if current_players
            else 0.0
        )

        by_team_player_rows: dict[int, dict[int, list[PlayerGameSample]]] = defaultdict(lambda: defaultdict(list))
        for row in player_games:
            by_team_player_rows[row.team_id][row.player_id].append(row)

        out: dict[int, dict[int, _PlayerRateStats]] = defaultdict(dict)
        for team_id, players in by_team_player_rows.items():
            for player_id, rows in players.items():
                sorted_rows = sorted(rows, key=lambda x: x.game_date, reverse=True)
                long_stats = self._single_player_stats_from_rows(
                    sorted_rows, current_season, current_games_per_player
                )
                recent_stats = self._single_player_stats_from_rows(
                    sorted_rows[: self.config.rolling_windows.player_games],
                    current_season,
                    current_games_per_player,
                )

                rw = self.config.rolling_windows.player_recent_weight
                merged = _PlayerRateStats(
                    weighted_games=((1.0 - rw) * long_stats.weighted_games) + (rw * recent_stats.weighted_games),
                    weighted_first_goals=((1.0 - rw) * long_stats.weighted_first_goals) + (rw * recent_stats.weighted_first_goals),
                    current_season_games=long_stats.current_season_games,
                    current_season_first_goals=long_stats.current_season_first_goals,
                    prior_season_games=long_stats.prior_season_games,
                    prior_season_first_goals=long_stats.prior_season_first_goals,
                )
                out[team_id][player_id] = merged
        return out

    def _single_player_stats_from_rows(
        self,
        rows: list[PlayerGameSample],
        current_season: int,
        current_games_per_player: float,
    ) -> _PlayerRateStats:
        out = _PlayerRateStats()
        for row in rows:
            w = self._season_weight(row.season, current_season, current_games_per_player)
            out.weighted_games += w
            out.weighted_first_goals += w * (1.0 if row.scored_first_for_team else 0.0)
            if row.season == current_season:
                out.current_season_games += w
                out.current_season_first_goals += w * (1.0 if row.scored_first_for_team else 0.0)
            elif row.season == current_season - 1:
                out.prior_season_games += w
                out.prior_season_first_goals += w * (1.0 if row.scored_first_for_team else 0.0)
        return out

    def _predict_players_for_team(
        self,
        game: ScheduledGame,
        team_id: int,
        opponent_team_id: int,
        team_first_probability: float,
        lineup: list[ScheduledLineupPlayer],
        team_player_stats: dict[int, dict[int, _PlayerRateStats]],
    ) -> list[PlayerFirstGoalPrediction]:
        if not lineup:
            return []

        team_stats = team_player_stats.get(team_id, {})
        team_first_goals = sum(stats.weighted_first_goals for stats in team_stats.values())

        prior_shares = self._build_prior_shares(lineup)
        empirical_signals: dict[int, float] = {}

        for player in lineup:
            stats = team_stats.get(player.player_id, _PlayerRateStats())
            current_rate = (
                stats.current_season_first_goals / stats.current_season_games
                if stats.current_season_games > 0
                else 0.0
            )
            prior_rate = (
                stats.prior_season_first_goals / stats.prior_season_games
                if stats.prior_season_games > 0
                else current_rate
            )
            full_weight_games = float(max(1, self.config.shrinkage.player_current_baseline_games))
            current_weight = min(1.0, stats.current_season_games / full_weight_games)
            regressed_rate = (current_weight * current_rate) + ((1.0 - current_weight) * prior_rate)
            empirical_signals[player.player_id] = max(0.0, regressed_rate)

        team_empirical_signal = sum(empirical_signals.values())
        unnormalized: dict[int, float] = {}

        for player in lineup:
            stats = team_stats.get(player.player_id, _PlayerRateStats())
            raw_share = (
                empirical_signals[player.player_id] / team_empirical_signal
                if team_empirical_signal > 0
                else 0.0
            )

            has_team_sample = team_first_goals >= self.config.minimum_samples.team_first_goals
            has_player_sample = stats.weighted_games >= self.config.minimum_samples.player_games
            empirical_share = raw_share if (has_team_sample and has_player_sample) else 0.0

            prior_weight = self.config.shrinkage.player_prior_strength
            sample_weight = max(0.0, stats.weighted_games)
            empirical_weight = sample_weight / (sample_weight + prior_weight) if (sample_weight + prior_weight) > 0 else 0.0

            final_share = (
                empirical_weight * empirical_share
                + (1.0 - empirical_weight) * prior_shares[player.player_id]
            )
            unnormalized[player.player_id] = max(0.0, final_share)

        total = sum(unnormalized.values())
        if total <= 0:
            uniform = 1.0 / len(lineup)
            normalized = {p.player_id: uniform for p in lineup}
        else:
            normalized = {player_id: value / total for player_id, value in unnormalized.items()}

        outputs: list[PlayerFirstGoalPrediction] = []
        for player in lineup:
            share = normalized[player.player_id]
            outputs.append(
                PlayerFirstGoalPrediction(
                    game_id=game.game_id,
                    game_date=game.game_date,
                    season=game.season,
                    team_id=team_id,
                    opponent_team_id=opponent_team_id,
                    player_id=player.player_id,
                    team_first_goal_probability=team_first_probability,
                    player_share_given_team_first=share,
                    player_first_goal_probability=team_first_probability * share,
                )
            )
        return outputs

    def _build_prior_shares(self, lineup: list[ScheduledLineupPlayer]) -> dict[int, float]:
        if not lineup:
            return {}

        if self.config.feature_toggles.use_toi_projection:
            weights = {
                row.player_id: max(0.0, row.projected_toi_minutes or 0.0)
                for row in lineup
            }
            if sum(weights.values()) > 0:
                denom = sum(weights.values())
                return {player_id: weight / denom for player_id, weight in weights.items()}

        uniform = 1.0 / len(lineup)
        return {row.player_id: uniform for row in lineup}
