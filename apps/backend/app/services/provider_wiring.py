from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from app.services.interfaces import OddsProvider, ProjectionProvider, ScheduleProvider
from app.services.dev_projection_provider import (
    AutoGeneratingProjectionProvider,
    NhlApiActiveRosterRepository,
    load_player_first_goal_history_from_nhl_api,
)
from app.services.mock_services import MockGamesService, MockOddsService, MockProjectionService
from app.services.odds_provider import LiveOddsProvider
from app.services.projection_store import build_real_projection_data_source_from_env
from app.services.recommendation_service import ValueRecommendationService
from app.services.real_services import NhlScheduleProvider


class ProviderMode(str, Enum):
    REAL = "real"
    MOCK = "mock"


@dataclass(frozen=True)
class ProviderRegistry:
    schedule_provider: ScheduleProvider
    projection_provider: ProjectionProvider
    odds_provider: OddsProvider
    recommendation_service: ValueRecommendationService


def _parse_provider_mode(raw_mode: str | None) -> ProviderMode:
    if raw_mode is None:
        return ProviderMode.REAL

    normalized = raw_mode.strip().lower()
    if normalized == ProviderMode.MOCK:
        return ProviderMode.MOCK
    return ProviderMode.REAL


def build_provider_registry_from_env() -> ProviderRegistry:
    """Create runtime provider wiring from BACKEND_PROVIDER_MODE (real|mock)."""

    mode = _parse_provider_mode(os.getenv("BACKEND_PROVIDER_MODE"))
    if mode == ProviderMode.MOCK:
        schedule_provider = MockGamesService()
        projection_provider = MockProjectionService()
        odds_provider = MockOddsService()
    else:
        schedule_provider = NhlScheduleProvider()
        projection_source = build_real_projection_data_source_from_env()
        projection_provider = AutoGeneratingProjectionProvider(
            schedule_provider=schedule_provider,
            artifact_path=projection_source.artifact_path,
            roster_repository=NhlApiActiveRosterRepository(),
            enable_dev_fallback=False,
            history_loader=load_player_first_goal_history_from_nhl_api,
        )
        odds_provider = LiveOddsProvider()

    recommendation_service = ValueRecommendationService(
        schedule_provider=schedule_provider,
        projection_provider=projection_provider,
        odds_provider=odds_provider,
    )
    return ProviderRegistry(
        schedule_provider=schedule_provider,
        projection_provider=projection_provider,
        odds_provider=odds_provider,
        recommendation_service=recommendation_service,
    )
