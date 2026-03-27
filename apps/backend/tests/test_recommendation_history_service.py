from datetime import date, datetime, time, timezone
from io import BytesIO
from pathlib import Path
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
from zipfile import ZipFile

from app.api.schemas import GameSummary, Recommendation
from app.services.interfaces import ScheduleProvider
from app.services.recommendation_history import GameOutcome
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


def _pending_outcome(_: str) -> GameOutcome:
    return GameOutcome(game_completed=False, first_goal_scorer_player_id=None, goal_counts_by_player_id={})


def test_lock_cutoff_is_calculated_in_eastern_time(tmp_path: Path) -> None:
    service = RecommendationHistoryService(
        recommendation_service=_MutableRecommendationService(),  # type: ignore[arg-type]
        schedule_provider=_StubScheduleProvider(),
        storage_path=tmp_path / "history.json",
        outcome_fetcher=_pending_outcome,
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
        outcome_fetcher=_pending_outcome,
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
    assert persisted[0]["is_locked"] is True
    assert persisted[0]["snapshot_timestamp"] == lock_time_utc.isoformat()
    assert persisted[0]["locked_at"] == lock_time_utc.isoformat()


def test_snapshot_not_created_before_lock(tmp_path: Path) -> None:
    service = RecommendationHistoryService(
        recommendation_service=_MutableRecommendationService(),  # type: ignore[arg-type]
        schedule_provider=_StubScheduleProvider(),
        storage_path=tmp_path / "history.json",
        outcome_fetcher=_pending_outcome,
    )

    selected_date = date(2026, 3, 26)
    before_lock_utc = datetime(2026, 3, 26, 21, 30, tzinfo=timezone.utc)

    created = service.ensure_snapshot(selected_date, "first_goal", now_utc=before_lock_utc)

    assert created is None
    assert service.list_snapshots(selected_date=selected_date, market="first_goal") == []


def test_snapshot_is_retrievable_on_future_day_from_persisted_storage(tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    selected_date = date(2026, 3, 24)
    lock_time_utc = datetime(2026, 3, 24, 22, 30, tzinfo=timezone.utc)

    writer_service = RecommendationHistoryService(
        recommendation_service=_MutableRecommendationService(),  # type: ignore[arg-type]
        schedule_provider=_StubScheduleProvider(),
        storage_path=history_path,
        outcome_fetcher=_pending_outcome,
    )
    writer_service.ensure_snapshot(selected_date, "first_goal", now_utc=lock_time_utc)

    reader_service = RecommendationHistoryService(
        recommendation_service=_MutableRecommendationService(),  # type: ignore[arg-type]
        schedule_provider=_StubScheduleProvider(),
        storage_path=history_path,
        outcome_fetcher=_pending_outcome,
    )
    loaded = reader_service.get_snapshot(selected_date, "first_goal")

    assert loaded is not None
    assert loaded["date"] == "2026-03-24"
    assert loaded["top_overall"][0]["player_name"] == "Player Alpha"


def test_existing_locked_snapshot_is_not_overwritten_after_restart(tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    selected_date = date(2026, 3, 24)
    lock_time_utc = datetime(2026, 3, 24, 22, 30, tzinfo=timezone.utc)

    writer_service = RecommendationHistoryService(
        recommendation_service=_MutableRecommendationService(),  # type: ignore[arg-type]
        schedule_provider=_StubScheduleProvider(),
        storage_path=history_path,
        outcome_fetcher=_pending_outcome,
    )
    writer_service.ensure_snapshot(selected_date, "first_goal", now_utc=lock_time_utc)

    changed_recommendation_service = _MutableRecommendationService()
    changed_recommendation_service.player_name = "Player Beta"
    restarted_service = RecommendationHistoryService(
        recommendation_service=changed_recommendation_service,  # type: ignore[arg-type]
        schedule_provider=_StubScheduleProvider(),
        storage_path=history_path,
        outcome_fetcher=_pending_outcome,
    )
    same_snapshot = restarted_service.ensure_snapshot(selected_date, "first_goal", now_utc=lock_time_utc)

    assert same_snapshot is not None
    assert same_snapshot["top_overall"][0]["player_name"] == "Player Alpha"
    assert len(restarted_service.list_snapshots(selected_date=selected_date, market="first_goal")) == 1


def test_export_includes_game_context_and_implied_probability_for_csv_and_xlsx(tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    selected_date = date(2026, 3, 24)
    lock_time_utc = datetime(2026, 3, 24, 22, 30, tzinfo=timezone.utc)
    service = RecommendationHistoryService(
        recommendation_service=_MutableRecommendationService(),  # type: ignore[arg-type]
        schedule_provider=_StubScheduleProvider(),
        storage_path=history_path,
        outcome_fetcher=_pending_outcome,
    )
    service.ensure_snapshot(selected_date, "first_goal", now_utc=lock_time_utc)

    csv_payload = service.export_csv(selected_date=selected_date, market="first_goal")
    csv_rows = csv_payload.splitlines()

    assert "game_id" not in csv_rows[0]
    assert "game_date" in csv_rows[0]
    assert "home_team" in csv_rows[0]
    assert "away_team" in csv_rows[0]
    assert "implied_probability" in csv_rows[0]
    assert "2026-03-24,first_goal,2026-03-24,,,top_overall,1,p1,Player Alpha,Home,0.2,0.1,900,0.1,0.15,pending,False,,," in csv_rows
    assert "2026-03-24,first_goal,2026-03-24,Home,Away,top_plays,1,p1,Player Alpha,Home,0.2,0.1,900,0.1,0.15,pending,False,,," in csv_rows

    workbook_bytes = service.export_xlsx(selected_date=selected_date, market="first_goal")
    with ZipFile(BytesIO(workbook_bytes)) as archive:
        assert "xl/worksheets/sheet1.xml" in archive.namelist()
        sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    root = ET.fromstring(sheet_xml)
    namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    row_nodes = root.findall("s:sheetData/s:row", namespace)
    assert len(row_nodes) >= 3
    assert "game_date" in sheet_xml
    assert ">2026-03-24<" in sheet_xml
    assert ">Home<" in sheet_xml
    assert ">Away<" in sheet_xml
    assert "<v>0.1</v>" in sheet_xml


def test_export_uses_stored_implied_probability_without_recalculating(tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    selected_date = date(2026, 3, 24)
    lock_time_utc = datetime(2026, 3, 24, 22, 30, tzinfo=timezone.utc)
    service = RecommendationHistoryService(
        recommendation_service=_MutableRecommendationService(),  # type: ignore[arg-type]
        schedule_provider=_StubScheduleProvider(),
        storage_path=history_path,
        outcome_fetcher=_pending_outcome,
    )
    service.ensure_snapshot(selected_date, "first_goal", now_utc=lock_time_utc)

    payload = service._load_storage()  # noqa: SLF001
    payload["snapshots"][0]["top_overall"][0]["implied_probability"] = 0.3333
    payload["snapshots"][0]["top_overall"][0]["market_odds"] = 900
    service._save_storage(payload)  # noqa: SLF001

    csv_payload = service.export_csv(selected_date=selected_date, market="first_goal")
    assert "2026-03-24,first_goal,2026-03-24,,,top_overall,1,p1,Player Alpha,Home,0.2,0.3333,900,0.1,0.15,pending,False,,," in csv_payload
