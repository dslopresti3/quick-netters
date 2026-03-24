from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError

from app.api.schemas import GameSummary
from app.services.http_client import BROWSER_LIKE_HEADERS, build_no_proxy_opener, fetch_json
from app.services.interfaces import OddsProvider, PlayerProjectionCandidate, ProjectionProvider, ScheduleProvider
from app.services.odds import NormalizedPlayerOdds

logger = logging.getLogger(__name__)

class NhlScheduleProvider(ScheduleProvider):
    """Fetch NHL schedule data from the official public NHL API."""

    base_url = "https://api-web.nhle.com/v1/schedule"

    def __init__(self) -> None:
        self.last_fetch_error: str | None = None
        self._cache_by_date: dict[date, list[GameSummary]] = {}

    def fetch(self, selected_date: date) -> list[GameSummary]:
        cached = self._cache_by_date.get(selected_date)
        if cached is not None:
            logger.info(
                "NHL schedule cache hit",
                extra={"selected_date": selected_date.isoformat(), "cached_games_count": len(cached)},
            )
            return [game.model_copy(deep=True) for game in cached]

        self.last_fetch_error = None
        url = f"{self.base_url}/{selected_date.isoformat()}"
        headers = dict(BROWSER_LIKE_HEADERS)
        opener = build_no_proxy_opener()
        fetch_started = perf_counter()
        logger.info(
            "Fetching NHL schedule",
            extra={
                "selected_date": selected_date.isoformat(),
                "url": url,
                "headers": headers,
                "proxy_mode": "disabled",
            },
        )
        try:
            payload = fetch_json(url=url, headers=headers, timeout_seconds=10, opener=opener)
            fetch_elapsed_ms = round((perf_counter() - fetch_started) * 1000, 2)
            logger.info(
                "NHL schedule JSON parse status",
                extra={
                    "selected_date": selected_date.isoformat(),
                    "url": url,
                    "json_parse_succeeded": True,
                    "schedule_fetch_elapsed_ms": fetch_elapsed_ms,
                },
            )
            logger.info(
                "NHL upstream raw schedule response",
                extra={"selected_date": selected_date.isoformat(), "raw_payload": payload},
            )
            extracted_games = _extract_games(payload)
            logger.info(
                "NHL extracted games count",
                extra={
                    "selected_date": selected_date.isoformat(),
                    "url": url,
                    "extracted_games_count": len(extracted_games),
                },
            )
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            fetch_elapsed_ms = round((perf_counter() - fetch_started) * 1000, 2)
            self.last_fetch_error = f"NHL schedule fetch failed for {selected_date.isoformat()} from {url}: {exc}"
            logger.warning(
                "NHL schedule fetch failed",
                extra={
                    "selected_date": selected_date.isoformat(),
                    "url": url,
                    "error": str(exc),
                    "json_parse_succeeded": False,
                    "schedule_fetch_error_note": self.last_fetch_error,
                    "schedule_fetch_elapsed_ms": fetch_elapsed_ms,
                },
            )
            return []

        mapped = _map_schedule_payload(payload, selected_date=selected_date)
        self._cache_by_date[selected_date] = [game.model_copy(deep=True) for game in mapped]
        return mapped

def _map_schedule_payload(payload: dict[str, Any], selected_date: date | None = None) -> list[GameSummary]:
    extracted_games = _extract_games(payload)
    logger.info("Extracted upstream games before filtering", extra={"games": extracted_games})

    if selected_date is not None:
        date_filtered_games = [game for game in extracted_games if _matches_selected_schedule_window(game, selected_date)]
        logger.info(
            "Extracted upstream games after date filtering",
            extra={
                "selected_date": selected_date.isoformat(),
                "total_extracted_games": len(extracted_games),
                "games_matching_date": len(date_filtered_games),
            },
        )
    else:
        date_filtered_games = extracted_games

    game_summaries: list[GameSummary] = []
    for game in date_filtered_games:
        summary = _map_game(game)
        if summary is not None:
            game_summaries.append(summary)

    logger.info("Final mapped internal game objects", extra={"mapped_games": [game.model_dump(mode="json") for game in game_summaries]})

    return game_summaries


