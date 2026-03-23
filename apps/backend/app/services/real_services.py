from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from app.api.schemas import GameSummary
from app.services.interfaces import OddsProvider, ProjectionProvider, ScheduleProvider
from app.services.odds import NormalizedPlayerOdds

logger = logging.getLogger(__name__)


class NhlScheduleProvider(ScheduleProvider):
    """Fetch NHL schedule data from the official public NHL API."""

    base_url = "https://api-web.nhle.com/v1/schedule"

    def __init__(self) -> None:
        self.last_fetch_error: str | None = None

    def fetch(self, selected_date: date) -> list[GameSummary]:
        self.last_fetch_error = None
        url = f"{self.base_url}/{selected_date.isoformat()}"
        logger.info("Fetching NHL schedule", extra={"selected_date": selected_date.isoformat(), "url": url})
        try:
            with urlopen(url, timeout=10) as response:
                payload = json.load(response)
                logger.info(
                    "NHL upstream raw schedule response",
                    extra={"selected_date": selected_date.isoformat(), "raw_payload": payload},
                )
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            self.last_fetch_error = f"NHL schedule fetch failed for {selected_date.isoformat()} from {url}: {exc}"
            logger.warning(
                "NHL schedule fetch failed",
                extra={
                    "selected_date": selected_date.isoformat(),
                    "url": url,
                    "error": str(exc),
                    "schedule_fetch_error_note": self.last_fetch_error,
                },
            )
            return []

        return _map_schedule_payload(payload, selected_date=selected_date)


def _map_schedule_payload(payload: dict[str, Any], selected_date: date | None = None) -> list[GameSummary]:
    extracted_games = _extract_games(payload)
    logger.info("Extracted upstream games before filtering", extra={"games": extracted_games})

    if selected_date is not None:
        target_date = selected_date.isoformat()
        date_filtered_games = [game for game in extracted_games if _matches_selected_date(game, target_date)]
        logger.info(
            "Extracted upstream games after date filtering",
            extra={
                "selected_date": target_date,
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


def _matches_selected_date(game: dict[str, Any], selected_date_iso: str) -> bool:
    game_date = game.get("gameDate")
    if isinstance(game_date, str):
        if game_date == selected_date_iso:
            return True
        if len(game_date) >= 10 and game_date[:10] == selected_date_iso:
            return True

    week_date = game.get("_weekDate")
    if isinstance(week_date, str):
        if week_date == selected_date_iso:
            return True
        if len(week_date) >= 10 and week_date[:10] == selected_date_iso:
            return True

    start_time_utc = game.get("startTimeUTC")
    if isinstance(start_time_utc, str) and len(start_time_utc) >= 10:
        return start_time_utc[:10] == selected_date_iso

    return False


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

    def fetch_player_first_goal_projections(self, selected_date: date) -> list[tuple[str, str, str, str, float]]:
        return []


class EmptyOddsProvider(OddsProvider):
    """Production wiring placeholder until live odds integration is added."""

    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        return []
