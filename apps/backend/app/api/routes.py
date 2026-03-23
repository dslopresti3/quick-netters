from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.schemas import DailyRecommendationsResponse, GameRecommendationsResponse, GamesResponse
from app.services.provider_wiring import ProviderRegistry
from app.utils.date_validation import ensure_date_not_more_than_one_day_ahead

router = APIRouter()


def get_provider_registry(request: Request) -> ProviderRegistry:
    return request.app.state.provider_registry


def _availability_notes(selected_date: date, providers: ProviderRegistry) -> tuple[bool, bool, list[str]]:
    projections_available = providers.recommendation_service.projections_available(selected_date)
    odds_available = providers.recommendation_service.odds_available(selected_date)

    notes: list[str] = []
    if not projections_available:
        notes.append("Projections are not available for this date yet. Value picks will appear after model generation runs.")
    if not odds_available:
        notes.append("Market odds are not available for this date yet. Value picks will appear once odds are posted.")

    return projections_available, odds_available, notes


@router.get("/games", response_model=GamesResponse)
def get_games(
    date: date = Query(..., description="UTC date to fetch games for"),
    providers: ProviderRegistry = Depends(get_provider_registry),
) -> GamesResponse:
    ensure_date_not_more_than_one_day_ahead(date)
    games = providers.schedule_provider.fetch(date)
    games = providers.recommendation_service.attach_top_projected_scorers(date, games)
    projections_available, odds_available, notes = _availability_notes(date, providers)
    return GamesResponse(
        date=date,
        games=games,
        projections_available=projections_available,
        odds_available=odds_available,
        notes=notes,
    )


@router.get("/recommendations/daily", response_model=DailyRecommendationsResponse)
def get_daily_recommendations(
    date: date = Query(..., description="UTC date to fetch recommendations for"),
    providers: ProviderRegistry = Depends(get_provider_registry),
) -> DailyRecommendationsResponse:
    ensure_date_not_more_than_one_day_ahead(date)
    recommendations = providers.recommendation_service.fetch_daily(date)
    projections_available, odds_available, notes = _availability_notes(date, providers)
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
    providers: ProviderRegistry = Depends(get_provider_registry),
) -> GameRecommendationsResponse:
    ensure_date_not_more_than_one_day_ahead(date)
    games = providers.recommendation_service.attach_top_projected_scorers(date, providers.schedule_provider.fetch(date))
    games_by_id = {game.game_id: game for game in games}

    if game_id not in games_by_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found for date")

    recommendations = providers.recommendation_service.fetch_for_game(date, game_id)
    projections_available, odds_available, notes = _availability_notes(date, providers)
    return GameRecommendationsResponse(
        date=date,
        game=games_by_id[game_id],
        recommendations=recommendations,
        projections_available=projections_available,
        odds_available=odds_available,
        notes=notes,
    )
