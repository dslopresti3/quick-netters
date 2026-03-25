from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.services.http_client import fetch_json
from app.services.identity import team_alias_tokens
from app.services.interfaces import PlayerHistoricalProduction

NHL_WEB_BASE = "https://api-web.nhle.com/v1"
NHL_ROSTER_TIMEOUT_SECONDS = 8
NHL_PLAYER_HISTORY_TIMEOUT_SECONDS = 4
NHL_SCHEDULE_TIMEOUT_SECONDS = 8
NHL_PLAY_BY_PLAY_TIMEOUT_SECONDS = 12
_FIRST_GOAL_DERIVED_STORE_KEY = "historical_first_goal_tracking"

TEAM_NAME_TO_ABBREV = {
    "anaheim ducks": "ANA",
    "arizona coyotes": "ARI",
    "boston bruins": "BOS",
    "buffalo sabres": "BUF",
    "calgary flames": "CGY",
    "carolina hurricanes": "CAR",
    "chicago blackhawks": "CHI",
    "colorado avalanche": "COL",
    "columbus blue jackets": "CBJ",
    "dallas stars": "DAL",
    "detroit red wings": "DET",
    "edmonton oilers": "EDM",
    "florida panthers": "FLA",
    "los angeles kings": "LAK",
    "la kings": "LAK",
    "minnesota wild": "MIN",
    "montreal canadiens": "MTL",
    "nashville predators": "NSH",
    "new jersey devils": "NJD",
    "new york islanders": "NYI",
    "new york rangers": "NYR",
    "ny rangers": "NYR",
    "ottawa senators": "OTT",
    "philadelphia flyers": "PHI",
    "pittsburgh penguins": "PIT",
    "san jose sharks": "SJS",
    "seattle kraken": "SEA",
    "st. louis blues": "STL",
    "st louis blues": "STL",
    "tampa bay lightning": "TBL",
    "toronto maple leafs": "TOR",
    "utah hockey club": "UTA",
    "utah mammoth": "UTA",
    "vancouver canucks": "VAN",
    "vegas golden knights": "VGK",
    "washington capitals": "WSH",
    "winnipeg jets": "WPG",
}


TEAM_TOKEN_TO_ABBREV: dict[str, str] = {}
for _team_name, _abbrev in TEAM_NAME_TO_ABBREV.items():
    for _token in team_alias_tokens(_team_name):
        TEAM_TOKEN_TO_ABBREV.setdefault(_token, _abbrev)

@dataclass(frozen=True)
class NhlRosterPlayer:
    player_id: str
    player_name: str
    active_team_name: str
    position_code: str | None = None


def team_abbrev_for_name(team_name: str) -> str | None:
    normalized = team_name.strip().lower()
    if not normalized:
        return None

    direct = TEAM_NAME_TO_ABBREV.get(normalized)
    if direct is not None:
        return direct

    for token in team_alias_tokens(team_name):
        mapped = TEAM_TOKEN_TO_ABBREV.get(token)
        if mapped is not None:
            return mapped
    return None


def fetch_team_roster_current(team_abbrev: str) -> list[NhlRosterPlayer]:
    payload = fetch_json(
        url=f"{NHL_WEB_BASE}/roster/{team_abbrev}/current",
        timeout_seconds=NHL_ROSTER_TIMEOUT_SECONDS,
    )
    players = _extract_roster_players(payload)
    return [
        NhlRosterPlayer(
            player_id=player["player_id"],
            player_name=player["player_name"],
            active_team_name=player["active_team_name"],
            position_code=player.get("position_code"),
        )
        for player in players
    ]


