from datetime import date
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from app.api.routes import get_games
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


def test_map_schedule_payload_includes_game_after_0000_utc_when_it_is_previous_eastern_day() -> None:
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


def test_map_schedule_payload_excludes_game_when_it_is_truly_next_eastern_day() -> None:
    payload = {
        "gameWeek": [
            {
                "date": "2026-03-23",
                "games": [
                    {
                        "id": 2026020100,
                        "startTimeUTC": "2026-03-24T04:30:00Z",
                        "gameState": "FUT",
                        "awayTeam": {"commonName": {"default": "Sharks"}},
                        "homeTeam": {"commonName": {"default": "Kings"}},
                    }
                ],
            }
        ]
    }

    games = _map_schedule_payload(payload, selected_date=date(2026, 3, 23))

    assert games == []


def test_map_schedule_payload_uses_eastern_calendar_day_for_selected_slate() -> None:
    payload = {
        "gameWeek": [
            {
                "date": "2026-03-23",
                "games": [
                    {
                        "id": 2026020102,
                        "startTimeUTC": "2026-03-24T01:00:00Z",
                        "gameState": "FUT",
                        "awayTeam": {"commonName": {"default": "Devils"}},
                        "homeTeam": {"commonName": {"default": "Islanders"}},
                    },
                    {
                        "id": 2026020103,
                        "startTimeUTC": "2026-03-24T04:30:00Z",
                        "gameState": "FUT",
                        "awayTeam": {"commonName": {"default": "Panthers"}},
                        "homeTeam": {"commonName": {"default": "Lightning"}},
                    }
                ],
            }
        ]
    }

    games = _map_schedule_payload(payload, selected_date=date(2026, 3, 23))

    assert {game.game_id for game in games} == {"2026020102"}


def test_schedule_provider_returns_empty_when_upstream_fails() -> None:
    provider = NhlScheduleProvider()

    with patch("app.services.real_services.fetch_json", side_effect=URLError("boom")):
        games = provider.fetch(date(2026, 3, 23))

    assert games == []


def test_schedule_provider_returns_empty_and_sets_error_for_http_403() -> None:
    provider = NhlScheduleProvider()
    selected_date = date(2026, 3, 23)
    url = f"{provider.base_url}/{selected_date.isoformat()}"
    forbidden = HTTPError(url=url, code=403, msg="Forbidden", hdrs=None, fp=None)

    with patch("app.services.real_services.fetch_json", side_effect=forbidden):
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

    def _fake_fetch_json(*, url: str, headers: dict, timeout_seconds: int, opener):  # noqa: ANN001
        seen["url"] = url
        seen["headers"] = headers
        seen["timeout_seconds"] = timeout_seconds
        seen["opener"] = opener
        return payload

    with patch("app.services.real_services.fetch_json", side_effect=_fake_fetch_json):
        games = provider.fetch(selected_date)

    assert seen["url"] == "https://api-web.nhle.com/v1/schedule/2026-03-23"
    assert seen["headers"]["User-Agent"] is not None
    assert "Mozilla/5.0" in seen["headers"]["User-Agent"]
    assert seen["headers"]["Accept"] == "application/json, text/plain, */*"
    assert seen["timeout_seconds"] == 10
    assert seen["opener"] is not None
    assert len(games) == 1
    assert games[0].game_id == "2026020101"


