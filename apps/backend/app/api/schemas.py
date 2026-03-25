from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=())


ConfidenceTag = Literal["high", "medium", "watch"]


DateAvailabilityStatus = Literal["invalid_date", "no_schedule", "missing_projections", "missing_odds", "ready"]


class DateAvailabilityResponse(APIModel):
    selected_date: date
    min_allowed_date: date
    max_allowed_date: date
    valid_by_product_rule: bool
    schedule_available: bool
    projections_available: bool
    odds_available: bool
    status: DateAvailabilityStatus
    messages: list[str] = Field(default_factory=list)


class HealthResponse(APIModel):
    status: Literal["ok"]
    service: str
    version: str


class TeamProjectionLeader(APIModel):
    team: str
    player_id: str
    player_name: str
    player_team: str | None = None
    team_name: str | None = None
    model_probability: float


class RecommendationModelDebug(APIModel):
    stable_baseline: float
    offensive_tier_multiplier: float
    stable_component: float
    recent_process_form: float
    recent_outcome_form: float
    recent_process_adjustment: float
    recent_outcome_adjustment: float
    model_probability: float
    fair_odds: int
    edge: float
    ev: float
    confidence_score: float
    recommendation_score: float


class GameSummary(APIModel):
    game_id: str = Field(..., description="Unique game identifier")
    game_time: datetime = Field(..., description="Scheduled start time in UTC")
    away_team: str
    home_team: str
    status: str | None = Field(default=None, description="Upstream game status, if available")
    display_game_time: str | None = Field(default=None, description="Display-ready localized game time")
    display_timezone: str | None = Field(default=None, description="IANA timezone used for display_game_time")
    away_top_projected_scorer: TeamProjectionLeader | None = None
    home_top_projected_scorer: TeamProjectionLeader | None = None


class Recommendation(APIModel):
    game_id: str
    game_time: datetime
    away_team: str
    home_team: str
    player_id: str
    player_name: str
    player_team: str | None = None
    team_name: str | None = None
    model_probability: float
    implied_probability: float | None = None
    fair_odds: int
    market_odds: int
    decimal_odds: float | None = None
    edge: float
    ev: float
    confidence_score: float | None = None
    recommendation_score: float | None = None
    model_debug: RecommendationModelDebug | None = None
    odds_snapshot_at: datetime | None = None
    confidence_tag: ConfidenceTag | None = None
    goals_this_year: float | None = None
    first_goals_this_year: float | None = None


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
    top_plays: list[Recommendation] = Field(default_factory=list)
    best_bet: Recommendation | None = None
    underdog_value_play: Recommendation | None = None
    projections_available: bool = True
    odds_available: bool = True
    notes: list[str] = Field(default_factory=list)
