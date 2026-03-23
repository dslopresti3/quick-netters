from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.services.interfaces import OddsProvider
from app.services.odds import NormalizedPlayerOdds, STALE_ODDS_THRESHOLD, normalize_snapshot_timestamp


class TheOddsApiClient:
    """Thin HTTP client for The Odds API NHL player first-goal market feed."""

    base_url = "https://api.the-odds-api.com/v4/sports/icehockey_nhl/odds"
    provider_name = "the-odds-api"

    def __init__(self, api_key: str | None = None, timeout_seconds: int = 10) -> None:
        self._api_key = api_key or os.getenv("ODDS_API_KEY")
        self._timeout_seconds = timeout_seconds

    def fetch_raw_events(self, selected_date: date) -> list[dict[str, Any]]:
        if not self._api_key:
            return []

        window_start = datetime.combine(selected_date, datetime.min.time(), tzinfo=timezone.utc)
        window_end = window_start + timedelta(days=1)
        params = urlencode(
            {
                "apiKey": self._api_key,
                "regions": "us",
                "markets": "player_first_goal_scorer",
                "oddsFormat": "american",
                "dateFormat": "iso",
                "commenceTimeFrom": window_start.isoformat(),
                "commenceTimeTo": window_end.isoformat(),
            }
        )
        request = Request(f"{self.base_url}?{params}", headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return []

        if not isinstance(payload, list):
            return []
        return [row for row in payload if isinstance(row, dict)]


class TheOddsApiAdapter:
    """Normalize The Odds API payloads into app-internal odds snapshots."""

    market_key = "player_first_goal_scorer"

    def __init__(self, source_name: str, stale_threshold: timedelta = STALE_ODDS_THRESHOLD) -> None:
        self._source_name = source_name
        self._stale_threshold = stale_threshold

    def normalize(self, raw_events: list[dict[str, Any]], now: datetime | None = None) -> list[NormalizedPlayerOdds]:
        normalized_rows: list[NormalizedPlayerOdds] = []
        reference_now = now or datetime.now(timezone.utc)

        for event in raw_events:
            provider_event_id = self._extract_event_id(event)
            away_team_raw = _extract_string(event.get("away_team"))
            home_team_raw = _extract_string(event.get("home_team"))
            provider_start_time = self._extract_provider_start_time(event)

            bookmakers = event.get("bookmakers")
            if not isinstance(bookmakers, list):
                continue

            for bookmaker in bookmakers:
                if not isinstance(bookmaker, dict):
                    continue
                book = self._extract_book(bookmaker)
                markets = bookmaker.get("markets")
                if not isinstance(markets, list):
                    continue

                for market in markets:
                    if not isinstance(market, dict) or market.get("key") != self.market_key:
                        continue

                    snapshot_at = self._extract_snapshot_timestamp(market, bookmaker, reference_now)
                    freshness_seconds = max(int((reference_now - snapshot_at).total_seconds()), 0)
                    is_fresh = freshness_seconds <= int(self._stale_threshold.total_seconds())
                    freshness_status = "fresh" if is_fresh else "stale"
                    if not is_fresh:
                        continue

                    outcomes = market.get("outcomes")
                    if not isinstance(outcomes, list):
                        continue

                    for outcome in outcomes:
                        row = self._normalize_outcome(
                            outcome=outcome,
                            provider_event_id=provider_event_id,
                            away_team_raw=away_team_raw,
                            home_team_raw=home_team_raw,
                            provider_start_time=provider_start_time,
                            snapshot_at=snapshot_at,
                            book=book,
                            freshness_seconds=freshness_seconds,
                            is_fresh=is_fresh,
                            freshness_status=freshness_status,
                        )
                        if row is not None:
                            normalized_rows.append(row)

        return normalized_rows

    def _normalize_outcome(
        self,
        outcome: Any,
        provider_event_id: str | None,
        away_team_raw: str | None,
        home_team_raw: str | None,
        provider_start_time: datetime | None,
        snapshot_at: datetime,
        book: str | None,
        freshness_seconds: int,
        is_fresh: bool,
        freshness_status: str,
    ) -> NormalizedPlayerOdds | None:
        if not isinstance(outcome, dict):
            return None

        player_name = _extract_string(outcome.get("name"))
        if player_name is None:
            return None

        odds_price = _parse_american_odds(outcome.get("price"))
        if odds_price is None:
            return None

        return NormalizedPlayerOdds(
            nhl_game_id=None,
            nhl_player_id=None,
            market_odds_american=odds_price,
            snapshot_at=snapshot_at,
            provider_name=self._source_name,
            provider_event_id=provider_event_id,
            provider_player_id=_extract_string(outcome.get("id")),
            provider_player_name_raw=player_name,
            provider_team_raw=_extract_string(outcome.get("description")),
            away_team_raw=away_team_raw,
            home_team_raw=home_team_raw,
            provider_start_time=provider_start_time,
            source=self._source_name,
            book=book,
            freshness_seconds=freshness_seconds,
            freshness_status=freshness_status,
            is_fresh=is_fresh,
        )

    @staticmethod
    def _extract_event_id(event: dict[str, Any]) -> str | None:
        game_id = event.get("id")
        if isinstance(game_id, str) and game_id.strip():
            return game_id
        if isinstance(game_id, int):
            return str(game_id)
        return None

    @staticmethod
    def _extract_book(bookmaker: dict[str, Any]) -> str | None:
        book_key = bookmaker.get("key")
        if isinstance(book_key, str) and book_key.strip():
            return book_key
        book_title = bookmaker.get("title")
        if isinstance(book_title, str) and book_title.strip():
            return book_title
        return None

    @staticmethod
    def _extract_provider_start_time(event: dict[str, Any]) -> datetime | None:
        commence_time = event.get("commence_time")
        if not isinstance(commence_time, str):
            return None
        try:
            return normalize_snapshot_timestamp(datetime.fromisoformat(commence_time.replace("Z", "+00:00")))
        except ValueError:
            return None

    @staticmethod
    def _extract_snapshot_timestamp(market: dict[str, Any], bookmaker: dict[str, Any], fallback: datetime) -> datetime:
        raw_timestamp = market.get("last_update")
        if not isinstance(raw_timestamp, str):
            raw_timestamp = bookmaker.get("last_update")
        if not isinstance(raw_timestamp, str):
            return fallback

        normalized = raw_timestamp.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return fallback
        return normalize_snapshot_timestamp(parsed)


class LiveOddsProvider(OddsProvider):
    """Production odds provider backed by The Odds API with adapter normalization."""

    def __init__(self, client: TheOddsApiClient | None = None, adapter: TheOddsApiAdapter | None = None) -> None:
        self._client = client or TheOddsApiClient()
        self._adapter = adapter or TheOddsApiAdapter(source_name=self._client.provider_name)

    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        raw_events = self._client.fetch_raw_events(selected_date)
        return self._adapter.normalize(raw_events)


def _extract_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_american_odds(raw_price: Any) -> int | None:
    if isinstance(raw_price, bool):
        return None

    numeric_price: float | None = None
    if isinstance(raw_price, (int, float)):
        numeric_price = float(raw_price)
    elif isinstance(raw_price, str):
        cleaned = raw_price.strip()
        if cleaned.startswith("+"):
            cleaned = cleaned[1:]
        try:
            numeric_price = float(cleaned)
        except ValueError:
            return None

    if numeric_price is None:
        return None

    if numeric_price == 0:
        return None

    integer_price = int(numeric_price)
    if integer_price == 0:
        return None
    return integer_price
