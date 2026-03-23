from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from app.api.schemas import DailyRecommendationsResponse, GameRecommendationsResponse, GamesResponse
from app.services.interfaces import GamesProvider, RecommendationsProvider
from app.services.mock_services import MockGamesService, MockRecommendationsService
from app.utils.date_validation import ensure_date_not_more_than_one_day_ahead

router = APIRouter()

games_service: GamesProvider = MockGamesService()
recommendations_service: RecommendationsProvider = MockRecommendationsService()


@router.get("/games", response_model=GamesResponse)
def get_games(date: date = Query(..., description="UTC date to fetch games for")) -> GamesResponse:
    ensure_date_not_more_than_one_day_ahead(date)
    games = games_service.fetch(date)
    return GamesResponse(date=date, games=games)


@router.get("/recommendations/daily", response_model=DailyRecommendationsResponse)
def get_daily_recommendations(date: date = Query(..., description="UTC date to fetch recommendations for")) -> DailyRecommendationsResponse:
    ensure_date_not_more_than_one_day_ahead(date)
    recommendations = recommendations_service.fetch_daily(date)
    return DailyRecommendationsResponse(date=date, recommendations=recommendations)


@router.get("/recommendations/game", response_model=GameRecommendationsResponse)
def get_game_recommendations(
    game_id: str = Query(..., description="Game id"),
    date: date = Query(..., description="UTC date to fetch game recommendations for"),
) -> GameRecommendationsResponse:
    ensure_date_not_more_than_one_day_ahead(date)
    games = {game.game_id: game for game in games_service.fetch(date)}

    if game_id not in games:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found for date")

    recommendations = recommendations_service.fetch_for_game(date, game_id)
    return GameRecommendationsResponse(date=date, game=games[game_id], recommendations=recommendations)
