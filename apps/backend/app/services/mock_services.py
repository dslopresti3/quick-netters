from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import logging

from app.services.projection_store import build_mock_projection_provider

from app.api.schemas import GameSummary, Recommendation, TeamProjectionLeader
from app.services.interfaces import (
    AvailabilityProvider,
    ScheduleProvider,
    OddsProvider,
    ProjectionProvider,
    RecommendationsProvider,
)
from app.services.odds_provider import LiveOddsProvider
from app.services.odds import (
    NormalizedPlayerOdds,
    american_to_implied_probability,
    expected_value_per_unit,
    fair_american_odds,
    is_stale,
)

logger = logging.getLogger(__name__)


class MockGamesService(ScheduleProvider):
    def __init__(self) -> None:
        self._cache: dict[date, list[GameSummary]] = {}

    def fetch(self, selected_date: date) -> list[GameSummary]:
        if selected_date in self._cache:
            return [game.model_copy(deep=True) for game in self._cache[selected_date]]

        self._cache[selected_date] = _build_games(selected_date)
        return [game.model_copy(deep=True) for game in self._cache[selected_date]]


class MockProjectionService(ProjectionProvider):
    """Mock provider that reads first-goal projections from a structured artifact store."""

    def __init__(self) -> None:
        self._provider = build_mock_projection_provider()

    def fetch_player_first_goal_projections(self, selected_date: date) -> list[tuple[str, str, str, str, float]]:
        if selected_date == date.today() + timedelta(days=1):
            return []
        return self._provider.fetch_player_first_goal_projections(selected_date)


class MockOddsService(OddsProvider):
    """Mock-mode wrapper around the live odds provider contract."""

    def __init__(self) -> None:
        self._provider = LiveOddsProvider()

    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        return self._provider.fetch_player_first_goal_odds(selected_date)


