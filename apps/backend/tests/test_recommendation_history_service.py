from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.api.schemas import GameSummary, Recommendation
from app.services.interfaces import ScheduleProvider
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


class _MutableRecommendationService:
    def __init__(self) -> None:
        self.player_name = "Player Alpha"

    def fetch_daily(self, selected_date: date, market: str = "first_goal") -> list[Recommendation]:
        return [self._recommendation(game_id="game-1", player_id="p1", player_name=self.player_name)]

    def fetch_game_recommendation_buckets(self, selected_date: date, game_id: str, market: str = "first_goal"):
        rec = self._recommendation(game_id=game_id, player_id="p1", player_name=self.player_name)
        return [rec], rec, None

    def _recommendation(self, game_id: str, player_id: str, player_name: str) -> Recommendation:
        return Recommendation(
            game_id=game_id,
            game_time=datetime.now(timezone.utc),
            away_team="Away",
            home_team="Home",
            player_id=player_id,
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


def test_lock_cutoff_is_calculated_in_eastern_time(tmp_path: Path) -> None:
    service = RecommendationHistoryService(
        recommendation_service=_MutableRecommendationService(),  # type: ignore[arg-type]
        schedule_provider=_StubScheduleProvider(),
        storage_path=tmp_path / "history.json",
    )

    earliest_et, cutoff_et = service.compute_lock_context(date(2026, 3, 26))  # type: ignore[assignment]

    assert earliest_et.tzinfo == ZoneInfo("America/New_York")
    assert earliest_et.hour == 19
    assert cutoff_et.hour == 18


def test_snapshot_persists_and_does_not_change_after_lock(tmp_path: Path) -> None:
    rec_service = _MutableRecommendationService()
    history_path = tmp_path / "history.json"
    service = RecommendationHistoryService(
        recommendation_service=rec_service,  # type: ignore[arg-type]
        schedule_provider=_StubScheduleProvider(),
        storage_path=history_path,
    )
    selected_date = date(2026, 3, 26)

    lock_time_utc = datetime(2026, 3, 26, 22, 30, tzinfo=timezone.utc)
    created = service.ensure_snapshot(selected_date, "first_goal", now_utc=lock_time_utc)
    assert created is not None
    assert created["top_overall"][0]["player_name"] == "Player Alpha"

    rec_service.player_name = "Player Beta"
    still_same = service.ensure_snapshot(selected_date, "first_goal", now_utc=lock_time_utc)
    assert still_same is not None
    assert still_same["top_overall"][0]["player_name"] == "Player Alpha"

    persisted = service.list_snapshots(selected_date=selected_date, market="first_goal")
    assert len(persisted) == 1
    assert persisted[0]["top_overall"][0]["player_name"] == "Player Alpha"


def test_snapshot_not_created_before_lock(tmp_path: Path) -> None:
    service = RecommendationHistoryService(
        recommendation_service=_MutableRecommendationService(),  # type: ignore[arg-type]
        schedule_provider=_StubScheduleProvider(),
        storage_path=tmp_path / "history.json",
    )

    selected_date = date(2026, 3, 26)
    before_lock_utc = datetime(2026, 3, 26, 21, 30, tzinfo=timezone.utc)

    created = service.ensure_snapshot(selected_date, "first_goal", now_utc=before_lock_utc)

    assert created is None
    assert service.list_snapshots(selected_date=selected_date, market="first_goal") == []
