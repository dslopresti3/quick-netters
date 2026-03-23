from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from app.api.schemas import GameSummary, Recommendation
from app.services.interfaces import GamesProvider, OddsProvider, RecommendationsProvider
from app.services.odds import (
    NormalizedPlayerOdds,
    american_to_implied_probability,
    expected_value_per_unit,
    fair_american_odds,
    is_stale,
)


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


class MockGamesService(GamesProvider):
    def fetch(self, selected_date: date) -> list[GameSummary]:
        return _build_games(selected_date)


class MockOddsService(OddsProvider):
    """Mock provider that mimics an external odds source through a service layer."""

    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        snapshot_recent = datetime.combine(selected_date, time(22, 10), tzinfo=timezone.utc)
        snapshot_stale = datetime.combine(selected_date, time(20, 0), tzinfo=timezone.utc)

        return [
            NormalizedPlayerOdds(
                game_id="g-nyr-vs-bos",
                player_id="p-david-pastrnak",
                market_odds_american=360,
                snapshot_at=snapshot_recent,
            ),
            NormalizedPlayerOdds(
                game_id="g-col-vs-dal",
                player_id="p-nathan-mackinnon",
                market_odds_american=350,
                snapshot_at=snapshot_recent,
            ),
            NormalizedPlayerOdds(
                game_id="g-lak-vs-vgk",
                player_id="p-jack-eichel",
                market_odds_american=410,
                snapshot_at=snapshot_recent,
            ),
            NormalizedPlayerOdds(
                game_id="g-nyr-vs-bos",
                player_id="p-artemi-panarin",
                market_odds_american=680,
                snapshot_at=snapshot_recent,
            ),
            # Graceful exclusion examples: stale and invalid lines.
            NormalizedPlayerOdds(
                game_id="g-col-vs-dal",
                player_id="p-invalid-price",
                market_odds_american=0,
                snapshot_at=snapshot_recent,
            ),
            NormalizedPlayerOdds(
                game_id="g-lak-vs-vgk",
                player_id="p-stale-line",
                market_odds_american=300,
                snapshot_at=snapshot_stale,
            ),
        ]


class ValueRecommendationService(RecommendationsProvider):
    """Build value recommendations by comparing model probabilities against market odds."""

    def __init__(self, odds_provider: OddsProvider) -> None:
        self._odds_provider = odds_provider

    def fetch_daily(self, selected_date: date) -> list[Recommendation]:
        recommendations = self._build_ranked_recommendations(selected_date)
        return recommendations[:3]

    def fetch_for_game(self, selected_date: date, game_id: str) -> list[Recommendation]:
        recommendations = self._build_ranked_recommendations(selected_date)
        game_recommendations = [recommendation for recommendation in recommendations if recommendation.game_id == game_id]
        return game_recommendations[:3]

    def _build_ranked_recommendations(self, selected_date: date) -> list[Recommendation]:
        games_by_id = {game.game_id: game for game in _build_games(selected_date)}
        odds_snapshots = self._odds_provider.fetch_player_first_goal_odds(selected_date)
        model_probabilities = _mock_model_probabilities()

        recommendations: list[Recommendation] = []
        for key, model_probability in model_probabilities.items():
            game_id, player_id = key
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

            player_name = _PLAYER_NAMES.get(player_id, player_id)
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


class MockRecommendationsService(ValueRecommendationService):
    def __init__(self) -> None:
        super().__init__(odds_provider=MockOddsService())


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


_PLAYER_NAMES = {
    "p-david-pastrnak": "David Pastrnak",
    "p-nathan-mackinnon": "Nathan MacKinnon",
    "p-jack-eichel": "Jack Eichel",
    "p-artemi-panarin": "Artemi Panarin",
}


def _mock_model_probabilities() -> dict[tuple[str, str], float]:
    return {
        ("g-nyr-vs-bos", "p-david-pastrnak"): 0.23,
        ("g-col-vs-dal", "p-nathan-mackinnon"): 0.24,
        ("g-lak-vs-vgk", "p-jack-eichel"): 0.21,
        ("g-nyr-vs-bos", "p-artemi-panarin"): 0.14,
        # Should be excluded because price is invalid.
        ("g-col-vs-dal", "p-invalid-price"): 0.08,
        # Should be excluded because odds are stale.
        ("g-lak-vs-vgk", "p-stale-line"): 0.11,
        # Should be excluded because price is missing.
        ("g-nyr-vs-bos", "p-missing-odds"): 0.05,
    }
