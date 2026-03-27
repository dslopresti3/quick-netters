from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .nhl_games_ingestion import NHL_WEB_BASE, fetch_json

INCLUDED_GAME_TYPES = {2, 3}
NHL_GAMECENTER_TIMEOUT_SECONDS = 20


@dataclass(slots=True)
class HistoricalPlayerGameRecord:
    season: str
    game_date: str
    game_id: str
    game_type: str
    game_type_code: int
    player_id: str
    player_name: str
    team: str
    opponent: str
    home_or_away: str
    goals: int | None
    shots: int | None
    time_on_ice: str | None
    power_play_time_on_ice: str | None
    points: int | None
    assists: int | None
    plus_minus: int | None
    pim: int | None
    hits: int | None
    blocked_shots: int | None
    faceoff_wins: int | None
    faceoff_taken: int | None
    power_play_goals: int | None
    power_play_points: int | None
    shorthanded_goals: int | None
    shorthanded_points: int | None
    shooting_pct: float | None
    opposing_goalie_id: str | None
    opposing_goalie_name: str | None
    opposing_goalie_is_starter: bool | None
    source_endpoint: str
    ingested_at_utc: str

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


def ingest_historical_player_games(
    *,
    games_csv_path: Path,
    output_csv_path: Path,
    raw_snapshot_root: Path,
    season_keys: list[str] | None = None,
) -> dict[str, Any]:
    selected_seasons = {season.strip() for season in season_keys or [] if season.strip()}
    historical_games = _load_historical_games(games_csv_path=games_csv_path, season_filter=selected_seasons or None)

    existing_rows = _load_existing_player_games(output_csv_path)
    upserts = 0
    rows_written = 0
    games_processed = 0

    ingested_at_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    for game in historical_games:
        endpoint = f"{NHL_WEB_BASE}/gamecenter/{game['game_id']}/boxscore"
        payload = fetch_json(url=endpoint, timeout_seconds=NHL_GAMECENTER_TIMEOUT_SECONDS)
        _write_snapshot(
            raw_snapshot_root=raw_snapshot_root,
            season=game["season"],
            game_id=game["game_id"],
            payload=payload,
        )
        player_rows = _normalize_player_games(
            game=game,
            endpoint=endpoint,
            payload=payload,
            ingested_at_utc=ingested_at_utc,
        )

        games_processed += 1
        for record in player_rows:
            key = (record.season, record.game_id, record.player_id)
            previous = existing_rows.get(key)
            row = record.to_row()
            if previous is not None and previous.get("ingested_at_utc"):
                row["ingested_at_utc"] = previous["ingested_at_utc"]
            existing_rows[key] = row
            if not _rows_equivalent(previous, existing_rows[key]):
                upserts += 1
            rows_written += 1

    merged_rows = sorted(
        existing_rows.values(),
        key=lambda row: (row["season"], row["game_date"], row["game_id"], row["player_id"]),
    )
    _write_csv(output_csv_path, merged_rows)

    return {
        "games_csv_path": str(games_csv_path),
        "output_csv_path": str(output_csv_path),
        "raw_snapshot_root": str(raw_snapshot_root),
        "season_filter": sorted(selected_seasons),
        "games_scanned": len(historical_games),
        "games_processed": games_processed,
        "player_rows_seen": rows_written,
        "total_rows": len(merged_rows),
        "upserts": upserts,
    }


def _load_historical_games(*, games_csv_path: Path, season_filter: set[str] | None) -> list[dict[str, str]]:
    if not games_csv_path.exists():
        raise FileNotFoundError(
            f"Historical games CSV not found at {games_csv_path}. Run historical game ingestion first."
        )

    with games_csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    filtered: list[dict[str, str]] = []
    for row in rows:
        season = str(row.get("season", "")).strip()
        game_id = str(row.get("game_id", "")).strip()
        if not season or not game_id:
            continue
        if season_filter is not None and season not in season_filter:
            continue

        game_type_code = _to_int_or_none(row.get("game_type_code"))
        if game_type_code not in INCLUDED_GAME_TYPES:
            continue

        filtered.append(
            {
                "season": season,
                "game_date": str(row.get("game_date", "")).strip(),
                "game_id": game_id,
                "game_type": str(row.get("game_type", "")).strip(),
                "game_type_code": str(game_type_code),
                "home_team": str(row.get("home_team", "")).strip(),
                "away_team": str(row.get("away_team", "")).strip(),
            }
        )
    return filtered