def _extract_games(payload: dict[str, Any]) -> list[dict[str, Any]]:
    game_weeks = payload.get("gameWeek")
    if isinstance(game_weeks, list):
        extracted: list[dict[str, Any]] = []
        for week in game_weeks:
            if not isinstance(week, dict):
                continue
            week_date = week.get("date")
            games = week.get("games")
            if not isinstance(games, list):
                continue
            for game in games:
                if not isinstance(game, dict):
                    continue
                if isinstance(week_date, str) and "_weekDate" not in game:
                    game = {**game, "_weekDate": week_date}
                extracted.append(game)
        return extracted

    games = payload.get("games")
    if isinstance(games, list):
        return [game for game in games if isinstance(game, dict)]

    return []    

def _matches_selected_schedule_window(game: dict[str, Any], selected_date: date) -> bool:
    game_date = _parse_date_hint(game.get("gameDate"))
    if game_date is not None:
        return game_date == selected_date

    week_date = _parse_date_hint(game.get("_weekDate"))
    start_time_utc = game.get("startTimeUTC")
    start_time_date = None
    if isinstance(start_time_utc, str):
        try:
            start_time_date = _parse_utc_datetime(start_time_utc).date()
        except ValueError:
            start_time_date = None

    if week_date is not None:
        if week_date != selected_date:
            return False
        if start_time_date is None:
            return True
        return start_time_date == selected_date

    if start_time_date is None:
        return False
    return start_time_date == selected_date


def _extract_game_hint_dates(game: dict[str, Any]) -> tuple[set[date], set[date]]:
    primary_hints: set[date] = set()
    secondary_hints: set[date] = set()
    parsed_game_date = _parse_date_hint(game.get("gameDate"))
    if parsed_game_date is not None:
        primary_hints.add(parsed_game_date)

    start_time_utc = game.get("startTimeUTC")
    if isinstance(start_time_utc, str):
        parsed_start = _parse_start_time_hint(start_time_utc)
        if parsed_start is not None:
            primary_hints.add(parsed_start)

    parsed_week_date = _parse_date_hint(game.get("_weekDate"))
    if parsed_week_date is not None:
        secondary_hints.add(parsed_week_date)
    return primary_hints, secondary_hints


def _parse_date_hint(raw_hint: Any) -> date | None:
    if not isinstance(raw_hint, str) or len(raw_hint) < 10:
        return None
    try:
        return date.fromisoformat(raw_hint[:10])
    except ValueError:
        return None


def _parse_start_time_hint(raw_start_time: str) -> date | None:
    try:
        parsed = _parse_utc_datetime(raw_start_time)
    except ValueError:
        return None
    return parsed.date()


def _map_game(game: dict[str, Any]) -> GameSummary | None:
    try:
        game_id = str(game["id"])
        start_time_utc = game["startTimeUTC"]
        away_team_name = game["awayTeam"]["commonName"]["default"]
        home_team_name = game["homeTeam"]["commonName"]["default"]
    except (KeyError, TypeError):
        return None

    if not isinstance(start_time_utc, str):
        return None

    try:
        game_time = _parse_utc_datetime(start_time_utc)
    except ValueError:
        return None

    status = _extract_status(game)
    return GameSummary(
        game_id=game_id,
        game_time=game_time,
        away_team=away_team_name,
        home_team=home_team_name,
        status=status,
    )


def _parse_utc_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_status(game: dict[str, Any]) -> str | None:
    game_state = game.get("gameState")
    if isinstance(game_state, str) and game_state:
        return game_state
    schedule_state = game.get("gameScheduleState")
    if isinstance(schedule_state, str) and schedule_state:
        return schedule_state
    return None


class EmptyScheduleProvider(ScheduleProvider):
    """Fallback no-op schedule provider."""

    def fetch(self, selected_date: date) -> list[GameSummary]:
        return []


class EmptyProjectionProvider(ProjectionProvider):
    """Production wiring placeholder until model projection integration is added."""

    def fetch_player_first_goal_projections(self, selected_date: date) -> list[PlayerProjectionCandidate]:
        return []


class EmptyOddsProvider(OddsProvider):
    """Production wiring placeholder until live odds integration is added."""

    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        return []