def fetch_player_first_goal_history(player_id: str, selected_date: date) -> PlayerHistoricalProduction:
    season = _season_from_date(selected_date)
    payload = fetch_json(
        url=f"{NHL_WEB_BASE}/player/{player_id}/game-log/{season}/2",
        timeout_seconds=NHL_PLAYER_HISTORY_TIMEOUT_SECONDS,
    )
    game_log_rows = _extract_game_log_rows(payload)

    season_games_played = float(len(game_log_rows)) if game_log_rows else None
    first_goals = 0.0
    total_goals = 0.0
    total_shots = 0.0
    first_period_goals = 0.0
    first_period_shots = 0.0
    for row in game_log_rows:
        first_goals += _first_goal_value(row)
        total_goals += _numeric_value(row.get("goals"))
        total_shots += _numeric_value(row.get("shots"))
        first_period_goals += _numeric_value(row.get("firstPeriodGoals"))
        first_period_shots += _first_period_shots_value(row)

    recent_5_rows = game_log_rows[:5]
    recent_10_rows = game_log_rows[:10]
    recent_5_first_goals = sum(_first_goal_value(row) for row in recent_5_rows)
    recent_10_first_goals = sum(_first_goal_value(row) for row in recent_10_rows)
    recent_5_total_goals = sum(_numeric_value(row.get("goals")) for row in recent_5_rows)
    recent_10_total_goals = sum(_numeric_value(row.get("goals")) for row in recent_10_rows)
    recent_5_total_shots = sum(_numeric_value(row.get("shots")) for row in recent_5_rows)
    recent_10_total_shots = sum(_numeric_value(row.get("shots")) for row in recent_10_rows)
    recent_5_first_period_goals = sum(_numeric_value(row.get("firstPeriodGoals")) for row in recent_5_rows)
    recent_10_first_period_goals = sum(_numeric_value(row.get("firstPeriodGoals")) for row in recent_10_rows)
    recent_5_first_period_shots = sum(_first_period_shots_value(row) for row in recent_5_rows)
    recent_10_first_period_shots = sum(_first_period_shots_value(row) for row in recent_10_rows)

    if season_games_played is None:
        return PlayerHistoricalProduction()
    return PlayerHistoricalProduction(
        season_first_goals=first_goals,
        season_games_played=season_games_played,
        season_total_goals=total_goals,
        season_total_shots=total_shots,
        season_first_period_goals=first_period_goals,
        season_first_period_shots=first_period_shots,
        recent_5_first_goals=recent_5_first_goals,
        recent_10_first_goals=recent_10_first_goals,
        recent_5_total_goals=recent_5_total_goals,
        recent_10_total_goals=recent_10_total_goals,
        recent_5_total_shots=recent_5_total_shots,
        recent_10_total_shots=recent_10_total_shots,
        recent_5_first_period_goals=recent_5_first_period_goals,
        recent_10_first_period_goals=recent_10_first_period_goals,
        recent_5_first_period_shots=recent_5_first_period_shots,
        recent_10_first_period_shots=recent_10_first_period_shots,
    )


