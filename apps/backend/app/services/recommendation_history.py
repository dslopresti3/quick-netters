from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
from threading import Lock
from tempfile import NamedTemporaryFile
from typing import Callable
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo
from zipfile import ZIP_DEFLATED, ZipFile

from app.api.schemas import GameSummary, Recommendation
from app.services.http_client import fetch_json
from app.services.markets import Market
from app.services.odds import american_to_implied_probability
from app.services.recommendation_service import ValueRecommendationService
from app.services.interfaces import ScheduleProvider

EASTERN_TIMEZONE = ZoneInfo("America/New_York")
NHL_WEB_BASE = "https://api-web.nhle.com/v1"
NHL_PLAY_BY_PLAY_TIMEOUT_SECONDS = 12
FINAL_GAME_STATES = {"FINAL", "OFF"}
RESULT_PENDING = "pending"
RESULT_HIT = "hit"
RESULT_MISS = "miss"


@dataclass(frozen=True)
class GameOutcome:
    game_completed: bool
    first_goal_scorer_player_id: str | None
    goal_counts_by_player_id: dict[str, int]


class RecommendationHistoryService:
    """Persist immutable recommendation snapshots after lock cutoff."""

    def __init__(
        self,
        recommendation_service: ValueRecommendationService,
        schedule_provider: ScheduleProvider,
        storage_path: Path,
        outcome_fetcher: Callable[[str], GameOutcome] | None = None,
    ) -> None:
        self._recommendation_service = recommendation_service
        self._schedule_provider = schedule_provider
        self._storage_path = storage_path
        self._outcome_fetcher = outcome_fetcher or _fetch_game_outcome
        self._lock = Lock()

    def compute_lock_context(self, selected_date: date) -> tuple[datetime, datetime] | None:
        games = self._schedule_provider.fetch(selected_date)
        if not games:
            return None

        earliest_game_time_utc = min(game.game_time for game in games)
        earliest_game_time_et = earliest_game_time_utc.astimezone(EASTERN_TIMEZONE)
        lock_cutoff_et = earliest_game_time_et - timedelta(hours=1)
        return earliest_game_time_et, lock_cutoff_et

    def is_locked(self, selected_date: date, *, now_utc: datetime | None = None) -> bool:
        context = self.compute_lock_context(selected_date)
        if context is None:
            return False

        _, lock_cutoff_et = context
        current_utc = now_utc or datetime.now(timezone.utc)
        return current_utc >= lock_cutoff_et.astimezone(timezone.utc)

    def ensure_snapshot(self, selected_date: date, market: Market, *, now_utc: datetime | None = None) -> dict | None:
        with self._lock:
            payload = self._load_storage_unlocked()
            existing = self._find_snapshot(payload, selected_date=selected_date, market=market)
            if existing is not None:
                return existing

            if not self.is_locked(selected_date, now_utc=now_utc):
                return None

            games = self._schedule_provider.fetch(selected_date)
            if not games:
                return None

            daily_top_three = self._recommendation_service.fetch_daily(selected_date, market=market)
            game_snapshots: list[dict] = []
            for game in games:
                top_plays, best_bet, underdog_value_play = self._recommendation_service.fetch_game_recommendation_buckets(
                    selected_date,
                    game.game_id,
                    market=market,
                )
                game_snapshots.append(
                    {
                        "game": self._serialize_game(game),
                        "top_plays": [self._serialize_recommendation(rec) for rec in top_plays[:3]],
                        "best_bet": self._serialize_recommendation(best_bet) if best_bet else None,
                        "underdog_value_play": self._serialize_recommendation(underdog_value_play) if underdog_value_play else None,
                    }
                )

            lock_context = self.compute_lock_context(selected_date)
            if lock_context is None:
                return None
            earliest_game_time_et, lock_cutoff_et = lock_context
            persisted_at = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
            snapshot = {
                "date": selected_date.isoformat(),
                "market": market,
                "snapshot_created_at": persisted_at.isoformat(),
                "snapshot_timestamp": persisted_at.isoformat(),
                "locked_at": persisted_at.isoformat(),
                "is_locked": True,
                "model_version": os.getenv("MODEL_VERSION"),
                "app_version": os.getenv("APP_VERSION"),
                "earliest_game_time_et": earliest_game_time_et.isoformat(),
                "lock_cutoff_et": lock_cutoff_et.isoformat(),
                "top_overall": [self._serialize_recommendation(rec) for rec in daily_top_three[:3]],
                "games": game_snapshots,
            }
            payload["snapshots"].append(snapshot)
            self._save_storage_unlocked(payload)
            return snapshot

    def get_snapshot(self, selected_date: date, market: Market) -> dict | None:
        payload = self._load_storage()
        for snapshot in payload["snapshots"]:
            if snapshot.get("date") == selected_date.isoformat() and snapshot.get("market") == market:
                return snapshot
        return None

    def list_snapshots(self, selected_date: date | None = None, market: Market | None = None) -> list[dict]:
        self.grade_snapshots(selected_date=selected_date, market=market)
        payload = self._load_storage()
        snapshots = payload["snapshots"]
        filtered = [
            snapshot
            for snapshot in snapshots
            if (selected_date is None or snapshot.get("date") == selected_date.isoformat())
            and (market is None or snapshot.get("market") == market)
        ]
        return sorted(filtered, key=lambda row: (row.get("date", ""), row.get("market", "")), reverse=True)

    def list_snapshot_dates(self, market: Market | None = None) -> list[date]:
        snapshots = self.list_snapshots(market=market)
        snapshot_dates: list[date] = []
        for snapshot in snapshots:
            raw_date = snapshot.get("date")
            if not isinstance(raw_date, str):
                continue
            try:
                snapshot_dates.append(date.fromisoformat(raw_date))
            except ValueError:
                continue
        return sorted(set(snapshot_dates))

    def export_csv(self, selected_date: date | None = None, market: Market | None = None) -> str:
        self.grade_snapshots(selected_date=selected_date, market=market)
        snapshots = self.list_snapshots(selected_date=selected_date, market=market)
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=self._export_header())
        writer.writeheader()
        for row in self._snapshot_export_rows(snapshots):
            writer.writerow(row)
        return output.getvalue().rstrip("\n")

    def export_xlsx(self, selected_date: date | None = None, market: Market | None = None) -> bytes:
        self.grade_snapshots(selected_date=selected_date, market=market)
        snapshots = self.list_snapshots(selected_date=selected_date, market=market)
        header = self._export_header()
        rows = [[row[column] for column in header] for row in self._snapshot_export_rows(snapshots)]
        return self._build_xlsx_bytes(header, rows)

    def _export_header(self) -> list[str]:
        return [
            "date",
            "market",
            "game_date",
            "home_team",
            "away_team",
            "bucket",
            "rank",
            "player_id",
            "player_name",
            "team_name",
            "model_probability",
            "implied_probability",
            "market_odds",
            "edge",
            "ev",
            "result_status",
            "game_completed",
            "graded_at",
            "actual_stat_value",
            "actual_result_detail",
        ]

    def _snapshot_export_rows(self, snapshots: list[dict]) -> list[dict[str, str | int | float | None]]:
        export_rows: list[dict[str, str | int | float | None]] = []
        for snapshot in snapshots:
            export_rows.extend(self._snapshot_rows(snapshot))
        return export_rows

    def _snapshot_rows(self, snapshot: dict) -> list[dict[str, str | int | float | None]]:
        output_rows: list[dict[str, str | int | float | None]] = []
        base_date = snapshot["date"]
        base_market = snapshot["market"]

        def _append_pick(bucket: str, rank: int, rec: dict, game_date: str, home_team: str | None, away_team: str | None) -> None:
            market_odds = rec.get("market_odds")
            implied_probability = rec.get("implied_probability")
            if implied_probability is None and isinstance(market_odds, int):
                converted = american_to_implied_probability(market_odds)
                implied_probability = round(converted, 4) if converted is not None else None
            output_rows.append(
                {
                    "date": base_date,
                    "market": base_market,
                    "game_date": game_date,
                    "home_team": home_team,
                    "away_team": away_team,
                    "bucket": bucket,
                    "rank": rank,
                    "player_id": rec.get("player_id", ""),
                    "player_name": rec.get("player_name", ""),
                    "team_name": rec.get("team_name", rec.get("player_team", "")) or "",
                    "model_probability": rec.get("model_probability"),
                    "implied_probability": implied_probability,
                    "market_odds": market_odds,
                    "edge": rec.get("edge"),
                    "ev": rec.get("ev"),
                    "result_status": rec.get("result_status", RESULT_PENDING),
                    "game_completed": rec.get("game_completed", False),
                    "graded_at": rec.get("graded_at"),
                    "actual_stat_value": rec.get("actual_stat_value"),
                    "actual_result_detail": rec.get("actual_result_detail"),
                }
            )

        for idx, rec in enumerate(snapshot.get("top_overall", []), start=1):
            _append_pick("top_overall", idx, rec, base_date, None, None)

        for game_snapshot in snapshot.get("games", []):
            game_context = game_snapshot.get("game", {})
            game_date = str(game_context.get("game_time", base_date)).split("T")[0]
            home_team = game_context.get("home_team")
            away_team = game_context.get("away_team")
            for idx, rec in enumerate(game_snapshot.get("top_plays", []), start=1):
                _append_pick("top_plays", idx, rec, game_date, home_team, away_team)
            best_bet = game_snapshot.get("best_bet")
            if isinstance(best_bet, dict):
                _append_pick("best_bet", 1, best_bet, game_date, home_team, away_team)
            underdog = game_snapshot.get("underdog_value_play")
            if isinstance(underdog, dict):
                _append_pick("underdog_value_play", 1, underdog, game_date, home_team, away_team)

        return output_rows

    def _build_xlsx_bytes(
        self,
        header: list[str],
        rows: list[list[str | int | float | None]],
    ) -> bytes:
        buffer = BytesIO()
        sheet_xml = self._build_sheet_xml([header, *rows])
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", _CONTENT_TYPES_XML)
            archive.writestr("_rels/.rels", _ROOT_RELS_XML)
            archive.writestr("xl/workbook.xml", _WORKBOOK_XML)
            archive.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS_XML)
            archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        return buffer.getvalue()

    def _build_sheet_xml(self, rows: list[list[str | int | float | None]]) -> str:
        row_xml: list[str] = []
        for row_index, row in enumerate(rows, start=1):
            cells: list[str] = []
            for col_index, value in enumerate(row, start=1):
                cell_ref = f"{_column_name(col_index)}{row_index}"
                if value is None:
                    continue
                if isinstance(value, (int, float)):
                    cells.append(f'<c r="{cell_ref}"><v>{value}</v></c>')
                else:
                    escaped = escape(str(value))
                    cells.append(f'<c r="{cell_ref}" t="inlineStr"><is><t>{escaped}</t></is></c>')
            row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(row_xml)}</sheetData>'
            "</worksheet>"
        )

    def grade_snapshots(
        self,
        selected_date: date | None = None,
        market: Market | None = None,
        *,
        now_utc: datetime | None = None,
    ) -> int:
        with self._lock:
            payload = self._load_storage_unlocked()
            snapshots = payload["snapshots"]
            outcome_cache: dict[str, GameOutcome] = {}
            changes = 0
            for snapshot in snapshots:
                if selected_date is not None and snapshot.get("date") != selected_date.isoformat():
                    continue
                snapshot_market = snapshot.get("market")
                if market is not None and snapshot_market != market:
                    continue
                if snapshot_market not in {"first_goal", "anytime"}:
                    continue
                changes += self._grade_snapshot(snapshot, snapshot_market, outcome_cache, now_utc=now_utc)
            if changes > 0:
                self._save_storage_unlocked(payload)
            return changes

    def _grade_snapshot(
        self,
        snapshot: dict,
        market: Market,
        outcome_cache: dict[str, GameOutcome],
        *,
        now_utc: datetime | None = None,
    ) -> int:
        changes = 0
        graded_at = (now_utc or datetime.now(timezone.utc)).isoformat()
        for rec in _iter_snapshot_picks(snapshot):
            game_id = str(rec.get("game_id", "")).strip()
            player_id = str(rec.get("player_id", "")).strip()
            if not game_id or not player_id:
                continue
            existing_status = rec.get("result_status")
            existing_completed = bool(rec.get("game_completed", False))
            if existing_completed and existing_status in {RESULT_HIT, RESULT_MISS}:
                continue
            outcome = outcome_cache.get(game_id)
            if outcome is None:
                outcome = self._outcome_fetcher(game_id)
                outcome_cache[game_id] = outcome
            new_fields = _grade_pick_fields(rec=rec, market=market, player_id=player_id, outcome=outcome, graded_at=graded_at)
            if _merge_updates(rec, new_fields):
                changes += 1
        return changes

    def _load_storage(self) -> dict:
        with self._lock:
            return self._load_storage_unlocked()

    def _load_storage_unlocked(self) -> dict:
        if not self._storage_path.exists():
            return {"snapshots": []}
        with self._storage_path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        snapshots = loaded.get("snapshots") if isinstance(loaded, dict) else None
        if not isinstance(snapshots, list):
            return {"snapshots": []}
        return {"snapshots": snapshots}

    def _save_storage(self, payload: dict) -> None:
        with self._lock:
            self._save_storage_unlocked(payload)

    def _save_storage_unlocked(self, payload: dict) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=self._storage_path.parent, delete=False) as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        temp_path.replace(self._storage_path)

    def _find_snapshot(self, payload: dict, selected_date: date, market: Market) -> dict | None:
        for snapshot in payload["snapshots"]:
            if snapshot.get("date") == selected_date.isoformat() and snapshot.get("market") == market:
                return snapshot
        return None

    def _serialize_recommendation(self, recommendation: Recommendation) -> dict:
        return recommendation.model_dump(mode="json")

    def _serialize_game(self, game: GameSummary) -> dict:
        return game.model_dump(mode="json")


