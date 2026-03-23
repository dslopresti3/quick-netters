from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

ConfidenceTag = Literal["high", "medium", "watch"]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class GameSummary(BaseModel):
    game_id: str = Field(..., description="Unique game identifier")
    game_time: datetime = Field(..., description="Scheduled start time in UTC")
    away_team: str
    home_team: str


class Recommendation(BaseModel):
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


class GamesResponse(BaseModel):
    date: date
    games: list[GameSummary]


class DailyRecommendationsResponse(BaseModel):
    date: date
    recommendations: list[Recommendation]


class GameRecommendationsResponse(BaseModel):
    date: date
    game: GameSummary
    recommendations: list[Recommendation]
