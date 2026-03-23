from datetime import date, datetime, time, timedelta, timezone

from app.api.schemas import GameSummary, Recommendation
from app.services.interfaces import GamesProvider, RecommendationsProvider


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


def _build_recommendations(selected_date: date) -> list[Recommendation]:
    games = {game.game_id: game for game in _build_games(selected_date)}

    return [
        Recommendation(
            game_id="g-nyr-vs-bos",
            game_time=games["g-nyr-vs-bos"].game_time,
            away_team=games["g-nyr-vs-bos"].away_team,
            home_team=games["g-nyr-vs-bos"].home_team,
            player_id="p-david-pastrnak",
            player_name="David Pastrnak",
            model_probability=0.23,
            fair_odds=335,
            market_odds=360,
            edge=0.019,
            ev=0.058,
            confidence_tag="high",
        ),
        Recommendation(
            game_id="g-col-vs-dal",
            game_time=games["g-col-vs-dal"].game_time,
            away_team=games["g-col-vs-dal"].away_team,
            home_team=games["g-col-vs-dal"].home_team,
            player_id="p-nathan-mackinnon",
            player_name="Nathan MacKinnon",
            model_probability=0.24,
            fair_odds=317,
            market_odds=350,
            edge=0.027,
            ev=0.071,
            confidence_tag="high",
        ),
        Recommendation(
            game_id="g-lak-vs-vgk",
            game_time=games["g-lak-vs-vgk"].game_time,
            away_team=games["g-lak-vs-vgk"].away_team,
            home_team=games["g-lak-vs-vgk"].home_team,
            player_id="p-jack-eichel",
            player_name="Jack Eichel",
            model_probability=0.21,
            fair_odds=376,
            market_odds=410,
            edge=0.014,
            ev=0.031,
            confidence_tag="medium",
        ),
        Recommendation(
            game_id="g-nyr-vs-bos",
            game_time=games["g-nyr-vs-bos"].game_time,
            away_team=games["g-nyr-vs-bos"].away_team,
            home_team=games["g-nyr-vs-bos"].home_team,
            player_id="p-artemi-panarin",
            player_name="Artemi Panarin",
            model_probability=0.14,
            fair_odds=614,
            market_odds=680,
            edge=0.009,
            ev=0.026,
            confidence_tag="watch",
        ),
    ]


class MockGamesService(GamesProvider):
    def fetch(self, selected_date: date) -> list[GameSummary]:
        return _build_games(selected_date)


class MockRecommendationsService(RecommendationsProvider):
    def fetch_daily(self, selected_date: date) -> list[Recommendation]:
        return _build_recommendations(selected_date)

    def fetch_for_game(self, selected_date: date, game_id: str) -> list[Recommendation]:
        recommendations = _build_recommendations(selected_date)
        return [recommendation for recommendation in recommendations if recommendation.game_id == game_id]