def _column_name(index: int) -> str:
    result = ""
    current = index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _iter_snapshot_picks(snapshot: dict):
    for rec in snapshot.get("top_overall", []):
        if isinstance(rec, dict):
            yield rec
    for game_snapshot in snapshot.get("games", []):
        if not isinstance(game_snapshot, dict):
            continue
        for rec in game_snapshot.get("top_plays", []):
            if isinstance(rec, dict):
                yield rec
        for bucket in ("best_bet", "underdog_value_play"):
            rec = game_snapshot.get(bucket)
            if isinstance(rec, dict):
                yield rec


def _merge_updates(rec: dict, updates: dict[str, object | None]) -> bool:
    changed = False
    for key, value in updates.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    return changed


def _grade_pick_fields(*, rec: dict, market: Market, player_id: str, outcome: GameOutcome, graded_at: str) -> dict[str, object | None]:
    if not outcome.game_completed:
        return {
            "result_status": RESULT_PENDING,
            "game_completed": False,
            "graded_at": None,
            "actual_stat_value": None,
            "actual_result_detail": None,
        }

    if market == "first_goal":
        hit = outcome.first_goal_scorer_player_id == player_id
        detail = "scored first goal" if hit else "did not score first goal"
        actual_value = 1 if hit else 0
    else:
        goals = int(outcome.goal_counts_by_player_id.get(player_id, 0))
        hit = goals >= 1
        detail = f"scored {goals} goal" if goals == 1 else f"scored {goals} goals"
        actual_value = goals

    return {
        "result_status": RESULT_HIT if hit else RESULT_MISS,
        "game_completed": True,
        "graded_at": graded_at,
        "actual_stat_value": actual_value,
        "actual_result_detail": detail,
    }