def refresh_incremental_first_goal_derived_data(selected_date: date, artifact_path: Path) -> None:
    payload = _load_projection_artifact_payload(artifact_path)
    store = _get_or_create_first_goal_store(payload, season=_season_from_date(selected_date))
    processed_game_ids_raw = store.get("processed_game_ids")
    if not isinstance(processed_game_ids_raw, list):
        processed_game_ids: set[str] = set()
    else:
        processed_game_ids = {str(game_id).strip() for game_id in processed_game_ids_raw if str(game_id).strip()}

    target_dates = [selected_date - timedelta(days=1), selected_date]
    newly_processed: list[str] = []
    for target_date in target_dates:
        schedule_payload = fetch_json(
            url=f"{NHL_WEB_BASE}/schedule/{target_date.isoformat()}",
            timeout_seconds=NHL_SCHEDULE_TIMEOUT_SECONDS,
        )
        for game in _extract_schedule_games(schedule_payload):
            if not _is_completed_game(game):
                continue
            game_id = str(game.get("id", "")).strip()
            if not game_id or game_id in processed_game_ids:
                continue
            pbp_payload = fetch_json(
                url=f"{NHL_WEB_BASE}/gamecenter/{game_id}/play-by-play",
                timeout_seconds=NHL_PLAY_BY_PLAY_TIMEOUT_SECONDS,
            )
            first_goal_scorer, first_period_scorers = _extract_first_goal_scorers_from_play_by_play(pbp_payload)
            _increment_player_counter(store, "player_first_goal_totals", first_goal_scorer)
            for scorer in first_period_scorers:
                _increment_player_counter(store, "player_first_period_goal_totals", scorer)
            processed_game_ids.add(game_id)
            newly_processed.append(game_id)

    if not newly_processed:
        return

    store["processed_game_ids"] = sorted(processed_game_ids)
    store["last_updated_on"] = selected_date.isoformat()
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_stored_first_goal_derived_history(
    *,
    selected_date: date,
    eligible_player_ids: set[str],
    artifact_path: Path,
) -> dict[str, PlayerHistoricalProduction]:
    if not eligible_player_ids:
        return {}
    payload = _load_projection_artifact_payload(artifact_path)
    by_season = payload.get(_FIRST_GOAL_DERIVED_STORE_KEY)
    if not isinstance(by_season, dict):
        return {}
    season_store = by_season.get(_season_from_date(selected_date))
    if not isinstance(season_store, dict):
        return {}

    first_goal_totals = _normalize_counter(season_store.get("player_first_goal_totals"))
    first_period_goal_totals = _normalize_counter(season_store.get("player_first_period_goal_totals"))
    history: dict[str, PlayerHistoricalProduction] = {}
    for player_id in eligible_player_ids:
        first_goals = first_goal_totals.get(player_id)
        first_period_goals = first_period_goal_totals.get(player_id)
        if first_goals is None and first_period_goals is None:
            continue
        history[player_id] = PlayerHistoricalProduction(
            season_first_goals=first_goals,
            season_first_period_goals=first_period_goals,
        )
    return history


def _extract_roster_players(payload: dict[str, Any]) -> list[dict[str, str]]:
    players: list[dict[str, str]] = []
    for team_key, group in payload.items():
        if not isinstance(group, list):
            continue
        for player in group:
            if not isinstance(player, dict):
                continue
            player_id_raw = player.get("id")
            if player_id_raw is None:
                continue
            player_id = str(player_id_raw).strip()
            if not player_id:
                continue
            first_name = _name_default(player.get("firstName"))
            last_name = _name_default(player.get("lastName"))
            full_name = f"{first_name} {last_name}".strip() or str(player.get("fullName", "")).strip()
            team_name = str(player.get("currentTeamAbbrev") or player.get("teamAbbrev") or team_key).strip()
            players.append(
                {
                    "player_id": player_id,
                    "player_name": full_name or player_id,
                    "active_team_name": team_name,
                    "position_code": _position_code(player),
                }
            )
    return players


def _extract_game_log_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("gameLog", "games", "playerGameLog"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _first_goal_value(row: dict[str, Any]) -> float:
    for key in ("firstGoals", "firstGoal"):
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, bool):
            return 1.0 if value else 0.0

    if bool(row.get("isFirstGoal")):
        return 1.0
    return 0.0


def _season_from_date(selected_date: date) -> str:
    start_year = selected_date.year if selected_date.month >= 9 else selected_date.year - 1
    return f"{start_year}{start_year + 1}"


def _name_default(raw_name: Any) -> str:
    if isinstance(raw_name, dict):
        default_name = raw_name.get("default")
        if isinstance(default_name, str):
            return default_name.strip()
    if isinstance(raw_name, str):
        return raw_name.strip()
    return ""


def _position_code(player: dict[str, Any]) -> str | None:
    for key in ("positionCode", "position", "positionAbbrev"):
        value = player.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return None


