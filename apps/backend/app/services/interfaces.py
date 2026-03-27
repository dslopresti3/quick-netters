from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

from app.api.schemas import GameSummary, Recommendation
from app.services.markets import Market
from app.services.odds import NormalizedPlayerOdds


@dataclass(frozen=True)
class PlayerHistoricalProduction:
    season_first_goals: float | None = None
    season_games_played: float | None = None
    season_total_goals: float | None = None
    season_total_shots: float | None = None
    season_first_period_goals: float | None = None
    season_first_period_shots: float | None = None
    recent_5_first_goals: float | None = None
    recent_10_first_goals: float | None = None
    recent_5_total_goals: float | None = None
    recent_10_total_goals: float | None = None
    recent_5_total_shots: float | None = None
    recent_10_total_shots: float | None = None
    recent_5_first_period_goals: float | None = None
    recent_10_first_period_goals: float | None = None
    recent_5_first_period_shots: float | None = None
    recent_10_first_period_shots: float | None = None
    projected_goals_per_game: float | None = None
    projected_shots_per_game: float | None = None
    projected_goals_per_60: float | None = None
    projected_pp_goals_per_60: float | None = None
    season_confidence: float | None = None
    recent_form_confidence: float | None = None
    opponent_goals_allowed_per_game: float | None = None
    opponent_penalty_kill_pct: float | None = None
    vs_opponent_team_goal_rate_index: float | None = None
    vs_opponent_team_confidence: float | None = None
    vs_opposing_goalie_goal_rate_index: float | None = None
    vs_opposing_goalie_confidence: float | None = None


@dataclass(frozen=True)
class PlayerRosterEligibility:
    active_team_name: str
    is_active_roster: bool = True
    position_code: str | None = None


@dataclass(frozen=True)
class PlayerProjectionCandidate:
    game_id: str
    nhl_player_id: str
    player_name: str
    projected_team_name: str
    model_probability: float
    historical_production: PlayerHistoricalProduction
    roster_eligibility: PlayerRosterEligibility
    first_goal_probability: float | None = None
    anytime_probability: float | None = None

    def probability_for_market(self, market: Market) -> float | None:
        if market == "anytime":
            return self.anytime_probability
        return self.first_goal_probability if self.first_goal_probability is not None else self.model_probability


class ScheduleProvider(ABC):
    @abstractmethod
    def fetch(self, selected_date: date) -> list[GameSummary]:
        """Return the published game schedule for a date."""


class ProjectionProvider(ABC):
    @abstractmethod
    def fetch_player_first_goal_projections(self, selected_date: date) -> list[PlayerProjectionCandidate]:
        """Return per-game projection candidates keyed by canonical NHL player identity."""


class OddsProvider(ABC):
    @abstractmethod
    def fetch_player_first_goal_odds(self, selected_date: date, market: Market = "first_goal") -> list[NormalizedPlayerOdds]:
        """Return normalized player scorer odds snapshots for a date/market."""


class RecommendationsProvider(ABC):
    @abstractmethod
    def fetch_daily(self, selected_date: date, market: Market = "first_goal") -> list[Recommendation]:
        """Return top daily recommendations for a date."""

    @abstractmethod
    def fetch_for_game(self, selected_date: date, game_id: str, market: Market = "first_goal") -> list[Recommendation]:
        """Return recommendations for one game/date."""


class AvailabilityProvider(ABC):
    @abstractmethod
    def projections_available(self, selected_date: date, market: Market = "first_goal") -> bool:
        """Return whether projections exist for a given date."""

    @abstractmethod
    def odds_available(self, selected_date: date, market: Market = "first_goal") -> bool:
        """Return whether odds exist for a given date."""


# Backwards-compatibility alias while call-sites migrate to the new naming.
GamesProvider = ScheduleProvider