def _fetch_game_outcome(game_id: str) -> GameOutcome:
    payload = fetch_json(
        url=f"{NHL_WEB_BASE}/gamecenter/{game_id}/play-by-play",
        timeout_seconds=NHL_PLAY_BY_PLAY_TIMEOUT_SECONDS,
    )
    game_state = str(payload.get("gameState", "")).strip().upper()
    game_completed = game_state in FINAL_GAME_STATES
    plays = payload.get("plays")
    if not isinstance(plays, list):
        return GameOutcome(
            game_completed=game_completed,
            first_goal_scorer_player_id=None,
            goal_counts_by_player_id={},
        )

    goals = [play for play in plays if isinstance(play, dict) and play.get("typeDescKey") == "goal"]
    goals_sorted = sorted(goals, key=lambda play: int(play.get("sortOrder", 10**9)))
    first_goal_scorer: str | None = None
    goal_counts: dict[str, int] = {}
    for idx, goal in enumerate(goals_sorted):
        details = goal.get("details")
        if not isinstance(details, dict):
            continue
        scorer_raw = details.get("scoringPlayerId")
        scorer = str(scorer_raw).strip() if scorer_raw is not None else ""
        if not scorer:
            continue
        goal_counts[scorer] = goal_counts.get(scorer, 0) + 1
        if idx == 0:
            first_goal_scorer = scorer
    return GameOutcome(
        game_completed=game_completed,
        first_goal_scorer_player_id=first_goal_scorer,
        goal_counts_by_player_id=goal_counts,
    )


_CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>
"""

_ROOT_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""

_WORKBOOK_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="recommendations" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
"""

_WORKBOOK_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
"""
