from datetime import date
import json
import logging
from time import perf_counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.api.schemas import (
    DailyRecommendationsResponse,
    DateAvailabilityResponse,
    GameRecommendationsResponse,
    GameSummary,
    GamesResponse,
    LockedRecommendationSnapshot,
    RecommendationHistoryResponse,
)
from app.services.provider_wiring import ProviderRegistry
from app.services.markets import Market, resolve_market
from app.utils.date_validation import (
    ensure_date_not_more_than_one_day_ahead,
    get_product_rule_window,
    is_valid_by_product_rule,
)

router = APIRouter()
logger = logging.getLogger(__name__)
DEFAULT_DISPLAY_TIMEZONE = "America/New_York"


def get_provider_registry(request: Request) -> ProviderRegistry:
    return request.app.state.provider_registry


def _build_date_availability(selected_date: date, providers: ProviderRegistry, market: Market = "first_goal") -> DateAvailabilityResponse:
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

    projections_available = providers.recommendation_service.projections_available(selected_date, market=market)
    odds_available = providers.recommendation_service.odds_available(selected_date, market=market)

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


def _availability_notes(selected_date: date, providers: ProviderRegistry, market: Market = "first_goal") -> tuple[bool, bool, list[str]]:
    metadata = _build_date_availability(selected_date, providers, market=market)

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




def _trigger_snapshot_capture(selected_date: date, market: Market, providers: ProviderRegistry) -> None:
    history_service = getattr(providers, "recommendation_history_service", None)
    if history_service is None:
        return
    history_service.ensure_snapshot(selected_date, market)


def _resolve_display_timezone(display_timezone: str | None) -> str:
    if isinstance(display_timezone, str) and display_timezone.strip():
        candidate = display_timezone.strip()
        try:
            ZoneInfo(candidate)
            return candidate
        except ZoneInfoNotFoundError:
            pass
    return DEFAULT_DISPLAY_TIMEZONE


def _with_display_times(games: list[GameSummary], display_timezone: str) -> list[GameSummary]:
    zone = ZoneInfo(display_timezone)
    localized_games = []
    for game in games:
        localized_games.append(
            game.model_copy(
                update={
                    "display_game_time": game.game_time.astimezone(zone).strftime("%Y-%m-%d %I:%M %p"),
                    "display_timezone": display_timezone,
                }
            )
        )
    return localized_games


@router.get("/availability/date", response_model=DateAvailabilityResponse)
def get_date_availability(
    date: date = Query(..., description="UTC date to validate and check data coverage for"),
    market: str | None = Query(default=None, description="Recommendation market: first_goal or anytime"),
    providers: ProviderRegistry = Depends(get_provider_registry),
) -> DateAvailabilityResponse:
    return _build_date_availability(date, providers, market=resolve_market(market))


@router.get("/games", response_model=GamesResponse)
def get_games(
    date: date = Query(..., description="UTC date to fetch games for"),
    market: str | None = Query(default=None, description="Recommendation market: first_goal or anytime"),
    timezone: str | None = Query(default=None, description="Optional IANA timezone for display formatting"),
    providers: ProviderRegistry = Depends(get_provider_registry),
) -> GamesResponse:
    selected_market = resolve_market(market)
    request_started = perf_counter()
    logger.info("games route entry", extra={"selected_date": date.isoformat()})
    ensure_date_not_more_than_one_day_ahead(date)
    _trigger_snapshot_capture(date, selected_market, providers)
    logger.info("games schedule fetch start", extra={"selected_date": date.isoformat()})
    schedule_started = perf_counter()
    games = providers.schedule_provider.fetch(date)
    schedule_elapsed_ms = round((perf_counter() - schedule_started) * 1000, 2)
    logger.info(
        "games schedule fetch end",
        extra={
            "selected_date": date.isoformat(),
            "games_count_after_schedule_fetch": len(games),
            "schedule_fetch_elapsed_ms": schedule_elapsed_ms,
        },
    )
    schedule_fetch_failure_note = _schedule_fetch_failure_note(providers)
    if schedule_fetch_failure_note is not None and len(games) == 0:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=schedule_fetch_failure_note)
    logger.info(
        "Games fetched before recommendation attachment",
        extra={"selected_date": date.isoformat(), "games_count_before_recommendation_attachment": len(games)},
    )
    logger.info("games scorer attachment start", extra={"selected_date": date.isoformat()})
    scorer_started = perf_counter()
    games = providers.recommendation_service.attach_top_projected_scorers(date, games)
    scorer_elapsed_ms = round((perf_counter() - scorer_started) * 1000, 2)
    logger.info(
        "games scorer attachment end",
        extra={
            "selected_date": date.isoformat(),
            "games_count_after_scorer_attachment": len(games),
            "scorer_attachment_elapsed_ms": scorer_elapsed_ms,
        },
    )
    logger.info(
        "Games after recommendation attachment",
        extra={"selected_date": date.isoformat(), "games_count_after_recommendation_attachment": len(games)},
    )
    notes: list[str] = []
    if len(games) == 0:
        projections_available = False
        odds_available = False
    else:
        projections_available = providers.recommendation_service.projections_available(date, market=selected_market)
        odds_available = providers.recommendation_service.odds_available(date, market=selected_market)
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
    response = GamesResponse(
        date=date,
        games=_with_display_times(games, _resolve_display_timezone(timezone)),
        projections_available=projections_available,
        odds_available=odds_available,
        notes=notes,
    )
    logger.info(
        "games response return",
        extra={
            "selected_date": date.isoformat(),
            "games_count_in_response": len(response.games),
            "projections_available": response.projections_available,
            "odds_available": response.odds_available,
            "notes_count": len(response.notes),
            "total_request_elapsed_ms": round((perf_counter() - request_started) * 1000, 2),
        },
    )
    return response


