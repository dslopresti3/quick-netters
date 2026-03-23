from __future__ import annotations

import math
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


def _clamp_probability(value: float) -> float:
    return max(0.001, min(0.999, value))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _logit(value: float) -> float:
    p = _clamp_probability(value)
    return math.log(p / (1.0 - p))


@dataclass(slots=True)
class _WeightedRate:
    numerator: float = 0.0
    denominator: float = 0.0

    def add(self, success: float, weight: float) -> None:
        self.numerator += success * weight
        self.denominator += weight


class FirstGoalProbabilityPipeline:
    """Two-layer first-goal scorer model with configurable empirical shrinkage."""

    def __init__(self, config: FirstGoalModelConfig):
        self.config = config

    def predict(
        self,
        team_games: list[TeamGameSample],
        player_games: list[PlayerGameSample],
        scheduled_games: list[ScheduledGame],
        scheduled_lineups: list[ScheduledLineupPlayer],
    ) -> list[PlayerFirstGoalPrediction]:
        team_rates = self._build_team_rates(team_games)
        player_shares = self._build_player_shares(player_games)

        lineup_by_game_team: dict[tuple[str, int], list[ScheduledLineupPlayer]] = defaultdict(list)
        for lineup_entry in scheduled_lineups:
            if lineup_entry.is_expected_active:
                lineup_by_game_team[(lineup_entry.game_id, lineup_entry.team_id)].append(lineup_entry)

        outputs: list[PlayerFirstGoalPrediction] = []
        for game in scheduled_games:
            home_team_probability = self._estimate_team_first_goal_probability(
                team_rates,
                game.home_team_id,
                game.away_team_id,
            )
            away_team_probability = 1.0 - home_team_probability

            outputs.extend(
                self._predict_players_for_team(
                    game,
                    game.home_team_id,
                    game.away_team_id,
                    home_team_probability,
                    lineup_by_game_team.get((game.game_id, game.home_team_id), []),
                    player_shares,
                )
            )
            outputs.extend(
                self._predict_players_for_team(
                    game,
                    game.away_team_id,
                    game.home_team_id,
                    away_team_probability,
                    lineup_by_game_team.get((game.game_id, game.away_team_id), []),
                    player_shares,
                )
            )

        return outputs

    def _season_weight(self, season: int, current_season: int) -> float:
        if season == current_season:
            return self.config.season_weights.current_season
        return self.config.season_weights.last_season

    def _build_team_rates(self, team_games: list[TeamGameSample]) -> dict[int, float]:
        if not team_games:
            return {}
        current_season = max(game.season for game in team_games)

        overall = _WeightedRate()
        team_long: dict[int, _WeightedRate] = defaultdict(_WeightedRate)
        team_recent_events: dict[int, list[tuple[date, float, float]]] = defaultdict(list)

        for row in team_games:
            season_weight = self._season_weight(row.season, current_season)
            success = 1.0 if row.scored_first else 0.0
            overall.add(success, season_weight)
            team_long[row.team_id].add(success, season_weight)
            team_recent_events[row.team_id].append((row.game_date, success, season_weight))

        league_rate = overall.numerator / overall.denominator if overall.denominator else 0.5

        team_rates: dict[int, float] = {}
        for team_id, rate in team_long.items():
            team_games_weight = rate.denominator
            base_rate = rate.numerator / team_games_weight if team_games_weight else league_rate
            blended_rate = self._blend_with_recent(
                base_rate=base_rate,
                events=team_recent_events[team_id],
                window=self.config.rolling_windows.team_games,
                recent_weight=self.config.rolling_windows.team_recent_weight,
            )

            min_games = self.config.minimum_samples.team_games
            sample_ratio = min(1.0, team_games_weight / max(1, min_games))
            blended_rate = (sample_ratio * blended_rate) + ((1.0 - sample_ratio) * league_rate)

            team_prior_strength = self.config.shrinkage.team_prior_strength
            shrunk = (
                (rate.numerator + (league_rate * team_prior_strength))
                / (team_games_weight + team_prior_strength)
            )
            team_rates[team_id] = (0.5 * blended_rate) + (0.5 * shrunk)

        return team_rates

    def _blend_with_recent(
        self,
        base_rate: float,
        events: list[tuple[date, float, float]],
        window: int,
        recent_weight: float,
    ) -> float:
        if not events or window <= 0:
            return base_rate

        sorted_events = sorted(events, key=lambda event: event[0], reverse=True)
        recent = sorted_events[:window]
        recent_weighted_total = sum(weight for _, _, weight in recent)
        if recent_weighted_total <= 0:
            return base_rate

        recent_rate = sum(success * weight for _, success, weight in recent) / recent_weighted_total
        return ((1.0 - recent_weight) * base_rate) + (recent_weight * recent_rate)

    def _estimate_team_first_goal_probability(
        self,
        team_rates: dict[int, float],
        home_team_id: int,
        away_team_id: int,
    ) -> float:
        league_default = 0.5
        home_rate = team_rates.get(home_team_id, league_default)
        away_rate = team_rates.get(away_team_id, league_default)

        margin = _logit(home_rate) - _logit(away_rate)
        if self.config.home_away.enabled:
            margin += self.config.home_away.home_ice_advantage

        return _sigmoid(margin)

    def _build_player_shares(self, player_games: list[PlayerGameSample]) -> dict[int, dict[int, float]]:
        if not player_games:
            return {}
        current_season = max(row.season for row in player_games)

        team_first_totals = _TeamTotals()
        team_stats: dict[int, _TeamTotals] = defaultdict(_TeamTotals)
        player_stats: dict[tuple[int, int], _WeightedRate] = defaultdict(_WeightedRate)
        player_recent_events: dict[tuple[int, int], list[tuple[date, float, float]]] = defaultdict(list)

        for row in player_games:
            season_weight = self._season_weight(row.season, current_season)
            game_weight = season_weight * (1.0 if row.on_ice_first_shift else 0.5)
            scored_first = 1.0 if row.scored_first_for_team else 0.0

            team_first_totals.games += game_weight
            team_first_totals.first_goals += scored_first * game_weight
            team_stats[row.team_id].games += game_weight
            team_stats[row.team_id].first_goals += scored_first * game_weight

            player_stats[(row.team_id, row.player_id)].add(scored_first, game_weight)
            player_recent_events[(row.team_id, row.player_id)].append((row.game_date, scored_first, game_weight))

        league_player_share = (
            team_first_totals.first_goals / team_first_totals.games if team_first_totals.games else 0.05
        )

        shares: dict[int, dict[int, float]] = defaultdict(dict)
        for (team_id, player_id), stat in player_stats.items():
            team_total = team_stats[team_id]
            if team_total.first_goals < self.config.minimum_samples.team_first_goals:
                continue

            raw_share = stat.numerator / team_total.first_goals if team_total.first_goals else 0.0
            recent_share = self._build_recent_player_share(
                team_first_goals=team_total.first_goals,
                events=player_recent_events[(team_id, player_id)],
            )
            blended_share = (
                ((1.0 - self.config.rolling_windows.player_recent_weight) * raw_share)
                + (self.config.rolling_windows.player_recent_weight * recent_share)
            )

            prior_strength = self.config.shrinkage.player_prior_strength
            shrunk_share = (
                stat.numerator + (league_player_share * prior_strength)
            ) / (team_total.first_goals + prior_strength)

            combined = (0.5 * blended_share) + (0.5 * shrunk_share)
            if stat.denominator < self.config.minimum_samples.player_games:
                sample_ratio = stat.denominator / max(1.0, float(self.config.minimum_samples.player_games))
                combined = (sample_ratio * combined) + ((1.0 - sample_ratio) * shrunk_share)

            shares[team_id][player_id] = max(0.0, combined)

        return shares

    def _build_recent_player_share(
        self,
        team_first_goals: float,
        events: list[tuple[date, float, float]],
    ) -> float:
        if not events:
            return 0.0
        recent_window = max(1, self.config.rolling_windows.player_games)
        sorted_events = sorted(events, key=lambda value: value[0], reverse=True)
        recent_events = sorted_events[:recent_window]

        numerator = sum(success * weight for _, success, weight in recent_events)
        return numerator / max(team_first_goals, 1.0)

    def _predict_players_for_team(
        self,
        game: ScheduledGame,
        team_id: int,
        opponent_team_id: int,
        team_probability: float,
        lineup: list[ScheduledLineupPlayer],
        player_shares: dict[int, dict[int, float]],
    ) -> list[PlayerFirstGoalPrediction]:
        if self.config.feature_toggles.use_projected_lineup and not lineup:
            return []

        team_player_share = dict(player_shares.get(team_id, {}))
        team_lineup = lineup if lineup else self._fallback_lineup_from_history(team_player_share)
        if not team_lineup:
            return []

        weights: dict[int, float] = {}
        for player in team_lineup:
            base_share = team_player_share.get(player.player_id, 0.0)
            if self.config.feature_toggles.use_toi_projection:
                toi_factor = max(0.1, (player.projected_toi_minutes or 10.0) / 10.0)
            else:
                toi_factor = 1.0
            weights[player.player_id] = max(0.0, base_share * toi_factor)

        total_weight = sum(weights.values())
        if total_weight <= 0:
            uniform_weight = 1.0 / len(team_lineup)
            normalized_share = {player.player_id: uniform_weight for player in team_lineup}
        else:
            normalized_share = {player_id: value / total_weight for player_id, value in weights.items()}

        output_rows: list[PlayerFirstGoalPrediction] = []
        for player in team_lineup:
            conditional_share = normalized_share[player.player_id]
            output_rows.append(
                PlayerFirstGoalPrediction(
                    game_id=game.game_id,
                    game_date=game.game_date,
                    season=game.season,
                    team_id=team_id,
                    opponent_team_id=opponent_team_id,
                    player_id=player.player_id,
                    team_first_goal_probability=team_probability,
                    player_share_given_team_first=conditional_share,
                    player_first_goal_probability=team_probability * conditional_share,
                )
            )

        return output_rows

    def _fallback_lineup_from_history(
        self,
        team_player_share: dict[int, float],
    ) -> list[ScheduledLineupPlayer]:
        if not team_player_share:
            return []
        ranked = sorted(team_player_share.items(), key=lambda item: item[1], reverse=True)[:18]
        return [
            ScheduledLineupPlayer(
                game_id="unknown",
                team_id=-1,
                player_id=player_id,
                projected_toi_minutes=None,
                is_expected_active=True,
            )
            for player_id, _ in ranked
        ]


@dataclass(slots=True)
class _TeamTotals:
    games: float = 0.0
    first_goals: float = 0.0