def test_map_schedule_payload_filters_to_selected_slate_date_only() -> None:
    payload = {
        "gameWeek": [
            {
                "date": "2026-03-24",
                "games": [
                    {
                        "id": 1,
                        "startTimeUTC": "2026-03-23T23:00:00Z",
                        "awayTeam": {"commonName": {"default": "A"}},
                        "homeTeam": {"commonName": {"default": "B"}},
                    },
                    {
                        "id": 2,
                        "startTimeUTC": "2026-03-24T23:00:00Z",
                        "awayTeam": {"commonName": {"default": "C"}},
                        "homeTeam": {"commonName": {"default": "D"}},
                    },
                    {
                        "id": 3,
                        "startTimeUTC": "2026-03-25T01:00:00Z",
                        "awayTeam": {"commonName": {"default": "E"}},
                        "homeTeam": {"commonName": {"default": "F"}},
                    },
                    {
                        "id": 4,
                        "startTimeUTC": "2026-03-27T01:00:00Z",
                        "awayTeam": {"commonName": {"default": "G"}},
                        "homeTeam": {"commonName": {"default": "H"}},
                    },
                ],
            }
        ]
    }

    games = _map_schedule_payload(payload, selected_date=date(2026, 3, 24))
    assert {game.game_id for game in games} == {"2", "3"}


def test_registry_real_mode_uses_live_schedule_provider() -> None:
    with patch("app.services.provider_wiring.os.getenv", return_value=None):
        registry = build_provider_registry_from_env()

    assert isinstance(registry.schedule_provider, NhlScheduleProvider)

    assert isinstance(registry.projection_provider, AutoGeneratingProjectionProvider)
    assert isinstance(registry.odds_provider, LiveOddsProvider)


def test_registry_real_mode_disables_auto_projection_dev_fallback_by_default() -> None:
    def _fake_getenv(key: str, default=None):  # noqa: ANN001
        if key == "BACKEND_PROVIDER_MODE":
            return "real"
        if key == "AUTO_PROJECTION_DEV_FALLBACK":
            return "1"
        return default

    with patch("app.services.provider_wiring.os.getenv", side_effect=_fake_getenv):
        registry = build_provider_registry_from_env()

    assert isinstance(registry.projection_provider, AutoGeneratingProjectionProvider)
    assert registry.projection_provider._enable_dev_fallback is False  # noqa: SLF001


def test_real_mode_uses_nhl_rosters_and_nhl_player_ids_without_dev_ids() -> None:
    selected_date = date(2026, 3, 24)

    def _fake_getenv(key: str, default=None):  # noqa: ANN001
        if key == "BACKEND_PROVIDER_MODE":
            return "real"
        return default

    def _fake_fetch_json(*, url: str, headers=None, timeout_seconds=10, opener=None):  # noqa: ANN001
        if url.endswith("/schedule/2026-03-24"):
            return {
                "gameWeek": [
                    {
                        "date": "2026-03-24",
                        "games": [
                            {
                                "id": 2026020001,
                                "gameDate": "2026-03-24",
                                "startTimeUTC": "2026-03-24T23:00:00Z",
                                "gameState": "FUT",
                                "awayTeam": {"commonName": {"default": "NY Rangers"}},
                                "homeTeam": {"commonName": {"default": "Boston Bruins"}},
                            }
                        ],
                    }
                ]
            }
        if "/roster/NYR/current" in url:
            return {"forwards": [{"id": 8479323, "firstName": {"default": "Artemi"}, "lastName": {"default": "Panarin"}}]}
        if "/roster/BOS/current" in url:
            return {"forwards": [{"id": 8477956, "firstName": {"default": "David"}, "lastName": {"default": "Pastrnak"}}]}
        if "/player/8479323/game-log/" in url:
            return {"gameLog": [{"firstGoals": 1}]}
        if "/player/8477956/game-log/" in url:
            return {"gameLog": [{"firstGoals": 1}]}
        return {}

    with patch("app.services.provider_wiring.os.getenv", side_effect=_fake_getenv):
        registry = build_provider_registry_from_env()

    with patch("app.services.real_services.fetch_json", side_effect=_fake_fetch_json), patch(
        "app.services.nhl_api_data.fetch_json", side_effect=_fake_fetch_json
    ):
        response = get_games(date=selected_date, providers=registry)

    assert response.games
    for game in response.games:
        for leader in (game.away_top_projected_scorer, game.home_top_projected_scorer):
            assert leader is not None
            assert not leader.player_id.startswith("dev-")