@router.get("/recommendations/daily", response_model=DailyRecommendationsResponse)
def get_daily_recommendations(
    date: date = Query(..., description="UTC date to fetch recommendations for"),
    market: str | None = Query(default=None, description="Recommendation market: first_goal or anytime"),
    providers: ProviderRegistry = Depends(get_provider_registry),
) -> DailyRecommendationsResponse:
    selected_market = resolve_market(market)
    ensure_date_not_more_than_one_day_ahead(date)
    _trigger_snapshot_capture(date, selected_market, providers)
    recommendations = providers.recommendation_service.fetch_daily(date, market=selected_market)
    projections_available, odds_available, notes = _availability_notes(date, providers, market=selected_market)
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
    market: str | None = Query(default=None, description="Recommendation market: first_goal or anytime"),
    timezone: str | None = Query(default=None, description="Optional IANA timezone for display formatting"),
    providers: ProviderRegistry = Depends(get_provider_registry),
) -> GameRecommendationsResponse:
    selected_market = resolve_market(market)
    ensure_date_not_more_than_one_day_ahead(date)
    _trigger_snapshot_capture(date, selected_market, providers)
    games = providers.recommendation_service.attach_top_projected_scorers(date, providers.schedule_provider.fetch(date))
    games_by_id = {game.game_id: game for game in games}

    if game_id not in games_by_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found for date")

    top_plays, best_bet, underdog_value_play = providers.recommendation_service.fetch_game_recommendation_buckets(
        date, game_id, market=selected_market
    )
    projections_available, odds_available, notes = _availability_notes(date, providers, market=selected_market)
    localized_game = _with_display_times([games_by_id[game_id]], _resolve_display_timezone(timezone))[0]
    return GameRecommendationsResponse(
        date=date,
        game=localized_game,
        recommendations=top_plays,
        top_plays=top_plays,
        best_bet=best_bet,
        underdog_value_play=underdog_value_play,
        projections_available=projections_available,
        odds_available=odds_available,
        notes=notes,
    )


@router.get("/recommendations/history", response_model=RecommendationHistoryResponse)
def get_recommendation_history(
    date: date | None = Query(default=None, description="Optional UTC date filter"),
    market: str | None = Query(default=None, description="Recommendation market: first_goal or anytime"),
    providers: ProviderRegistry = Depends(get_provider_registry),
) -> RecommendationHistoryResponse:
    history_service = getattr(providers, "recommendation_history_service", None)
    if history_service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Recommendation history service unavailable")

    selected_market = resolve_market(market) if market is not None else None
    if date is not None and selected_market is not None:
        history_service.ensure_snapshot(date, selected_market)

    snapshots = [LockedRecommendationSnapshot.model_validate(item) for item in history_service.list_snapshots(date, selected_market)]

    if date is None or selected_market is None:
        return RecommendationHistoryResponse(snapshots=snapshots)

    lock_context = history_service.compute_lock_context(date)
    if lock_context is None:
        return RecommendationHistoryResponse(
            date=date,
            market=selected_market,
            is_locked=False,
            snapshots=snapshots,
        )

    earliest_game_time_et, lock_cutoff_et = lock_context
    return RecommendationHistoryResponse(
        date=date,
        market=selected_market,
        is_locked=history_service.is_locked(date),
        earliest_game_time_et=earliest_game_time_et,
        lock_cutoff_et=lock_cutoff_et,
        snapshots=snapshots,
    )


@router.get("/recommendations/history/export")
def export_recommendation_history(
    format: str = Query(default="json", description="Export format: json or csv"),
    date: date | None = Query(default=None, description="Optional UTC date filter"),
    market: str | None = Query(default=None, description="Recommendation market: first_goal or anytime"),
    providers: ProviderRegistry = Depends(get_provider_registry),
) -> Response:
    history_service = getattr(providers, "recommendation_history_service", None)
    if history_service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Recommendation history service unavailable")

    selected_market = resolve_market(market) if market is not None else None
    normalized_format = format.strip().lower()

    if normalized_format == "csv":
        payload = history_service.export_csv(selected_date=date, market=selected_market)
        return Response(content=payload, media_type="text/csv")

    if normalized_format == "json":
        snapshots = history_service.list_snapshots(selected_date=date, market=selected_market)
        return Response(content=json.dumps({"snapshots": snapshots}), media_type="application/json")

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported format. Use json or csv")