def _numeric_value(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _first_period_shots_value(row: dict[str, Any]) -> float:
    for key in ("firstPeriodShots", "shotsFirstPeriod", "period1Shots", "shotsInFirstPeriod"):
        if key in row:
            return _numeric_value(row.get(key))
    return 0.0


def _load_projection_artifact_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "projections": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": 1, "projections": []}
    if isinstance(payload, dict):
        return payload
    return {"schema_version": 1, "projections": []}


def _get_or_create_first_goal_store(payload: dict[str, Any], *, season: str) -> dict[str, Any]:
    by_season = payload.get(_FIRST_GOAL_DERIVED_STORE_KEY)
    if not isinstance(by_season, dict):
        by_season = {}
        payload[_FIRST_GOAL_DERIVED_STORE_KEY] = by_season
    store = by_season.get(season)
    if not isinstance(store, dict):
        store = {
            "processed_game_ids": [],
            "player_first_goal_totals": {},
            "player_first_period_goal_totals": {},
        }
        by_season[season] = store
    return store


def _extract_schedule_games(schedule_payload: dict[str, Any]) -> list[dict[str, Any]]:
    game_weeks = schedule_payload.get("gameWeek")
    if isinstance(game_weeks, list):
        games: list[dict[str, Any]] = []
        for week in game_weeks:
            if not isinstance(week, dict):
                continue
            week_games = week.get("games")
            if not isinstance(week_games, list):
                continue
            for game in week_games:
                if isinstance(game, dict):
                    games.append(game)
        return games
    games = schedule_payload.get("games")
    if isinstance(games, list):
        return [game for game in games if isinstance(game, dict)]
    return []


def _is_completed_game(game: dict[str, Any]) -> bool:
    state = str(game.get("gameState", "")).strip().upper()
    return state in {"FINAL", "OFF"}


def _extract_first_goal_scorers_from_play_by_play(payload: dict[str, Any]) -> tuple[str | None, list[str]]:
    plays = payload.get("plays")
    if not isinstance(plays, list):
        return None, []
    goal_events = [play for play in plays if isinstance(play, dict) and play.get("typeDescKey") == "goal"]
    if not goal_events:
        return None, []
    sorted_goals = sorted(goal_events, key=lambda play: int(play.get("sortOrder", 10**9)))
    first_goal_scorer: str | None = None
    first_period_scorers: list[str] = []
    for idx, goal in enumerate(sorted_goals):
        details = goal.get("details")
        if not isinstance(details, dict):
            continue
        scorer_raw = details.get("scoringPlayerId")
        scorer = str(scorer_raw).strip() if scorer_raw is not None else ""
        if not scorer:
            continue
        if idx == 0:
            first_goal_scorer = scorer
        period_number = _period_number(goal)
        if period_number == 1:
            first_period_scorers.append(scorer)
    return first_goal_scorer, first_period_scorers


def _period_number(play: dict[str, Any]) -> int | None:
    period_descriptor = play.get("periodDescriptor")
    if isinstance(period_descriptor, dict):
        raw = period_descriptor.get("number")
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.isdigit():
            return int(raw)
    raw_period = play.get("period")
    if isinstance(raw_period, int):
        return raw_period
    if isinstance(raw_period, str) and raw_period.isdigit():
        return int(raw_period)
    return None


def _increment_player_counter(store: dict[str, Any], field_name: str, player_id: str | None) -> None:
    if player_id is None or not player_id.strip():
        return
    counters = store.get(field_name)
    if not isinstance(counters, dict):
        counters = {}
        store[field_name] = counters
    current_value = counters.get(player_id)
    numeric_current = float(current_value) if isinstance(current_value, (int, float)) else 0.0
    counters[player_id] = numeric_current + 1.0


def _normalize_counter(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, float] = {}
    for key, value in raw.items():
        player_id = str(key).strip()
        if not player_id:
            continue
        if not isinstance(value, (int, float)):
            continue
        normalized[player_id] = float(value)
    return normalized
