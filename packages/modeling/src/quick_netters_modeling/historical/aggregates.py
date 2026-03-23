from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict

from .schemas import GameRecord, PlayerGameAggregate, ShotEvent, TeamGameAggregate


def build_game_table(shots: list[ShotEvent]) -> list[dict]:
    by_game: dict[tuple[int, str], dict] = {}
    teams_by_game: dict[tuple[int, str], set[int]] = defaultdict(set)

    for shot in shots:
        key = (shot.season, shot.game_id)
        teams_by_game[key].add(shot.team_id)

        if key not in by_game:
            by_game[key] = {
                "season": shot.season,
                "game_id": shot.game_id,
                "game_date": shot.event_time_utc.date().isoformat(),
                "home_team_id": 0,
                "away_team_id": 0,
                "home_goals": 0,
                "away_goals": 0,
                "total_shots": 0,
                "total_xg": 0.0,
            }

        rec = by_game[key]
        rec["total_shots"] += 1
        rec["total_xg"] += shot.expected_goal

    out: list[dict] = []
    for key, rec in by_game.items():
        teams = sorted(teams_by_game[key])
        if teams:
            rec["home_team_id"] = teams[0]
        if len(teams) > 1:
            rec["away_team_id"] = teams[1]

        home_team = rec["home_team_id"]
        away_team = rec["away_team_id"]
        rec["home_goals"] = sum(s.is_goal for s in shots if s.season == rec["season"] and s.game_id == rec["game_id"] and s.team_id == home_team)
        rec["away_goals"] = sum(s.is_goal for s in shots if s.season == rec["season"] and s.game_id == rec["game_id"] and s.team_id == away_team)

        out.append(asdict(GameRecord(**rec)))

    return out


def build_player_game_table(shots: list[ShotEvent]) -> list[dict]:
    by_key: dict[tuple[int, str, int], dict] = {}
    for shot in shots:
        key = (shot.season, shot.game_id, shot.shooter_id)
        if key not in by_key:
            by_key[key] = {
                "season": shot.season,
                "game_id": shot.game_id,
                "player_id": shot.shooter_id,
                "team_id": shot.team_id,
                "shots": 0,
                "goals": 0,
                "xg": 0.0,
            }
        rec = by_key[key]
        rec["shots"] += 1
        rec["goals"] += int(shot.is_goal)
        rec["xg"] += shot.expected_goal

    return [asdict(PlayerGameAggregate(**row)) for row in by_key.values()]


def build_team_game_table(shots: list[ShotEvent]) -> list[dict]:
    by_key: dict[tuple[int, str, int], dict] = {}
    teams_by_game: dict[tuple[int, str], set[int]] = defaultdict(set)

    for shot in shots:
        game_key = (shot.season, shot.game_id)
        teams_by_game[game_key].add(shot.team_id)

    for shot in shots:
        key = (shot.season, shot.game_id, shot.team_id)
        if key not in by_key:
            by_key[key] = {
                "season": shot.season,
                "game_id": shot.game_id,
                "team_id": shot.team_id,
                "opponent_team_id": 0,
                "shots_for": 0,
                "shots_against": 0,
                "goals_for": 0,
                "goals_against": 0,
                "xg_for": 0.0,
                "xg_against": 0.0,
            }

        rec = by_key[key]
        rec["shots_for"] += 1
        rec["goals_for"] += int(shot.is_goal)
        rec["xg_for"] += shot.expected_goal

    for (season, game_id, team_id), rec in by_key.items():
        opponents = [t for t in teams_by_game[(season, game_id)] if t != team_id]
        rec["opponent_team_id"] = opponents[0] if opponents else 0
        rec["shots_against"] = sum(
            1 for s in shots if s.season == season and s.game_id == game_id and s.team_id != team_id
        )
        rec["goals_against"] = sum(
            int(s.is_goal)
            for s in shots
            if s.season == season and s.game_id == game_id and s.team_id != team_id
        )
        rec["xg_against"] = sum(
            s.expected_goal
            for s in shots
            if s.season == season and s.game_id == game_id and s.team_id != team_id
        )

    return [asdict(TeamGameAggregate(**row)) for row in by_key.values()]
