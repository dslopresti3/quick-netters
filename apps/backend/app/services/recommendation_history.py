from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from app.api.schemas import GameSummary, Recommendation
from app.services.markets import Market
from app.services.recommendation_service import ValueRecommendationService
from app.services.interfaces import ScheduleProvider

EASTERN_TIMEZONE = ZoneInfo("America/New_York")


class RecommendationHistoryService:
    """Persist immutable recommendation snapshots after lock cutoff."""

    def __init__(
        self,
        recommendation_service: ValueRecommendationService,
        schedule_provider: ScheduleProvider,
        storage_path: Path,
    ) -> None:
        self._recommendation_service = recommendation_service
        self._schedule_provider = schedule_provider
        self._storage_path = storage_path
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
        existing = self.get_snapshot(selected_date, market)
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

        snapshot = {
            "date": selected_date.isoformat(),
            "market": market,
            "snapshot_created_at": (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
            "earliest_game_time_et": earliest_game_time_et.isoformat(),
            "lock_cutoff_et": lock_cutoff_et.isoformat(),
            "top_overall": [self._serialize_recommendation(rec) for rec in daily_top_three[:3]],
            "games": game_snapshots,
        }
        self._upsert_snapshot(snapshot)
        return snapshot

    def get_snapshot(self, selected_date: date, market: Market) -> dict | None:
        payload = self._load_storage()
        for snapshot in payload["snapshots"]:
            if snapshot.get("date") == selected_date.isoformat() and snapshot.get("market") == market:
                return snapshot
        return None

    def list_snapshots(self, selected_date: date | None = None, market: Market | None = None) -> list[dict]:
        payload = self._load_storage()
        snapshots = payload["snapshots"]
        filtered = [
            snapshot
            for snapshot in snapshots
            if (selected_date is None or snapshot.get("date") == selected_date.isoformat())
            and (market is None or snapshot.get("market") == market)
        ]
        return sorted(filtered, key=lambda row: (row.get("date", ""), row.get("market", "")), reverse=True)

    def export_csv(self, selected_date: date | None = None, market: Market | None = None) -> str:
        snapshots = self.list_snapshots(selected_date=selected_date, market=market)
        header = [
            "date",
            "market",
            "game_id",
            "bucket",
            "rank",
            "player_id",
            "player_name",
            "team_name",
            "model_probability",
            "market_odds",
            "edge",
            "ev",
        ]
        rows = [",".join(header)]
        for snapshot in snapshots:
            rows.extend(self._snapshot_rows(snapshot))
        return "\n".join(rows)

    def _snapshot_rows(self, snapshot: dict) -> list[str]:
        output_rows: list[str] = []
        base_date = snapshot["date"]
        base_market = snapshot["market"]

        def _append_pick(bucket: str, rank: int, rec: dict, game_id: str = "overall") -> None:
            output_rows.append(
                ",".join(
                    [
                        base_date,
                        base_market,
                        game_id,
                        bucket,
                        str(rank),
                        rec.get("player_id", ""),
                        rec.get("player_name", ""),
                        rec.get("team_name", rec.get("player_team", "")) or "",
                        str(rec.get("model_probability", "")),
                        str(rec.get("market_odds", "")),
                        str(rec.get("edge", "")),
                        str(rec.get("ev", "")),
                    ]
                )
            )

        for idx, rec in enumerate(snapshot.get("top_overall", []), start=1):
            _append_pick("top_overall", idx, rec)

        for game_snapshot in snapshot.get("games", []):
            game_id = game_snapshot.get("game", {}).get("game_id", "")
            for idx, rec in enumerate(game_snapshot.get("top_plays", []), start=1):
                _append_pick("top_plays", idx, rec, game_id=game_id)
            best_bet = game_snapshot.get("best_bet")
            if isinstance(best_bet, dict):
                _append_pick("best_bet", 1, best_bet, game_id=game_id)
            underdog = game_snapshot.get("underdog_value_play")
            if isinstance(underdog, dict):
                _append_pick("underdog_value_play", 1, underdog, game_id=game_id)

        return output_rows

    def _upsert_snapshot(self, snapshot: dict) -> None:
        with self._lock:
            payload = self._load_storage()
            snapshots = [
                row
                for row in payload["snapshots"]
                if not (row.get("date") == snapshot["date"] and row.get("market") == snapshot["market"])
            ]
            snapshots.append(snapshot)
            payload["snapshots"] = snapshots
            self._save_storage(payload)

    def _load_storage(self) -> dict:
        if not self._storage_path.exists():
            return {"snapshots": []}
        with self._storage_path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        snapshots = loaded.get("snapshots") if isinstance(loaded, dict) else None
        if not isinstance(snapshots, list):
            return {"snapshots": []}
        return {"snapshots": snapshots}

    def _save_storage(self, payload: dict) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self._storage_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    def _serialize_recommendation(self, recommendation: Recommendation) -> dict:
        return recommendation.model_dump(mode="json")

    def _serialize_game(self, game: GameSummary) -> dict:
        return game.model_dump(mode="json")
