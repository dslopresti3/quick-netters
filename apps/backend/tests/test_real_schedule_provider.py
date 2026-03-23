from datetime import date
from urllib.error import URLError
from unittest.mock import patch

from app.services.provider_wiring import build_provider_registry_from_env
from app.services.projection_store import StoreBackedProjectionProvider
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

    games = _map_schedule_payload(payload)

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

    games = _map_schedule_payload(payload)

    assert games == []


def test_schedule_provider_returns_empty_when_upstream_fails() -> None:
    provider = NhlScheduleProvider()

    with patch("app.services.real_services.urlopen", side_effect=URLError("boom")):
        games = provider.fetch(date(2026, 3, 23))

    assert games == []


def test_registry_real_mode_uses_live_schedule_provider() -> None:
    with patch("app.services.provider_wiring.os.getenv", return_value=None):
        registry = build_provider_registry_from_env()

    assert isinstance(registry.schedule_provider, NhlScheduleProvider)

    assert isinstance(registry.projection_provider, StoreBackedProjectionProvider)
