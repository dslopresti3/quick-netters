from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

NHL_WEB_BASE = "https://api-web.nhle.com/v1"
NHL_SCHEDULE_SEASON_TIMEOUT_SECONDS = 20
INCLUDED_GAME_TYPES = {2, 3}
FINAL_STATES = {"FINAL", "OFF"}
BROWSER_LIKE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://www.nhl.com/",
    "Origin": "https://www.nhl.com",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


@dataclass(slots=True)
class HistoricalGameRecord:
    season: str
    game_id: str
    game_date: str
    game_type: str
    game_type_code: int
    home_team: str
    away_team: str
    home_score: int | None
    away_score: int | None
    final_state: str | None
    is_final: bool
    venue: str | None
    neutral_site: bool | None
    start_time_utc: str | None
    game_schedule_state: str | None
    source_endpoint: str
    ingested_at_utc: str

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


def ingest_historical_games(
    *,
    output_csv_path: Path,
    raw_snapshot_root: Path,
    season_keys: list[str],
) -> dict[str, Any]:
    existing_rows = _load_existing_games(output_csv_path)
    upserts = 0
    excluded_preseason = 0
    included_regular = 0
    included_postseason = 0

    ingested_at_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    seasons_with_data: list[str] = []

    for season_key in season_keys:
        endpoint = f"{NHL_WEB_BASE}/schedule-season/{season_key}"
        payload = fetch_json(url=endpoint, timeout_seconds=NHL_SCHEDULE_SEASON_TIMEOUT_SECONDS)
        _write_snapshot(raw_snapshot_root=raw_snapshot_root, season_key=season_key, payload=payload)

        season_games = _extract_schedule_games(payload)
        for game in season_games:
            game_type_code = _parse_game_type_code(game)
            if game_type_code == 1:
                excluded_preseason += 1

        normalized = _normalize_schedule_games(
            season_key=season_key,
            endpoint=endpoint,
            games=season_games,
            ingested_at_utc=ingested_at_utc,
        )
        if normalized:
            seasons_with_data.append(season_key)

        for record in normalized:
            if record.game_type_code == 2:
                included_regular += 1
            elif record.game_type_code == 3:
                included_postseason += 1
            key = (record.season, record.game_id)
            previous = existing_rows.get(key)
            row = record.to_row()
            if previous is not None and previous.get("ingested_at_utc"):
                row["ingested_at_utc"] = previous["ingested_at_utc"]
            existing_rows[key] = row
            if not _rows_equivalent(previous, existing_rows[key]):
                upserts += 1

    merged_rows = sorted(existing_rows.values(), key=lambda row: (row["season"], row["game_date"], row["game_id"]))
    _write_csv(output_csv_path, merged_rows)

    return {
        "seasons_requested": season_keys,
        "seasons_with_data": seasons_with_data,
        "upserts": upserts,
        "total_rows": len(merged_rows),
        "included_regular_season_games": included_regular,
        "included_postseason_games": included_postseason,
        "excluded_preseason_games": excluded_preseason,
        "output_csv_path": str(output_csv_path),
    }


def discover_supported_season_keys(
    *,
    start_year: int,
    end_year: int,
) -> list[str]:
    season_keys: list[str] = []
    for year in range(start_year, end_year + 1):
        season_key = _season_key_from_start_year(year)
        endpoint = f"{NHL_WEB_BASE}/schedule-season/{season_key}"
        try:
            payload = fetch_json(url=endpoint, timeout_seconds=8)
        except (HTTPError, URLError, TimeoutError, ValueError):
            continue
        games = _extract_schedule_games(payload)
        if any(_parse_game_type_code(game) in INCLUDED_GAME_TYPES for game in games):
            season_keys.append(season_key)
    return season_keys


def season_keys_from_args(*, season: str | None, season_start: int | None, season_end: int | None) -> list[str]:
    if season:
        return [season]
    if season_start is not None and season_end is not None:
        if season_end < season_start:
            raise ValueError("--season-end must be greater than or equal to --season-start")
        return [_season_key_from_start_year(year) for year in range(season_start, season_end + 1)]
    raise ValueError("Provide either --season, --season-start/--season-end, or --all-supported")


