from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any


ELIGIBLE_GAME_TYPE_CODES = {2, 3}
RECENT_WINDOWS = (5, 10, 20)
DEFAULT_LEAGUE_BASELINE = {
    "goals_per_game": 0.18,
    "shots_per_game": 2.3,
    "goals_per_60": 0.75,
    "shots_per_60": 9.2,
    "pp_goals_per_60": 2.2,
}
TEAM_MATCHUP_PRIOR_GAMES = 14.0
GOALIE_MATCHUP_PRIOR_GAMES = 10.0
TEAM_MATCHUP_MAX_INFLUENCE = 0.35
GOALIE_MATCHUP_MAX_INFLUENCE = 0.25


def build_feature_rows(team_games: list[dict], odds_rows: list[dict]) -> list[dict]:
    odds_by_game: dict[str, dict] = {}
    for row in odds_rows:
        game_id = str(row.get("game_id", row.get("gameId", "")))
        if game_id:
            odds_by_game[game_id] = row

    out: list[dict] = []
    for row in team_games:
        game_id = row["game_id"]
        odds = odds_by_game.get(game_id, {})
        out.append(
            {
                "season": row["season"],
                "game_id": game_id,
                "team_id": row["team_id"],
                "opponent_team_id": row["opponent_team_id"],
                "shots_for": row["shots_for"],
                "shots_against": row["shots_against"],
                "goals_for": row["goals_for"],
                "goals_against": row["goals_against"],
                "xg_for": row["xg_for"],
                "xg_against": row["xg_against"],
                "market_moneyline": odds.get("moneyline"),
                "market_total": odds.get("total"),
            }
        )
    return out


