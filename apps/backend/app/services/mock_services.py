from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from app.api.schemas import GameSummary, Recommendation, TeamProjectionLeader
from app.services.interfaces import (
    AvailabilityProvider,
    GamesProvider,
    OddsProvider,
    ProjectionProvider,
    RecommendationsProvider,
)
from app.services.odds import (
    NormalizedPlayerOdds,
    american_to_implied_probability,
    expected_value_per_unit,
    fair_american_odds,
    is_stale,
)


class MockGamesService(GamesProvider):
    def __init__(self) -> None:
        self._cache: dict[date, list[GameSummary]] = {}

    def fetch(self, selected_date: date) -> list[GameSummary]:
        if selected_date in self._cache:
            return [game.model_copy(deep=True) for game in self._cache[selected_date]]

        self._cache[selected_date] = _build_games(selected_date)
        return [game.model_copy(deep=True) for game in self._cache[selected_date]]


class MockProjectionService(ProjectionProvider):
    """Mock provider that mimics model output for projected first-goal probabilities."""

    def __init__(self) -> None:
        self._cache: dict[date, list[tuple[str, str, str, str, float]]] = {}

    def fetch_player_first_goal_projections(self, selected_date: date) -> list[tuple[str, str, str, str, float]]:
        if selected_date not in self._cache:
            if selected_date == date.today() + timedelta(days=1):
                self._cache[selected_date] = []
            else:
                self._cache[selected_date] = _mock_model_probabilities()

        return list(self._cache[selected_date])


class MockOddsService(OddsProvider):
    """Mock provider that mimics an external odds source through a service layer."""

    def __init__(self) -> None:
        self._cache: dict[date, list[NormalizedPlayerOdds]] = {}

    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        if selected_date not in self._cache:
            self._cache[selected_date] = _build_odds(selected_date)
        return list(self._cache[selected_date])


class ValueRecommendationService(RecommendationsProvider, AvailabilityProvider):
    """Build value recommendations by comparing model probabilities against market odds."""

    def __init__(self, games_provider: GamesProvider, projection_provider: ProjectionProvider, odds_provider: OddsProvider) -> None:
        self._games_provider = games_provider
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
        return len(self._projection_provider.fetch_player_first_goal_projections(selected_date)) > 0

    def odds_available(self, selected_date: date) -> bool:
        snapshots = self._odds_provider.fetch_player_first_goal_odds(selected_date)
        return any(snapshot.market_odds_american != 0 for snapshot in snapshots)

    def attach_top_projected_scorers(self, selected_date: date, games: list[GameSummary]) -> list[GameSummary]:
        projection_rows = self._projection_provider.fetch_player_first_goal_projections(selected_date)
        top_by_game_team: dict[tuple[str, str], tuple[str, str, str, str, float]] = {}

        for projection in projection_rows:
            game_id, _, _, team_name, probability = projection
            key = (game_id, team_name)
            existing = top_by_game_team.get(key)
            if existing is None or probability > existing[4]:
                top_by_game_team[key] = projection

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

    def _build_ranked_recommendations(self, selected_date: date) -> list[Recommendation]:
        games_by_id = {game.game_id: game for game in self._games_provider.fetch(selected_date)}
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


def _build_odds(selected_date: date) -> list[NormalizedPlayerOdds]:
    snapshot_recent = datetime.combine(selected_date, time(22, 10), tzinfo=timezone.utc)
    snapshot_stale = datetime.combine(selected_date, time(20, 0), tzinfo=timezone.utc)

    base_rows = [
        ("g-nyr-vs-bos", "p-david-pastrnak", 360, snapshot_recent),
        ("g-col-vs-dal", "p-nathan-mackinnon", 350, snapshot_recent),
        ("g-lak-vs-vgk", "p-jack-eichel", 410, snapshot_recent),
        ("g-nyr-vs-bos", "p-artemi-panarin", 680, snapshot_recent),
        ("g-col-vs-dal", "p-invalid-price", 0, snapshot_recent),
        ("g-lak-vs-vgk", "p-stale-line", 300, snapshot_stale),
    ]

    if selected_date == date.today() + timedelta(days=1):
        base_rows = []

    return [
        NormalizedPlayerOdds(
            game_id=game_id,
            player_id=player_id,
            market_odds_american=market_odds_american,
            snapshot_at=snapshot_at,
        )
        for game_id, player_id, market_odds_american, snapshot_at in base_rows
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


def _mock_model_probabilities() -> list[tuple[str, str, str, str, float]]:
    return [
        ("g-nyr-vs-bos", "p-david-pastrnak", "David Pastrnak", "Boston Bruins", 0.23),
        ("g-col-vs-dal", "p-nathan-mackinnon", "Nathan MacKinnon", "Colorado Avalanche", 0.24),
        ("g-lak-vs-vgk", "p-jack-eichel", "Jack Eichel", "Vegas Golden Knights", 0.21),
        ("g-nyr-vs-bos", "p-artemi-panarin", "Artemi Panarin", "NY Rangers", 0.14),
        ("g-col-vs-dal", "p-invalid-price", "Depth Forward", "Dallas Stars", 0.08),
        ("g-lak-vs-vgk", "p-stale-line", "Bottom-Six Wing", "LA Kings", 0.11),
        ("g-nyr-vs-bos", "p-missing-odds", "Secondary Option", "Boston Bruins", 0.05),
    ]


class MockRecommendationsService(ValueRecommendationService):
    def __init__(self) -> None:
        games_provider = MockGamesService()
        projection_provider = MockProjectionService()
        odds_provider = MockOddsService()
        super().__init__(games_provider=games_provider, projection_provider=projection_provider, odds_provider=odds_provider)
