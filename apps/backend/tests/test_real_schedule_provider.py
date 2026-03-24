import io
import json
from datetime import date
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from app.services.provider_wiring import build_provider_registry_from_env
from app.services.odds_provider import LiveOddsProvider
from app.services.dev_projection_provider import AutoGeneratingProjectionProvider
from app.services.real_services import NhlScheduleProvider, _map_schedule_payload


def test_map_schedule_payload_maps_games_into_internal_schema() -> None:
    payload = {
        "gameWeek": [
            {
                "games": [
                    {
                        "id": 2025020001,
                        "startTimeUTC": "2026-03-23T23:00:00Z",
                        "gameState": "FUT",
                        "awayTeam": {"commonName": {"default": "Rangers"}},
                        "homeTeam": {"commonName": {"default": "Bruins"}},
                    }
                ]
            }
        ]
    }

    games = _map_schedule_payload(payload, selected_date=date(2026, 3, 23))

    assert len(games) == 1
    assert games[0].game_id == "2025020001"
    assert games[0].away_team == "Rangers"
    assert games[0].home_team == "Bruins"
    assert games[0].status == "FUT"
    assert games[0].game_time.isoformat() == "2026-03-23T23:00:00+00:00"


def test_map_schedule_payload_returns_empty_for_no_games_or_malformed_rows() -> None:
    payload = {
        "gameWeek": [
            {"games": []},
            {"games": [{"id": "bad-row-with-missing-fields"}]},
        ]
    }

    games = _map_schedule_payload(payload, selected_date=date(2026, 3, 23))

    assert games == []


def test_map_schedule_payload_supports_top_level_games_shape() -> None:
    payload = {
        "games": [
            {
                "id": 2026020001,
                "gameDate": "2026-03-23",
                "startTimeUTC": "2026-03-23T23:00:00Z",
                "gameState": "FUT",
                "awayTeam": {"commonName": {"default": "Canadiens"}},
                "homeTeam": {"commonName": {"default": "Maple Leafs"}},
            }
        ]
    }

    games = _map_schedule_payload(payload, selected_date=date(2026, 3, 23))

    assert len(games) == 1
    assert games[0].game_id == "2026020001"
    assert games[0].away_team == "Canadiens"
    assert games[0].home_team == "Maple Leafs"


def test_map_schedule_payload_uses_week_date_when_game_date_missing() -> None:
    payload = {
        "gameWeek": [
            {
                "date": "2026-03-23",
                "games": [
                    {
                        "id": 2026020099,
                        "startTimeUTC": "2026-03-24T02:30:00Z",
                        "gameState": "FUT",
                        "awayTeam": {"commonName": {"default": "Sharks"}},
                        "homeTeam": {"commonName": {"default": "Kings"}},
                    }
                ],
            }
        ]
    }

    games = _map_schedule_payload(payload, selected_date=date(2026, 3, 23))

    assert len(games) == 1
    assert games[0].game_id == "2026020099"
    assert games[0].away_team == "Sharks"
    assert games[0].home_team == "Kings"
    assert games[0].game_time.isoformat() == "2026-03-24T02:30:00+00:00"


def test_map_schedule_payload_keeps_games_when_game_date_is_utc_next_day() -> None:
    payload = {
        "gameWeek": [
            {
                "date": "2026-03-23",
                "games": [
                    {
                        "id": 2026020101,
                        "gameDate": "2026-03-24",
                        "startTimeUTC": "2026-03-24T01:00:00Z",
                        "gameState": "FUT",
                        "awayTeam": {"commonName": {"default": "Devils"}},
                        "homeTeam": {"commonName": {"default": "Islanders"}},
                    }
                ],
            }
        ]
    }

    games = _map_schedule_payload(payload, selected_date=date(2026, 3, 23))

    assert len(games) == 1
    assert games[0].game_id == "2026020101"
    assert games[0].away_team == "Devils"
    assert games[0].home_team == "Islanders"


def test_schedule_provider_returns_empty_when_upstream_fails() -> None:
    provider = NhlScheduleProvider()

    with patch("app.services.real_services.urlopen", side_effect=URLError("boom")):
        games = provider.fetch(date(2026, 3, 23))

    assert games == []


def test_schedule_provider_returns_empty_and_sets_error_for_http_403() -> None:
    provider = NhlScheduleProvider()
    selected_date = date(2026, 3, 23)
    url = f"{provider.base_url}/{selected_date.isoformat()}"
    forbidden = HTTPError(url=url, code=403, msg="Forbidden", hdrs=None, fp=None)

    with patch("app.services.real_services.urlopen", side_effect=forbidden):
        games = provider.fetch(selected_date)

    assert games == []
    assert provider.last_fetch_error is not None
    assert "403" in provider.last_fetch_error
    assert url in provider.last_fetch_error


def test_schedule_provider_fetch_uses_browser_headers_and_parses_payload() -> None:
    provider = NhlScheduleProvider()
    selected_date = date(2026, 3, 23)
    payload = {
        "gameWeek": [
            {
                "date": "2026-03-23",
                "games": [
                    {
                        "id": 2026020101,
                        "gameDate": "2026-03-24",
                        "startTimeUTC": "2026-03-24T01:00:00Z",
                        "gameState": "FUT",
                        "awayTeam": {"commonName": {"default": "Devils"}},
                        "homeTeam": {"commonName": {"default": "Islanders"}},
                    }
                ],
            }
        ]
    }
    seen = {}

    class _FakeResponse(io.StringIO):
        def __init__(self, raw_payload: dict) -> None:
            super().__init__(json.dumps(raw_payload))

        def getcode(self) -> int:
            return 200

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            self.close()

    def _fake_urlopen(request, timeout: int):  # noqa: ANN001
        seen["request"] = request
        seen["timeout"] = timeout
        return _FakeResponse(payload)

    with patch("app.services.real_services.urlopen", side_effect=_fake_urlopen):
        games = provider.fetch(selected_date)

    request = seen["request"]
    assert request.full_url == "https://api-web.nhle.com/v1/schedule/2026-03-23"
    assert request.get_header("User-agent") is not None
    assert "Mozilla/5.0" in request.get_header("User-agent")
    assert request.get_header("Accept") == "application/json"
    assert seen["timeout"] == 10
    assert len(games) == 1


def test_registry_real_mode_uses_live_schedule_provider() -> None:
    with patch("app.services.provider_wiring.os.getenv", return_value=None):
        registry = build_provider_registry_from_env()

    assert isinstance(registry.schedule_provider, NhlScheduleProvider)

    assert isinstance(registry.projection_provider, AutoGeneratingProjectionProvider)
    assert isinstance(registry.odds_provider, LiveOddsProvider)