def _normalize_schedule_games(
    *,
    season_key: str,
    endpoint: str,
    games: list[dict[str, Any]],
    ingested_at_utc: str,
) -> list[HistoricalGameRecord]:
    normalized: list[HistoricalGameRecord] = []
    for game in games:
        game_type_code = _parse_game_type_code(game)
        if game_type_code not in INCLUDED_GAME_TYPES:
            continue

        game_id_raw = game.get("id")
        game_id = str(game_id_raw).strip() if game_id_raw is not None else ""
        if not game_id:
            continue

        start_time_utc = _as_non_empty_string(game.get("startTimeUTC"))
        game_date = _game_date_from_start_time(start_time_utc)
        if game_date is None:
            game_date = _as_non_empty_string(game.get("gameDate")) or ""

        home_team = _extract_team_name(game.get("homeTeam"))
        away_team = _extract_team_name(game.get("awayTeam"))

        home_score = _to_int_or_none(game.get("homeTeam", {}).get("score") if isinstance(game.get("homeTeam"), dict) else None)
        away_score = _to_int_or_none(game.get("awayTeam", {}).get("score") if isinstance(game.get("awayTeam"), dict) else None)

        final_state = _as_non_empty_string(game.get("gameState"))
        is_final = (final_state or "").upper() in FINAL_STATES

        normalized.append(
            HistoricalGameRecord(
                season=_season_from_game_or_default(game, season_key),
                game_id=game_id,
                game_date=game_date,
                game_type=_game_type_label(game_type_code),
                game_type_code=game_type_code,
                home_team=home_team,
                away_team=away_team,
                home_score=home_score,
                away_score=away_score,
                final_state=final_state,
                is_final=is_final,
                venue=_as_non_empty_string(game.get("venue", {}).get("default") if isinstance(game.get("venue"), dict) else game.get("venue")),
                neutral_site=_to_bool_or_none(game.get("neutralSite")),
                start_time_utc=start_time_utc,
                game_schedule_state=_as_non_empty_string(game.get("gameScheduleState")),
                source_endpoint=endpoint,
                ingested_at_utc=ingested_at_utc,
            )
        )
    return normalized


def _season_from_game_or_default(game: dict[str, Any], season_key: str) -> str:
    for field in ("season", "seasonId"):
        raw = game.get(field)
        if isinstance(raw, int):
            return str(raw)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return season_key


def _extract_schedule_games(payload: dict[str, Any]) -> list[dict[str, Any]]:
    game_weeks = payload.get("gameWeek")
    if isinstance(game_weeks, list):
        extracted: list[dict[str, Any]] = []
        for week in game_weeks:
            if not isinstance(week, dict):
                continue
            week_games = week.get("games")
            if not isinstance(week_games, list):
                continue
            for game in week_games:
                if isinstance(game, dict):
                    extracted.append(game)
        return extracted

    games = payload.get("games")
    if isinstance(games, list):
        return [game for game in games if isinstance(game, dict)]
    return []


def _parse_game_type_code(game: dict[str, Any]) -> int | None:
    for field in ("gameType", "gameTypeId"):
        raw = game.get(field)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str):
            normalized = raw.strip().upper()
            if normalized.isdigit():
                return int(normalized)
            if normalized in {"R", "REG", "REGULAR", "REGULAR_SEASON"}:
                return 2
            if normalized in {"P", "PO", "POST", "POSTSEASON", "PLAYOFF", "PLAYOFFS"}:
                return 3
            if normalized in {"PR", "PRE", "PRESEASON"}:
                return 1
    return None


def _game_type_label(game_type_code: int) -> str:
    if game_type_code == 2:
        return "regular_season"
    if game_type_code == 3:
        return "postseason"
    if game_type_code == 1:
        return "preseason"
    return "unknown"


def _extract_team_name(team_payload: Any) -> str:
    if not isinstance(team_payload, dict):
        return ""
    common_name = team_payload.get("commonName")
    if isinstance(common_name, dict):
        default_name = common_name.get("default")
        if isinstance(default_name, str) and default_name.strip():
            return default_name.strip()
    place_name = team_payload.get("placeName")
    place_default = place_name.get("default") if isinstance(place_name, dict) else ""
    common_default = common_name.get("default") if isinstance(common_name, dict) else ""
    combined = f"{place_default} {common_default}".strip()
    return combined


def _game_date_from_start_time(start_time_utc: str | None) -> str | None:
    if not start_time_utc:
        return None
    try:
        parsed = datetime.fromisoformat(start_time_utc.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.date().isoformat()


def _as_non_empty_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _to_int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return None


def _to_bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None


def _write_snapshot(*, raw_snapshot_root: Path, season_key: str, payload: dict[str, Any]) -> None:
    snapshot_path = raw_snapshot_root / f"season={season_key}" / "schedule_season.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _load_existing_games(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: dict[tuple[str, str], dict[str, Any]] = {}
        for row in reader:
            season = str(row.get("season", "")).strip()
            game_id = str(row.get("game_id", "")).strip()
            if not season or not game_id:
                continue
            rows[(season, game_id)] = row
        return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _season_key_from_start_year(start_year: int) -> str:
    return f"{start_year}{start_year + 1}"


def _rows_equivalent(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    keys = set(previous.keys()) | set(current.keys())
    for key in keys:
        previous_value = _normalized_compare_value(previous.get(key))
        current_value = _normalized_compare_value(current.get(key))
        if previous_value != current_value:
            return False
    return True


def _normalized_compare_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def fetch_json(*, url: str, timeout_seconds: int) -> dict[str, Any]:
    request = Request(url=url, headers=dict(BROWSER_LIKE_HEADERS))
    opener = build_opener(ProxyHandler({}))
    with opener.open(request, timeout=timeout_seconds) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object from {url}, got {type(payload).__name__}.")
    return payload
