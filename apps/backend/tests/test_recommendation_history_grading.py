from datetime import date, datetime, time, timezone
from pathlib import Path

from app.api.schemas import GameSummary, Recommendation
from app.services.interfaces import ScheduleProvider
from app.services.recommendation_history import GameOutcome, RecommendationHistoryService


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


class _StubRecommendationService:
    def fetch_daily(self, selected_date: date, market: str = "first_goal") -> list[Recommendation]:
        return [self._recommendation(selected_date, "8478402")]

    def fetch_game_recommendation_buckets(self, selected_date: date, game_id: str, market: str = "first_goal"):
        rec = self._recommendation(selected_date, "8478402")
        return [rec], rec, None

    def _recommendation(self, selected_date: date, player_id: str) -> Recommendation:
        return Recommendation(
            game_id="game-1",
            game_time=datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc),
            away_team="Away",
            home_team="Home",
            player_id=player_id,
            player_name="Player Alpha",
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


def _service(tmp_path: Path, outcome: GameOutcome) -> RecommendationHistoryService:
    def _fetcher(_: str) -> GameOutcome:
        return outcome

    return RecommendationHistoryService(
        recommendation_service=_StubRecommendationService(),  # type: ignore[arg-type]
        schedule_provider=_StubScheduleProvider(),
        storage_path=tmp_path / "history.json",
        outcome_fetcher=_fetcher,
    )


def test_first_goal_grading_hit(tmp_path: Path) -> None:
    service = _service(tmp_path, GameOutcome(True, "8478402", {"8478402": 1}))
    selected_date = date(2026, 3, 24)
    service.ensure_snapshot(selected_date, "first_goal", now_utc=datetime(2026, 3, 24, 22, 30, tzinfo=timezone.utc))
    snapshots = service.list_snapshots(selected_date, "first_goal")
    assert snapshots[0]["top_overall"][0]["result_status"] == "hit"


def test_first_goal_grading_miss(tmp_path: Path) -> None:
    service = _service(tmp_path, GameOutcome(True, "999", {"999": 1}))
    selected_date = date(2026, 3, 24)
    service.ensure_snapshot(selected_date, "first_goal", now_utc=datetime(2026, 3, 24, 22, 30, tzinfo=timezone.utc))
    snapshots = service.list_snapshots(selected_date, "first_goal")
    assert snapshots[0]["top_overall"][0]["result_status"] == "miss"


def test_anytime_grading_hit(tmp_path: Path) -> None:
    service = _service(tmp_path, GameOutcome(True, "999", {"8478402": 2}))
    selected_date = date(2026, 3, 24)
    service.ensure_snapshot(selected_date, "anytime", now_utc=datetime(2026, 3, 24, 22, 30, tzinfo=timezone.utc))
    snapshots = service.list_snapshots(selected_date, "anytime")
    assert snapshots[0]["top_overall"][0]["result_status"] == "hit"
    assert snapshots[0]["top_overall"][0]["actual_stat_value"] == 2


def test_anytime_grading_miss(tmp_path: Path) -> None:
    service = _service(tmp_path, GameOutcome(True, "999", {}))
    selected_date = date(2026, 3, 24)
    service.ensure_snapshot(selected_date, "anytime", now_utc=datetime(2026, 3, 24, 22, 30, tzinfo=timezone.utc))
    snapshots = service.list_snapshots(selected_date, "anytime")
    assert snapshots[0]["top_overall"][0]["result_status"] == "miss"


def test_pending_when_game_not_completed(tmp_path: Path) -> None:
    service = _service(tmp_path, GameOutcome(False, None, {}))
    selected_date = date(2026, 3, 24)
    service.ensure_snapshot(selected_date, "first_goal", now_utc=datetime(2026, 3, 24, 22, 30, tzinfo=timezone.utc))
    snapshots = service.list_snapshots(selected_date, "first_goal")
    assert snapshots[0]["top_overall"][0]["result_status"] == "pending"
    assert snapshots[0]["top_overall"][0]["graded_at"] is None


def test_grading_persists_alongside_snapshot_without_overwriting_snapshot_values(tmp_path: Path) -> None:
    service = _service(tmp_path, GameOutcome(True, "8478402", {"8478402": 1}))
    selected_date = date(2026, 3, 24)
    service.ensure_snapshot(selected_date, "first_goal", now_utc=datetime(2026, 3, 24, 22, 30, tzinfo=timezone.utc))
    first_loaded = service.list_snapshots(selected_date, "first_goal")[0]["top_overall"][0]
    model_probability = first_loaded["model_probability"]
    market_odds = first_loaded["market_odds"]
    graded_at = first_loaded["graded_at"]

    reloaded = service.get_snapshot(selected_date, "first_goal")
    assert reloaded is not None
    pick = reloaded["top_overall"][0]
    assert pick["model_probability"] == model_probability
    assert pick["market_odds"] == market_odds
    assert pick["graded_at"] == graded_at