def _normalize_player_games(
    *,
    game: dict[str, str],
    endpoint: str,
    payload: dict[str, Any],
    ingested_at_utc: str,
) -> list[HistoricalPlayerGameRecord]:
    away_payload = payload.get("awayTeam") if isinstance(payload.get("awayTeam"), dict) else {}
    home_payload = payload.get("homeTeam") if isinstance(payload.get("homeTeam"), dict) else {}

    away_team = game["away_team"] or _team_label(away_payload)
    home_team = game["home_team"] or _team_label(home_payload)

    player_stats = payload.get("playerByGameStats")
    if not isinstance(player_stats, dict):
        return []

    goalie_lookup = _build_goalie_lookup(player_stats)
    away_starter_id = _starter_goalie_id(away_payload)
    home_starter_id = _starter_goalie_id(home_payload)

    normalized: list[HistoricalPlayerGameRecord] = []
    normalized.extend(
        _collect_side_players(
            side_key="awayTeam",
            team=away_team,
            opponent=home_team,
            home_or_away="away",
            game=game,
            endpoint=endpoint,
            ingested_at_utc=ingested_at_utc,
            player_stats=player_stats,
            opposing_goalie_id=home_starter_id,
            opposing_goalie_name=goalie_lookup.get(home_starter_id or ""),
            opposing_goalie_is_starter=True if home_starter_id else None,
        )
    )
    normalized.extend(
        _collect_side_players(
            side_key="homeTeam",
            team=home_team,
            opponent=away_team,
            home_or_away="home",
            game=game,
            endpoint=endpoint,
            ingested_at_utc=ingested_at_utc,
            player_stats=player_stats,
            opposing_goalie_id=away_starter_id,
            opposing_goalie_name=goalie_lookup.get(away_starter_id or ""),
            opposing_goalie_is_starter=True if away_starter_id else None,
        )
    )
    return normalized


def _collect_side_players(
    *,
    side_key: str,
    team: str,
    opponent: str,
    home_or_away: str,
    game: dict[str, str],
    endpoint: str,
    ingested_at_utc: str,
    player_stats: dict[str, Any],
    opposing_goalie_id: str | None,
    opposing_goalie_name: str | None,
    opposing_goalie_is_starter: bool | None,
) -> list[HistoricalPlayerGameRecord]:
    side_payload = player_stats.get(side_key)
    if not isinstance(side_payload, dict):
        return []

    seen_player_ids: set[str] = set()
    rows: list[HistoricalPlayerGameRecord] = []
    for bucket_key in ("forwards", "defense", "goalies", "skaters", "players"):
        bucket = side_payload.get(bucket_key)
        if not isinstance(bucket, list):
            continue
        for raw_row in bucket:
            if not isinstance(raw_row, dict):
                continue
            player_id = _player_id(raw_row)
            if not player_id or player_id in seen_player_ids:
                continue
            seen_player_ids.add(player_id)
            rows.append(
                HistoricalPlayerGameRecord(
                    season=game["season"],
                    game_date=game["game_date"],
                    game_id=game["game_id"],
                    game_type=game["game_type"],
                    game_type_code=int(game["game_type_code"]),
                    player_id=player_id,
                    player_name=_player_name(raw_row, fallback=player_id),
                    team=team,
                    opponent=opponent,
                    home_or_away=home_or_away,
                    goals=_to_int_or_none(raw_row.get("goals")),
                    shots=_to_int_or_none(raw_row.get("shots")),
                    time_on_ice=_to_str_or_none(raw_row.get("toi") or raw_row.get("timeOnIce")),
                    power_play_time_on_ice=_to_str_or_none(
                        raw_row.get("powerPlayToi") or raw_row.get("powerPlayTimeOnIce") or raw_row.get("ppToi")
                    ),
                    points=_to_int_or_none(raw_row.get("points")),
                    assists=_to_int_or_none(raw_row.get("assists")),
                    plus_minus=_to_int_or_none(raw_row.get("plusMinus")),
                    pim=_to_int_or_none(raw_row.get("pim")),
                    hits=_to_int_or_none(raw_row.get("hits")),
                    blocked_shots=_to_int_or_none(raw_row.get("blockedShots")),
                    faceoff_wins=_to_int_or_none(raw_row.get("faceoffWinningPctg") or raw_row.get("faceoffsWon")),
                    faceoff_taken=_to_int_or_none(raw_row.get("faceoffs")),
                    power_play_goals=_to_int_or_none(raw_row.get("powerPlayGoals")),
                    power_play_points=_to_int_or_none(raw_row.get("powerPlayPoints")),
                    shorthanded_goals=_to_int_or_none(raw_row.get("shortHandedGoals")),
                    shorthanded_points=_to_int_or_none(raw_row.get("shortHandedPoints")),
                    shooting_pct=_to_float_or_none(raw_row.get("shootingPctg")),
                    opposing_goalie_id=opposing_goalie_id,
                    opposing_goalie_name=opposing_goalie_name,
                    opposing_goalie_is_starter=opposing_goalie_is_starter,
                    source_endpoint=endpoint,
                    ingested_at_utc=ingested_at_utc,
                )
            )
    return rows


