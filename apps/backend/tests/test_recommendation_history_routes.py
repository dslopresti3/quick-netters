from datetime import date, datetime, time, timezone
from pathlib import Path

from app.api.routes import get_recommendation_history, get_recommendation_history_availability
from app.api.schemas import GameSummary, Recommendation
from app.services.interfaces import ScheduleProvider
from app.services.provider_wiring import ProviderRegistry
from app.services.recommendation_history import RecommendationHistoryService


class _StubScheduleProvider(ScheduleProvider):
    def fetch(self, selected_date: date) -> list[GameSummary]:
        return [
            GameSummary(
                game_id="game-1",
                game_time=datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc),
                away_team="Away",
                home_team="Home",
            )
        ]


class _CountingRecommendationService:
    def __init__(self) -> None:
        self.fetch_daily_calls = 0

    def fetch_daily(self, selected_date: date, market: str = "first_goal") -> list[Recommendation]:
        self.fetch_daily_calls += 1
        return [self._recommendation(selected_date, "Player Alpha")]

    def fetch_game_recommendation_buckets(self, selected_date: date, game_id: str, market: str = "first_goal"):
        rec = self._recommendation(selected_date, "Player Alpha")
        return [rec], rec, None

    def _recommendation(self, selected_date: date, player_name: str) -> Recommendation:
        return Recommendation(
            game_id="game-1",
            game_time=datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc),
            away_team="Away",
            home_team="Home",
            player_id="p1",
            player_name=player_name,
            player_team="Home",
            team_name="Home",
            model_probability=0.2,
            implied_probability=0.1,
            fair_odds=500,
            market_odds=900,
            decimal_odds=10.0,
            edge=0.1,
            ev=0.15,
        )

def test_history_route_returns_only_persisted_snapshots(tmp_path: Path) -> None:
    selected_date = date(2026, 3, 24)
    schedule_provider = _StubScheduleProvider()
    recommendation_service = _CountingRecommendationService()
    history_service = RecommendationHistoryService(
        recommendation_service=recommendation_service,  # type: ignore[arg-type]
        schedule_provider=schedule_provider,
        storage_path=tmp_path / "history.json",
    )
    providers = ProviderRegistry(
        schedule_provider=schedule_provider,
        projection_provider=None,  # type: ignore[arg-type]
        odds_provider=None,  # type: ignore[arg-type]
        recommendation_service=recommendation_service,  # type: ignore[arg-type]
        recommendation_history_service=history_service,
    )

    payload = get_recommendation_history(date=selected_date, market="first_goal", providers=providers)

    assert payload.snapshots == []
    assert recommendation_service.fetch_daily_calls == 0


def test_history_availability_lists_browsable_saved_dates_by_market(tmp_path: Path) -> None:
    schedule_provider = _StubScheduleProvider()
    recommendation_service = _CountingRecommendationService()
    history_service = RecommendationHistoryService(
        recommendation_service=recommendation_service,  # type: ignore[arg-type]
        schedule_provider=schedule_provider,
        storage_path=tmp_path / "history.json",
    )
    providers = ProviderRegistry(
        schedule_provider=schedule_provider,
        projection_provider=None,  # type: ignore[arg-type]
        odds_provider=None,  # type: ignore[arg-type]
        recommendation_service=recommendation_service,  # type: ignore[arg-type]
        recommendation_history_service=history_service,
    )

    history_service.ensure_snapshot(date(2026, 3, 24), "first_goal", now_utc=datetime(2026, 3, 24, 22, 30, tzinfo=timezone.utc))
    history_service.ensure_snapshot(date(2026, 3, 25), "first_goal", now_utc=datetime(2026, 3, 25, 22, 30, tzinfo=timezone.utc))
    history_service.ensure_snapshot(date(2026, 3, 24), "anytime", now_utc=datetime(2026, 3, 24, 22, 30, tzinfo=timezone.utc))

    payload = get_recommendation_history_availability(date=date(2026, 3, 25), market="first_goal", providers=providers)

    assert payload.available_dates == [date(2026, 3, 24), date(2026, 3, 25)]
    assert payload.min_available_date == date(2026, 3, 24)
    assert payload.max_available_date == date(2026, 3, 25)
    assert payload.has_snapshot is True


def test_history_route_loads_persisted_snapshot_from_previous_day(tmp_path: Path) -> None:
    storage_path = tmp_path / "history.json"
    saved_date = date(2026, 3, 24)

    writer_service = RecommendationHistoryService(
        recommendation_service=_CountingRecommendationService(),  # type: ignore[arg-type]
        schedule_provider=_StubScheduleProvider(),
        storage_path=storage_path,
    )
    writer_service.ensure_snapshot(saved_date, "first_goal", now_utc=datetime(2026, 3, 24, 22, 30, tzinfo=timezone.utc))

    reader_schedule_provider = _StubScheduleProvider()
    reader_recommendation_service = _CountingRecommendationService()
    reader_service = RecommendationHistoryService(
        recommendation_service=reader_recommendation_service,  # type: ignore[arg-type]
        schedule_provider=reader_schedule_provider,
        storage_path=storage_path,
    )
    providers = ProviderRegistry(
        schedule_provider=reader_schedule_provider,
        projection_provider=None,  # type: ignore[arg-type]
        odds_provider=None,  # type: ignore[arg-type]
        recommendation_service=reader_recommendation_service,  # type: ignore[arg-type]
        recommendation_history_service=reader_service,
    )

    payload = get_recommendation_history(date=saved_date, market="first_goal", providers=providers)

    assert len(payload.snapshots) == 1
    assert payload.snapshots[0].date == saved_date
    assert payload.snapshots[0].top_overall[0].player_name == "Player Alpha"
    assert reader_recommendation_service.fetch_daily_calls == 0
