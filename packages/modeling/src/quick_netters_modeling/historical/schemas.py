from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass(slots=True)
class ShotEvent:
    season: int
    game_id: str
    event_id: str
    event_time_utc: datetime
    period: int
    period_seconds: int
    team_id: int
    shooter_id: int
    goalie_id: int | None
    x_coord: float
    y_coord: float
    shot_type: str
    strength_state: str
    is_goal: bool
    expected_goal: float

    def to_row(self) -> dict:
        row = asdict(self)
        row["event_time_utc"] = self.event_time_utc.isoformat()
        return row


SHOT_EVENT_PK = ("season", "game_id", "event_id")


@dataclass(slots=True)
class GameRecord:
    season: int
    game_id: str
    game_date: str
    home_team_id: int
    away_team_id: int
    home_goals: int
    away_goals: int
    total_shots: int
    total_xg: float


GAME_PK = ("season", "game_id")


@dataclass(slots=True)
class PlayerGameAggregate:
    season: int
    game_id: str
    player_id: int
    team_id: int
    shots: int
    goals: int
    xg: float


PLAYER_GAME_PK = ("season", "game_id", "player_id")


@dataclass(slots=True)
class TeamGameAggregate:
    season: int
    game_id: str
    team_id: int
    opponent_team_id: int
    shots_for: int
    shots_against: int
    goals_for: int
    goals_against: int
    xg_for: float
    xg_against: float


TEAM_GAME_PK = ("season", "game_id", "team_id")