def _build_goalie_lookup(player_stats: dict[str, Any]) -> dict[str, str]:
    goalie_lookup: dict[str, str] = {}
    for side_key in ("awayTeam", "homeTeam"):
        side_payload = player_stats.get(side_key)
        if not isinstance(side_payload, dict):
            continue
        goalies = side_payload.get("goalies")
        if not isinstance(goalies, list):
            continue
        for goalie in goalies:
            if not isinstance(goalie, dict):
                continue
            goalie_id = _player_id(goalie)
            if not goalie_id:
                continue
            goalie_lookup[goalie_id] = _player_name(goalie, fallback=goalie_id)
    return goalie_lookup


def _starter_goalie_id(team_payload: dict[str, Any]) -> str | None:
    for key in ("starter", "starterId", "startingGoalieId"):
        raw = team_payload.get(key)
        if raw is None:
            continue
        starter = str(raw).strip()
        if starter:
            return starter
    goalies = team_payload.get("goalies")
    if isinstance(goalies, list) and goalies:
        first = str(goalies[0]).strip()
        if first:
            return first
    return None


def _team_label(team_payload: dict[str, Any]) -> str:
    for key in ("abbrev", "name", "teamName", "commonName"):
        raw = team_payload.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        if isinstance(raw, dict):
            default_value = raw.get("default")
            if isinstance(default_value, str) and default_value.strip():
                return default_value.strip()
    return ""


def _player_id(raw_row: dict[str, Any]) -> str:
    for key in ("playerId", "id"):
        raw = raw_row.get(key)
        if raw is None:
            continue
        value = str(raw).strip()
        if value:
            return value
    return ""


def _player_name(raw_row: dict[str, Any], *, fallback: str) -> str:
    for key in ("name", "playerName", "fullName"):
        raw = raw_row.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        if isinstance(raw, dict):
            default_value = raw.get("default")
            if isinstance(default_value, str) and default_value.strip():
                return default_value.strip()
    first_name = raw_row.get("firstName")
    last_name = raw_row.get("lastName")
    if isinstance(first_name, dict):
        first_name = first_name.get("default")
    if isinstance(last_name, dict):
        last_name = last_name.get("default")
    if isinstance(first_name, str) and isinstance(last_name, str):
        full_name = f"{first_name.strip()} {last_name.strip()}".strip()
        if full_name:
            return full_name
    return fallback


def _load_existing_player_games(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in reader:
            season = str(row.get("season", "")).strip()
            game_id = str(row.get("game_id", "")).strip()
            player_id = str(row.get("player_id", "")).strip()
            if not season or not game_id or not player_id:
                continue
            rows[(season, game_id, player_id)] = row
        return rows


def _to_int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return int(float(normalized))
        except ValueError:
            return None
    return None


def _to_float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return float(normalized)
        except ValueError:
            return None
    return None


def _to_str_or_none(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _rows_equivalent(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    keys = set(previous.keys()) | set(current.keys())
    for key in keys:
        if _normalized_compare_value(previous.get(key)) != _normalized_compare_value(current.get(key)):
            return False
    return True


def _normalized_compare_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_snapshot(*, raw_snapshot_root: Path, season: str, game_id: str, payload: dict[str, Any]) -> None:
    snapshot_path = raw_snapshot_root / f"season={season}" / f"game_id={game_id}_boxscore.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