class ValueRecommendationService(RecommendationsProvider, AvailabilityProvider):
    """Build value recommendations by comparing model probabilities against market odds."""

    def __init__(self, schedule_provider: ScheduleProvider, projection_provider: ProjectionProvider, odds_provider: OddsProvider) -> None:
        self._schedule_provider = schedule_provider
        self._projection_provider = projection_provider
        self._odds_provider = odds_provider

    def fetch_daily(self, selected_date: date) -> list[Recommendation]:
        recommendations = self._build_ranked_recommendations(selected_date)
        return recommendations[:3]

    def fetch_for_game(self, selected_date: date, game_id: str) -> list[Recommendation]:
        recommendations = self._build_ranked_recommendations(selected_date)
        game_recommendations = [recommendation for recommendation in recommendations if recommendation.game_id == game_id]
        return game_recommendations[:3]

    def projections_available(self, selected_date: date) -> bool:
        _, projections_available = self._build_top_projection_lookup(selected_date, games=None)
        return projections_available

    def odds_available(self, selected_date: date) -> bool:
        snapshots = self._odds_provider.fetch_player_first_goal_odds(selected_date)
        return any(snapshot.market_odds_american != 0 for snapshot in snapshots)

    def attach_top_projected_scorers(self, selected_date: date, games: list[GameSummary]) -> list[GameSummary]:
        top_by_game_team, _ = self._build_top_projection_lookup(selected_date, games)

        enriched_games: list[GameSummary] = []
        for game in games:
            enriched = game.model_copy(deep=True)
            away_pick = top_by_game_team.get((game.game_id, game.away_team))
            home_pick = top_by_game_team.get((game.game_id, game.home_team))

            if away_pick:
                _, player_id, player_name, team_name, probability = away_pick
                enriched.away_top_projected_scorer = TeamProjectionLeader(
                    team=team_name,
                    player_id=player_id,
                    player_name=player_name,
                    model_probability=round(probability, 4),
                )

            if home_pick:
                _, player_id, player_name, team_name, probability = home_pick
                enriched.home_top_projected_scorer = TeamProjectionLeader(
                    team=team_name,
                    player_id=player_id,
                    player_name=player_name,
                    model_probability=round(probability, 4),
                )

            enriched_games.append(enriched)

        return enriched_games

    def _build_top_projection_lookup(
        self,
        selected_date: date,
        games: list[GameSummary] | None,
    ) -> tuple[dict[tuple[str, str], tuple[str, str, str, str, float]], bool]:
        projection_rows = self._projection_provider.fetch_player_first_goal_projections(selected_date)
        valid_game_teams: set[tuple[str, str]] | None = None
        if games is not None:
            valid_game_teams = {
                (game.game_id, game.away_team)
                for game in games
            } | {
                (game.game_id, game.home_team)
                for game in games
            }

        top_by_game_team: dict[tuple[str, str], tuple[str, str, str, str, float]] = {}
        attached_projection_count = 0
        seen_projection_keys: set[tuple[str, str]] = set()

        for idx, projection in enumerate(projection_rows):
            game_id, player_id, player_name, team_name, probability = projection

            if not isinstance(game_id, str) or not game_id.strip():
                logger.warning("Skipping projection row with missing game_id", extra={"selected_date": selected_date.isoformat(), "row_index": idx})
                continue
            if not isinstance(player_id, str) or not player_id.strip():
                logger.warning("Skipping projection row with missing player_id", extra={"selected_date": selected_date.isoformat(), "row_index": idx})
                continue
            if not isinstance(player_name, str) or not player_name.strip():
                logger.warning("Skipping projection row with missing player_name", extra={"selected_date": selected_date.isoformat(), "row_index": idx})
                continue
            if not isinstance(team_name, str) or not team_name.strip():
                logger.warning("Skipping projection row with missing team_name", extra={"selected_date": selected_date.isoformat(), "row_index": idx})
                continue
            if not isinstance(probability, (int, float)):
                logger.warning(
                    "Skipping projection row with non-numeric probability",
                    extra={"selected_date": selected_date.isoformat(), "row_index": idx, "value": probability},
                )
                continue

            probability_value = float(probability)
            if probability_value <= 0 or probability_value >= 1:
                logger.warning(
                    "Skipping projection row with invalid probability",
                    extra={"selected_date": selected_date.isoformat(), "row_index": idx, "value": probability_value},
                )
                continue

            projection_key = (game_id.strip(), team_name.strip())
            if valid_game_teams is not None and projection_key not in valid_game_teams:
                continue

            dedupe_key = (projection_key[0], player_id.strip())
            if dedupe_key in seen_projection_keys:
                logger.warning(
                    "Skipping duplicate projection row",
                    extra={
                        "selected_date": selected_date.isoformat(),
                        "row_index": idx,
                        "game_id": projection_key[0],
                        "player_id": player_id.strip(),
                    },
                )
                continue
            seen_projection_keys.add(dedupe_key)

            attached_projection_count += 1
            normalized_projection = (
                projection_key[0],
                player_id.strip(),
                player_name.strip(),
                projection_key[1],
                probability_value,
            )
            existing = top_by_game_team.get(projection_key)
            if existing is None or probability_value > existing[4]:
                top_by_game_team[projection_key] = normalized_projection

        return top_by_game_team, attached_projection_count > 0

    def _build_ranked_recommendations(self, selected_date: date) -> list[Recommendation]:
        games_by_id = {game.game_id: game for game in self._schedule_provider.fetch(selected_date)}
        odds_snapshots = self._odds_provider.fetch_player_first_goal_odds(selected_date)
        projections = self._projection_provider.fetch_player_first_goal_projections(selected_date)

        projections_by_game_player = {
            (game_id, player_id): (player_name, probability)
            for game_id, player_id, player_name, _, probability in projections
        }

        recommendations: list[Recommendation] = []
        for (game_id, player_id), (player_name, model_probability) in projections_by_game_player.items():
            game = games_by_id.get(game_id)
            odds_snapshot = _latest_snapshot_for_player(odds_snapshots, game_id, player_id)

            if game is None or odds_snapshot is None or is_stale(odds_snapshot.snapshot_at):
                continue

            implied_probability = american_to_implied_probability(odds_snapshot.market_odds_american)
            fair_odds = fair_american_odds(model_probability)
            ev = expected_value_per_unit(model_probability, odds_snapshot.market_odds_american)

            if implied_probability is None or fair_odds is None or ev is None:
                continue

            edge = model_probability - implied_probability
            if edge <= 0:
                continue

            recommendations.append(
                Recommendation(
                    game_id=game_id,
                    game_time=game.game_time,
                    away_team=game.away_team,
                    home_team=game.home_team,
                    player_id=player_id,
                    player_name=player_name,
                    model_probability=round(model_probability, 4),
                    fair_odds=fair_odds,
                    market_odds=odds_snapshot.market_odds_american,
                    edge=round(edge, 4),
                    ev=round(ev, 4),
                    implied_probability=round(implied_probability, 4),
                    odds_snapshot_at=odds_snapshot.snapshot_at,
                    confidence_tag=_confidence_tag(ev),
                )
            )

        return sorted(recommendations, key=lambda rec: (rec.ev, rec.edge, rec.model_probability), reverse=True)


def _build_games(selected_date: date) -> list[GameSummary]:
    if selected_date > date.today() + timedelta(days=1):
        return []

    return [
        GameSummary(
            game_id="g-nyr-vs-bos",
            game_time=datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc),
            away_team="NY Rangers",
            home_team="Boston Bruins",
        ),
        GameSummary(
            game_id="g-col-vs-dal",
            game_time=datetime.combine(selected_date + timedelta(days=1), time(0, 30), tzinfo=timezone.utc),
            away_team="Colorado Avalanche",
            home_team="Dallas Stars",
        ),
        GameSummary(
            game_id="g-lak-vs-vgk",
            game_time=datetime.combine(selected_date + timedelta(days=1), time(3, 0), tzinfo=timezone.utc),
            away_team="LA Kings",
            home_team="Vegas Golden Knights",
        ),
    ]


def _latest_snapshot_for_player(
    snapshots: list[NormalizedPlayerOdds], game_id: str, player_id: str
) -> NormalizedPlayerOdds | None:
    candidates = [snapshot for snapshot in snapshots if snapshot.game_id == game_id and snapshot.player_id == player_id]
    if not candidates:
        return None
    return max(candidates, key=lambda snapshot: snapshot.snapshot_at)


def _confidence_tag(ev: float) -> str:
    if ev >= 0.06:
        return "high"
    if ev >= 0.03:
        return "medium"
    return "watch"




class MockRecommendationsService(ValueRecommendationService):
    def __init__(self) -> None:
        schedule_provider = MockGamesService()
        projection_provider = MockProjectionService()
        odds_provider = MockOddsService()
        super().__init__(schedule_provider=schedule_provider, projection_provider=projection_provider, odds_provider=odds_provider)
