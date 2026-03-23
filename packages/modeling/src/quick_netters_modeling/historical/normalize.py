from __future__ import annotations

from datetime import datetime

from .schemas import ShotEvent


def _first_value(row: dict, keys: tuple[str, ...], default: str | None = None) -> str | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def normalize_shot_rows(raw_rows: list[dict]) -> list[ShotEvent]:
    normalized: list[ShotEvent] = []
    for row in raw_rows:
        season = int(_first_value(row, ("season",), "0"))
        game_id = _first_value(row, ("game_id", "gameId"), "")
        event_id = _first_value(row, ("event_id", "eventId", "event_idx"), "")

        event_time_raw = _first_value(
            row,
            ("event_time_utc", "eventTimeUTC", "gameDate", "game_date"),
            "1970-01-01T00:00:00",
        )
        event_time = datetime.fromisoformat(event_time_raw.replace("Z", "+00:00"))

        period = int(float(_first_value(row, ("period",), "0")))
        period_seconds = int(float(_first_value(row, ("period_seconds", "secondsElapsed"), "0")))

        team_id = int(float(_first_value(row, ("team_id", "team", "teamId"), "0")))
        shooter_id = int(float(_first_value(row, ("shooter_id", "shooterPlayerId"), "0")))

        goalie_raw = _first_value(row, ("goalie_id", "goaliePlayerId"))
        goalie_id = int(float(goalie_raw)) if goalie_raw not in (None, "") else None

        x_coord = float(_first_value(row, ("x_coord", "xCordAdjusted", "xCord"), "0"))
        y_coord = float(_first_value(row, ("y_coord", "yCordAdjusted", "yCord"), "0"))
        shot_type = _first_value(row, ("shot_type", "shotType"), "UNKNOWN")
        strength_state = _first_value(row, ("strength_state", "situation"), "EVEN")

        goal_raw = _first_value(row, ("is_goal", "goal"), "0")
        is_goal = goal_raw.lower() in {"1", "true", "yes"}

        expected_goal = float(_first_value(row, ("expected_goal", "xGoal"), "0"))

        normalized.append(
            ShotEvent(
                season=season,
                game_id=game_id,
                event_id=event_id,
                event_time_utc=event_time,
                period=period,
                period_seconds=period_seconds,
                team_id=team_id,
                shooter_id=shooter_id,
                goalie_id=goalie_id,
                x_coord=x_coord,
                y_coord=y_coord,
                shot_type=shot_type,
                strength_state=strength_state,
                is_goal=is_goal,
                expected_goal=expected_goal,
            )
        )
    return normalized
