from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from app.api.schemas import DailyRecommendationsResponse, GameRecommendationsResponse, GamesResponse
from app.services.interfaces import GamesProvider
from app.services.mock_services import MockGamesService, MockOddsService, MockProjectionService, ValueRecommendationService
from app.utils.date_validation import ensure_date_not_more_than_one_day_ahead

router = APIRouter()

games_service: GamesProvider = MockGamesService()
projection_service = MockProjectionService()
odds_service = MockOddsService()
recommendations_service = ValueRecommendationService(
    games_provider=games_service,
    projection_provider=projection_service,
    odds_provider=odds_service,
)


def _availability_notes(selected_date: date) -> tuple[bool, bool, list[str]]:
    projections_available = len(projection_service.fetch_player_first_goal_projections(selected_date)) > 0
    odds_available = len(odds_service.fetch_player_first_goal_odds(selected_date)) > 0

    notes: list[str] = []
    if not projections_available:
        notes.append("Projections are not available for this date yet. Value picks will appear after model generation runs.")
    if not odds_available:
        notes.append("Market odds are not available for this date yet. Value picks will appear once odds are posted.")

    return projections_available, odds_available, notes


@router.get("/games", response_model=GamesResponse)
def get_games(date: date = Query(..., description="UTC date to fetch games for")) -> GamesResponse:
    ensure_date_not_more_than_one_day_ahead(date)
    games = games_service.fetch(date)
    games = recommendations_service.attach_top_projected_scorers(date, games)
    projections_available, odds_available, notes = _availability_notes(date)
    return GamesResponse(
        date=date,
        games=games,
        projections_available=projections_available,
        odds_available=odds_available,
        notes=notes,
    )


@router.get("/recommendations/daily", response_model=DailyRecommendationsResponse)
def get_daily_recommendations(date: date = Query(..., description="UTC date to fetch recommendations for")) -> DailyRecommendationsResponse:
    ensure_date_not_more_than_one_day_ahead(date)
    recommendations = recommendations_service.fetch_daily(date)
    projections_available, odds_available, notes = _availability_notes(date)
    return DailyRecommendationsResponse(
        date=date,
        recommendations=recommendations,
        projections_available=projections_available,
        odds_available=odds_available,
        notes=notes,
    )


@router.get("/recommendations/game", response_model=GameRecommendationsResponse)
def get_game_recommendations(
    game_id: str = Query(..., description="Game id"),
    date: date = Query(..., description="UTC date to fetch game recommendations for"),
) -> GameRecommendationsResponse:
    ensure_date_not_more_than_one_day_ahead(date)
    games = recommendations_service.attach_top_projected_scorers(date, games_service.fetch(date))
    games_by_id = {game.game_id: game for game in games}

    if game_id not in games_by_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found for date")

    recommendations = recommendations_service.fetch_for_game(date, game_id)
    projections_available, odds_available, notes = _availability_notes(date)
    return GameRecommendationsResponse(
        date=date,
        game=games_by_id[game_id],
        recommendations=recommendations,
        projections_available=projections_available,
        odds_available=odds_available,
        notes=notes,
    )
