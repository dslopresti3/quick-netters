from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=())


ConfidenceTag = Literal["high", "medium", "watch"]


class HealthResponse(APIModel):
    status: Literal["ok"]
    service: str
    version: str


class TeamProjectionLeader(APIModel):
    team: str
    player_id: str
    player_name: str
    model_probability: float


class GameSummary(APIModel):
    game_id: str = Field(..., description="Unique game identifier")
    game_time: datetime = Field(..., description="Scheduled start time in UTC")
    away_team: str
    home_team: str
    status: str | None = Field(default=None, description="Upstream game status, if available")
    away_top_projected_scorer: TeamProjectionLeader | None = None
    home_top_projected_scorer: TeamProjectionLeader | None = None


class Recommendation(APIModel):
    game_id: str
    game_time: datetime
    away_team: str
    home_team: str
    player_id: str
    player_name: str
    model_probability: float
    implied_probability: float | None = None
    fair_odds: int
    market_odds: int
    edge: float
    ev: float
    odds_snapshot_at: datetime | None = None
    confidence_tag: ConfidenceTag | None = None


class GamesResponse(APIModel):
    date: date
    games: list[GameSummary]
    projections_available: bool = True
    odds_available: bool = True
    notes: list[str] = Field(default_factory=list)


class DailyRecommendationsResponse(APIModel):
    date: date
    recommendations: list[Recommendation]
    projections_available: bool = True
    odds_available: bool = True
    notes: list[str] = Field(default_factory=list)


class GameRecommendationsResponse(APIModel):
    date: date
    game: GameSummary
    recommendations: list[Recommendation]
    projections_available: bool = True
    odds_available: bool = True
    notes: list[str] = Field(default_factory=list)
