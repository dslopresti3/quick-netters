from datetime import date

from fastapi import APIRouter, Query

from app.services.interfaces import (
    OddsProvider,
    ProjectionsProvider,
    RecommendationsProvider,
    ScheduleProvider,
)
from app.services.mock_services import MockOddsService, MockProjectionsService, MockRecommendationsService, MockScheduleService
from app.utils.date_validation import ensure_date_not_more_than_one_day_ahead

router = APIRouter(prefix="/v1")

schedule_service: ScheduleProvider = MockScheduleService()
projections_service: ProjectionsProvider = MockProjectionsService()
odds_service: OddsProvider = MockOddsService()
recommendations_service: RecommendationsProvider = MockRecommendationsService()


@router.get("/schedule")
def get_schedule(selected_date: date = Query(..., description="UTC date to fetch schedule for")) -> dict:
    ensure_date_not_more_than_one_day_ahead(selected_date)
    return {"selected_date": selected_date.isoformat(), "data": schedule_service.fetch(selected_date)}


@router.get("/projections")
def get_projections(selected_date: date = Query(..., description="UTC date to fetch projections for")) -> dict:
    ensure_date_not_more_than_one_day_ahead(selected_date)
    return {"selected_date": selected_date.isoformat(), "data": projections_service.fetch(selected_date)}


@router.get("/odds")
def get_odds(selected_date: date = Query(..., description="UTC date to fetch odds for")) -> dict:
    ensure_date_not_more_than_one_day_ahead(selected_date)
    return {"selected_date": selected_date.isoformat(), "data": odds_service.fetch(selected_date)}


@router.get("/recommendations")
def get_recommendations(selected_date: date = Query(..., description="UTC date to fetch recommendations for")) -> dict:
    ensure_date_not_more_than_one_day_ahead(selected_date)
    return {
        "selected_date": selected_date.isoformat(),
        "data": recommendations_service.fetch(selected_date),
    }