def build_player_probability_features(
    player_game_rows: list[dict[str, Any]],
    *,
    as_of_date: date,
    season: str | None = None,
    matchup_team_by_player: dict[str, str] | None = None,
    matchup_goalie_by_player: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build player-level feature rows for projection models (e.g., anytime, first-goal)."""
    eligible_rows = [
        row
        for row in player_game_rows
        if _is_model_eligible_game(row)
        and (dt := _parse_game_date(row.get("game_date"))) is not None
        and dt < as_of_date
    ]
    if not eligible_rows:
        return []

    league_baseline = _build_league_baseline(eligible_rows)
    by_player: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in eligible_rows:
        key = (
            str(row.get("player_id", "")).strip(),
            str(row.get("team", "")).strip(),
        )
        if key[0]:
            by_player[key].append(row)

    feature_rows: list[dict[str, Any]] = []
    for (player_id, team), rows in by_player.items():
        player_rows = sorted(rows, key=lambda item: _parse_game_date(item.get("game_date")) or date.min, reverse=True)
        latest = player_rows[0]
        player_season = season or str(latest.get("season", "")).strip()
        season_rows = [row for row in player_rows if str(row.get("season", "")).strip() == player_season]
        season_block = _compute_rate_block(season_rows)
        season_stabilized = _stabilize_season_block(season_block, league_baseline)

        row: dict[str, Any] = {
            "as_of_date": as_of_date.isoformat(),
            "season": player_season,
            "player_id": player_id,
            "player_name": str(latest.get("player_name", "")).strip(),
            "team": team,
            "games_played_season": season_block["games"],
            "goals_season": season_block["goals"],
            "shots_season": season_block["shots"],
            "goals_per_game_season": season_block["goals_per_game"],
            "shots_per_game_season": season_block["shots_per_game"],
            "goals_per_60_season": season_block["goals_per_60"],
            "shots_per_60_season": season_block["shots_per_60"],
            "pp_toi_minutes_per_game_season": season_block["pp_toi_minutes_per_game"],
            "pp_goals_per_60_season": season_block["pp_goals_per_60"],
            "goals_per_game_season_stabilized": season_stabilized["goals_per_game"],
            "shots_per_game_season_stabilized": season_stabilized["shots_per_game"],
            "goals_per_60_season_stabilized": season_stabilized["goals_per_60"],
            "shots_per_60_season_stabilized": season_stabilized["shots_per_60"],
            "pp_goals_per_60_season_stabilized": season_stabilized["pp_goals_per_60"],
            "season_confidence": season_stabilized["confidence"],
        }

        recent_projection_components: dict[str, float] = {}
        recent_confidence = 0.0
        for window in RECENT_WINDOWS:
            window_rows = player_rows[:window]
            window_block = _compute_rate_block(window_rows)
            window_stabilized = _stabilize_recent_block(window_block, season_stabilized)
            row.update(
                {
                    f"games_last_{window}": window_block["games"],
                    f"goals_last_{window}": window_block["goals"],
                    f"shots_last_{window}": window_block["shots"],
                    f"goals_per_game_last_{window}": window_block["goals_per_game"],
                    f"shots_per_game_last_{window}": window_block["shots_per_game"],
                    f"goals_per_60_last_{window}": window_block["goals_per_60"],
                    f"shots_per_60_last_{window}": window_block["shots_per_60"],
                    f"pp_toi_minutes_per_game_last_{window}": window_block["pp_toi_minutes_per_game"],
                    f"pp_goals_per_60_last_{window}": window_block["pp_goals_per_60"],
                    f"goals_per_game_last_{window}_stabilized": window_stabilized["goals_per_game"],
                    f"shots_per_game_last_{window}_stabilized": window_stabilized["shots_per_game"],
                    f"goals_per_60_last_{window}_stabilized": window_stabilized["goals_per_60"],
                    f"shots_per_60_last_{window}_stabilized": window_stabilized["shots_per_60"],
                    f"pp_goals_per_60_last_{window}_stabilized": window_stabilized["pp_goals_per_60"],
                    f"recent_confidence_last_{window}": window_stabilized["confidence"],
                }
            )
            weight = {5: 0.5, 10: 0.3, 20: 0.2}[window]
            recent_confidence += weight * window_stabilized["confidence"]
            for metric in (
                "goals_per_game",
                "shots_per_game",
                "goals_per_60",
                "shots_per_60",
                "pp_goals_per_60",
            ):
                recent_projection_components[metric] = (
                    recent_projection_components.get(metric, 0.0) + weight * window_stabilized[metric]
                )

        projection_weight = max(0.0, min(1.0, recent_confidence))
        row["recent_form_confidence"] = projection_weight
        row["projected_goals_per_game"] = (
            projection_weight * recent_projection_components["goals_per_game"]
            + (1.0 - projection_weight) * season_stabilized["goals_per_game"]
        )
        row["projected_shots_per_game"] = (
            projection_weight * recent_projection_components["shots_per_game"]
            + (1.0 - projection_weight) * season_stabilized["shots_per_game"]
        )
        row["projected_goals_per_60"] = (
            projection_weight * recent_projection_components["goals_per_60"]
            + (1.0 - projection_weight) * season_stabilized["goals_per_60"]
        )
        row["projected_shots_per_60"] = (
            projection_weight * recent_projection_components["shots_per_60"]
            + (1.0 - projection_weight) * season_stabilized["shots_per_60"]
        )
        row["projected_pp_goals_per_60"] = (
            projection_weight * recent_projection_components["pp_goals_per_60"]
            + (1.0 - projection_weight) * season_stabilized["pp_goals_per_60"]
        )

        matchup_team = (matchup_team_by_player or {}).get(player_id) or str(latest.get("opponent", "")).strip()
        row["matchup_opponent_team"] = matchup_team
        team_matchup = _build_matchup_history_features(
            rows=player_rows,
            baseline_goals_per_game=row["projected_goals_per_game"],
            baseline_shots_per_game=row["projected_shots_per_game"],
            filter_field="opponent",
            filter_value=matchup_team,
            prior_games=TEAM_MATCHUP_PRIOR_GAMES,
            max_influence=TEAM_MATCHUP_MAX_INFLUENCE,
        )
        row.update({f"vs_opponent_team_{key}": value for key, value in team_matchup.items()})

        matchup_goalie = (matchup_goalie_by_player or {}).get(player_id) or str(latest.get("opposing_goalie_id", "")).strip()
        row["matchup_opposing_goalie_id"] = matchup_goalie
        goalie_matchup = _build_matchup_history_features(
            rows=player_rows,
            baseline_goals_per_game=row["projected_goals_per_game"],
            baseline_shots_per_game=row["projected_shots_per_game"],
            filter_field="opposing_goalie_id",
            filter_value=matchup_goalie,
            prior_games=GOALIE_MATCHUP_PRIOR_GAMES,
            max_influence=GOALIE_MATCHUP_MAX_INFLUENCE,
        )
        row.update({f"vs_opposing_goalie_{key}": value for key, value in goalie_matchup.items()})

        row["projection_market_ready_anytime"] = True
        row["projection_market_ready_first_goal"] = True
        feature_rows.append(row)

    return sorted(feature_rows, key=lambda item: (item["team"], item["player_id"]))


def _is_model_eligible_game(row: dict[str, Any]) -> bool:
    game_type_code = _to_int(row.get("game_type_code"))
    return game_type_code in ELIGIBLE_GAME_TYPE_CODES


def _compute_rate_block(rows: list[dict[str, Any]]) -> dict[str, float]:
    games = float(len(rows))
    goals = float(sum(max(0, _to_int(row.get("goals"))) for row in rows))
    shots = float(sum(max(0, _to_int(row.get("shots"))) for row in rows))
    toi_minutes = float(sum(_to_minutes(row.get("time_on_ice")) for row in rows))
    pp_toi_minutes = float(sum(_to_minutes(row.get("power_play_time_on_ice")) for row in rows))
    pp_goals = float(sum(max(0, _to_int(row.get("power_play_goals"))) for row in rows))

    return {
        "games": games,
        "goals": goals,
        "shots": shots,
        "goals_per_game": (goals / games) if games > 0 else 0.0,
        "shots_per_game": (shots / games) if games > 0 else 0.0,
        "goals_per_60": (goals * 60.0 / toi_minutes) if toi_minutes > 0 else 0.0,
        "shots_per_60": (shots * 60.0 / toi_minutes) if toi_minutes > 0 else 0.0,
        "pp_toi_minutes_per_game": (pp_toi_minutes / games) if games > 0 else 0.0,
        "pp_goals_per_60": (pp_goals * 60.0 / pp_toi_minutes) if pp_toi_minutes > 0 else 0.0,
        "toi_minutes": toi_minutes,
        "pp_toi_minutes": pp_toi_minutes,
    }


def _build_league_baseline(rows: list[dict[str, Any]]) -> dict[str, float]:
    observed = _compute_rate_block(rows)
    confidence = min(1.0, observed["games"] / 5000.0)
    return {
        **observed,
        "goals_per_game": _blend(observed["goals_per_game"], DEFAULT_LEAGUE_BASELINE["goals_per_game"], confidence),
        "shots_per_game": _blend(observed["shots_per_game"], DEFAULT_LEAGUE_BASELINE["shots_per_game"], confidence),
        "goals_per_60": _blend(observed["goals_per_60"], DEFAULT_LEAGUE_BASELINE["goals_per_60"], confidence),
        "shots_per_60": _blend(observed["shots_per_60"], DEFAULT_LEAGUE_BASELINE["shots_per_60"], confidence),
        "pp_goals_per_60": _blend(observed["pp_goals_per_60"], DEFAULT_LEAGUE_BASELINE["pp_goals_per_60"], confidence),
    }


def _stabilize_season_block(season_block: dict[str, float], league_block: dict[str, float]) -> dict[str, float]:
    games_conf = min(1.0, season_block["games"] / 25.0)
    shots_conf = min(1.0, season_block["shots"] / 70.0)
    toi_conf = min(1.0, season_block["toi_minutes"] / 320.0)
    pp_toi_conf = min(1.0, season_block["pp_toi_minutes"] / 45.0)
    confidence = (0.45 * games_conf) + (0.35 * shots_conf) + (0.20 * toi_conf)

    return {
        "goals_per_game": _blend(season_block["goals_per_game"], league_block["goals_per_game"], confidence),
        "shots_per_game": _blend(season_block["shots_per_game"], league_block["shots_per_game"], confidence),
        "goals_per_60": _blend(season_block["goals_per_60"], league_block["goals_per_60"], confidence),
        "shots_per_60": _blend(season_block["shots_per_60"], league_block["shots_per_60"], confidence),
        "pp_goals_per_60": _blend(season_block["pp_goals_per_60"], league_block["pp_goals_per_60"], pp_toi_conf),
        "confidence": confidence,
    }


def _stabilize_recent_block(recent_block: dict[str, float], season_stabilized: dict[str, float]) -> dict[str, float]:
    games_conf = min(1.0, recent_block["games"] / 8.0)
    shots_conf = min(1.0, recent_block["shots"] / 24.0)
    toi_conf = min(1.0, recent_block["toi_minutes"] / 140.0)
    pp_toi_conf = min(1.0, recent_block["pp_toi_minutes"] / 18.0)
    confidence = (0.45 * games_conf) + (0.35 * shots_conf) + (0.20 * toi_conf)

    return {
        "goals_per_game": _blend(recent_block["goals_per_game"], season_stabilized["goals_per_game"], confidence),
        "shots_per_game": _blend(recent_block["shots_per_game"], season_stabilized["shots_per_game"], confidence),
        "goals_per_60": _blend(recent_block["goals_per_60"], season_stabilized["goals_per_60"], confidence),
        "shots_per_60": _blend(recent_block["shots_per_60"], season_stabilized["shots_per_60"], confidence),
        "pp_goals_per_60": _blend(recent_block["pp_goals_per_60"], season_stabilized["pp_goals_per_60"], pp_toi_conf),
        "confidence": confidence,
    }


def _parse_game_date(raw_value: Any) -> date | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _to_int(raw_value: Any) -> int:
    if raw_value is None:
        return 0
    value = str(raw_value).strip()
    if not value:
        return 0
    try:
        return int(float(value))
    except ValueError:
        return 0


def _to_minutes(raw_value: Any) -> float:
    value = str(raw_value or "").strip()
    if not value:
        return 0.0
    if ":" not in value:
        try:
            return float(value)
        except ValueError:
            return 0.0
    minutes_str, seconds_str = value.split(":", maxsplit=1)
    try:
        minutes = float(minutes_str)
        seconds = float(seconds_str)
    except ValueError:
        return 0.0
    return minutes + (seconds / 60.0)


def _blend(primary: float, baseline: float, confidence: float) -> float:
    weight = max(0.0, min(1.0, confidence))
    return (weight * primary) + ((1.0 - weight) * baseline)


def _build_matchup_history_features(
    *,
    rows: list[dict[str, Any]],
    baseline_goals_per_game: float,
    baseline_shots_per_game: float,
    filter_field: str,
    filter_value: str,
    prior_games: float,
    max_influence: float,
) -> dict[str, float | bool]:
    key = str(filter_value).strip()
    if not key:
        return {
            "available": False,
            "games": 0.0,
            "goals": 0.0,
            "shots": 0.0,
            "goals_per_game": 0.0,
            "shots_per_game": 0.0,
            "goals_per_game_stabilized": baseline_goals_per_game,
            "shots_per_game_stabilized": baseline_shots_per_game,
            "confidence": 0.0,
            "goals_rate_modifier": 1.0,
            "shots_rate_modifier": 1.0,
        }

    matchup_rows = [row for row in rows if str(row.get(filter_field, "")).strip() == key]
    block = _compute_rate_block(matchup_rows)
    empirical_confidence = block["games"] / (block["games"] + prior_games) if block["games"] > 0 else 0.0
    confidence = max_influence * empirical_confidence
    goals_stabilized = _blend(block["goals_per_game"], baseline_goals_per_game, confidence)
    shots_stabilized = _blend(block["shots_per_game"], baseline_shots_per_game, confidence)

    return {
        "available": block["games"] > 0,
        "games": block["games"],
        "goals": block["goals"],
        "shots": block["shots"],
        "goals_per_game": block["goals_per_game"],
        "shots_per_game": block["shots_per_game"],
        "goals_per_game_stabilized": goals_stabilized,
        "shots_per_game_stabilized": shots_stabilized,
        "confidence": confidence,
        "goals_rate_modifier": _rate_modifier(stabilized=goals_stabilized, baseline=baseline_goals_per_game, max_abs_delta=0.25),
        "shots_rate_modifier": _rate_modifier(stabilized=shots_stabilized, baseline=baseline_shots_per_game, max_abs_delta=0.3),
    }


def _rate_modifier(*, stabilized: float, baseline: float, max_abs_delta: float) -> float:
    if baseline <= 0:
        return 1.0
    raw = (stabilized / baseline) - 1.0
    clamped = max(-max_abs_delta, min(max_abs_delta, raw))
    return 1.0 + clamped
