from datetime import date
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.schemas import (
    DailyRecommendationsResponse,
    DateAvailabilityResponse,
    GameRecommendationsResponse,
    GamesResponse,
)
from app.services.provider_wiring import ProviderRegistry
from app.utils.date_validation import (
    ensure_date_not_more_than_one_day_ahead,
    get_product_rule_window,
    is_valid_by_product_rule,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def get_provider_registry(request: Request) -> ProviderRegistry:
    return request.app.state.provider_registry


def _build_date_availability(selected_date: date, providers: ProviderRegistry) -> DateAvailabilityResponse:
    window = get_product_rule_window()
    valid = is_valid_by_product_rule(selected_date)

    if not valid:
        return DateAvailabilityResponse(
            selected_date=selected_date,
            min_allowed_date=window.min_allowed_date,
            max_allowed_date=window.max_allowed_date,
            valid_by_product_rule=False,
            schedule_available=False,
            projections_available=False,
            odds_available=False,
            status="invalid_date",
            messages=[
                "Selected date is outside the product window.",
                (
                    "Choose a date between "
                    f"{window.min_allowed_date.isoformat()} and {window.max_allowed_date.isoformat()}."
                ),
            ],
        )

    games = providers.schedule_provider.fetch(selected_date)
    schedule_available = len(games) > 0

    if not schedule_available:
        schedule_fetch_failure_note = _schedule_fetch_failure_note(providers)
        if schedule_fetch_failure_note is not None:
            logger.warning(
                "Date availability has no schedule due to upstream fetch failure",
                extra={"selected_date": selected_date.isoformat(), "note": schedule_fetch_failure_note},
            )
            messages = [
                "Upstream schedule fetch failed for this date.",
                schedule_fetch_failure_note,
            ]
        else:
            messages = [
                "No scheduled games are currently published for this date.",
            ]
        return DateAvailabilityResponse(
            selected_date=selected_date,
            min_allowed_date=window.min_allowed_date,
            max_allowed_date=window.max_allowed_date,
            valid_by_product_rule=True,
            schedule_available=False,
            projections_available=False,
            odds_available=False,
            status="no_schedule",
            messages=messages,
        )

    projections_available = providers.recommendation_service.projections_available(selected_date)
    odds_available = providers.recommendation_service.odds_available(selected_date)

    if not projections_available:
        status_value = "missing_projections"
        messages = [
            "Schedule is available, but projections are not ready yet.",
            "Value picks will appear after model generation runs.",
        ]
    elif not odds_available:
        status_value = "missing_odds"
        messages = [
            "Schedule and projections are available, but market odds are not posted yet.",
            "Value picks will appear once odds are available.",
        ]
    else:
        status_value = "ready"
        messages = ["Schedule, projections, and odds are available for this date."]

    return DateAvailabilityResponse(
        selected_date=selected_date,
        min_allowed_date=window.min_allowed_date,
        max_allowed_date=window.max_allowed_date,
        valid_by_product_rule=True,
        schedule_available=True,
        projections_available=projections_available,
        odds_available=odds_available,
        status=status_value,
        messages=messages,
    )


def _availability_notes(selected_date: date, providers: ProviderRegistry) -> tuple[bool, bool, list[str]]:
    metadata = _build_date_availability(selected_date, providers)

    notes: list[str] = []
    if metadata.status == "missing_projections":
        notes.append("Projections are not available for this date yet. Value picks will appear after model generation runs.")
    if metadata.status == "missing_odds":
        notes.append("Market odds are not available for this date yet. Value picks will appear once odds are posted.")

    return metadata.projections_available, metadata.odds_available, notes


def _schedule_fetch_failure_note(providers: ProviderRegistry) -> str | None:
    error_note = getattr(providers.schedule_provider, "last_fetch_error", None)
    if isinstance(error_note, str) and error_note:
        return error_note
    return None


@router.get("/availability/date", response_model=DateAvailabilityResponse)
def get_date_availability(
    date: date = Query(..., description="UTC date to validate and check data coverage for"),
    providers: ProviderRegistry = Depends(get_provider_registry),
) -> DateAvailabilityResponse:
    return _build_date_availability(date, providers)


@router.get("/games", response_model=GamesResponse)
def get_games(
    date: date = Query(..., description="UTC date to fetch games for"),
    providers: ProviderRegistry = Depends(get_provider_registry),
) -> GamesResponse:
    ensure_date_not_more_than_one_day_ahead(date)
    games = providers.schedule_provider.fetch(date)
    schedule_fetch_failure_note = _schedule_fetch_failure_note(providers)
    if schedule_fetch_failure_note is not None and len(games) == 0:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=schedule_fetch_failure_note)
    logger.info(
        "Games fetched before recommendation attachment",
        extra={"selected_date": date.isoformat(), "games_count_before_recommendation_attachment": len(games)},
    )
    games = providers.recommendation_service.attach_top_projected_scorers(date, games)
    logger.info(
        "Games after recommendation attachment",
        extra={"selected_date": date.isoformat(), "games_count_after_recommendation_attachment": len(games)},
    )
    notes: list[str] = []
    if len(games) == 0:
        projections_available = False
        odds_available = False
    else:
        projections_available = providers.recommendation_service.projections_available(date)
        odds_available = providers.recommendation_service.odds_available(date)
        if not projections_available:
            notes.append("Projections are not available for this date yet. Value picks will appear after model generation runs.")
        if not odds_available:
            notes.append("Market odds are not available for this date yet. Value picks will appear once odds are posted.")

    if schedule_fetch_failure_note is not None:
        notes.append(schedule_fetch_failure_note)
        logger.warning(
            "Returning games response with schedule fetch failure note",
            extra={"selected_date": date.isoformat(), "note": schedule_fetch_failure_note},
        )
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
