from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date


@dataclass(slots=True)
class TeamGameSample:
    game_id: str
    game_date: date
    season: int
    team_id: int
    opponent_team_id: int
    is_home: bool
    scored_first: bool


@dataclass(slots=True)
class PlayerGameSample:
    game_id: str
    game_date: date
    season: int
    team_id: int
    player_id: int
    scored_first_for_team: bool
    on_ice_first_shift: bool = True
    toi_minutes: float | None = None


@dataclass(slots=True)
class ScheduledGame:
    game_id: str
    game_date: date
    season: int
    home_team_id: int
    away_team_id: int


@dataclass(slots=True)
class ScheduledLineupPlayer:
    game_id: str
    team_id: int
    player_id: int
    projected_toi_minutes: float | None = None
    is_expected_active: bool = True


@dataclass(slots=True)
class PlayerFirstGoalPrediction:
    game_id: str
    game_date: date
    season: int
    team_id: int
    opponent_team_id: int
    player_id: int
    team_first_goal_probability: float
    player_share_given_team_first: float
    player_first_goal_probability: float

    def to_row(self) -> dict:
        row = asdict(self)
        row["game_date"] = self.game_date.isoformat()
        return row
