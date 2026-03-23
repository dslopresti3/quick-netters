from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from app.api.schemas import GameSummary
from app.services.interfaces import OddsProvider, ProjectionProvider, ScheduleProvider
from app.services.odds import NormalizedPlayerOdds


class NhlScheduleProvider(ScheduleProvider):
    """Fetch NHL schedule data from the official public NHL API."""

    base_url = "https://api-web.nhle.com/v1/schedule"

    def fetch(self, selected_date: date) -> list[GameSummary]:
        url = f"{self.base_url}/{selected_date.isoformat()}"
        try:
            with urlopen(url, timeout=10) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return []

        return _map_schedule_payload(payload)


def _map_schedule_payload(payload: dict[str, Any]) -> list[GameSummary]:
    game_summaries: list[GameSummary] = []
    game_weeks = payload.get("gameWeek")
    if not isinstance(game_weeks, list):
        return []

    for week in game_weeks:
        if not isinstance(week, dict):
            continue
        games = week.get("games")
        if not isinstance(games, list):
            continue

        for game in games:
            summary = _map_game(game)
            if summary is not None:
                game_summaries.append(summary)

    return game_summaries


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
