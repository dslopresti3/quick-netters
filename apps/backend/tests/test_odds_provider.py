import json
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from app.services.odds_provider import TheOddsApiAdapter, TheOddsApiClient


def test_the_odds_api_client_uses_the_odds_api_key_fallback_env(monkeypatch) -> None:
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    monkeypatch.setenv("THE_ODDS_API_KEY", "fallback-key")

    client = TheOddsApiClient()

    assert client._api_key == "fallback-key"


def test_the_odds_api_adapter_normalizes_rows_into_internal_schema() -> None:
    now = datetime(2026, 3, 23, 22, 0, tzinfo=timezone.utc)
    raw_events = [
        {
            "id": "evt-100",
            "away_team": "NY Rangers",
            "home_team": "Boston Bruins",
            "commence_time": "2026-03-23T23:00:00Z",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": "player_goal_scorer_first",
                            "last_update": "2026-03-23T21:55:00Z",
                            "outcomes": [
                                {"name": "Artemi Panarin", "price": "+425"},
                                {"name": "David Pastrnak", "price": 360},
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    rows = TheOddsApiAdapter(source_name="the-odds-api").normalize(raw_events, now=now)

    assert len(rows) == 2
    assert rows[0].nhl_game_id is None
    assert rows[0].nhl_player_id is None
    assert rows[0].provider_event_id == "evt-100"
    assert rows[0].provider_player_name_raw == "Artemi Panarin"
    assert rows[0].market_odds_american == 425
    assert rows[0].source == "the-odds-api"
    assert rows[0].book == "draftkings"
    assert rows[0].freshness_seconds == 300
    assert rows[0].is_fresh is True


def test_the_odds_api_adapter_skips_invalid_or_malformed_rows() -> None:
    now = datetime(2026, 3, 23, 22, 0, tzinfo=timezone.utc)
    raw_events = [
        {
            "id": "evt-100",
            "away_team": "NY Rangers",
            "home_team": "Boston Bruins",
            "bookmakers": [
                {
                    "key": "fanduel",
                    "markets": [
                        {
                            "key": "player_goal_scorer_first",
                            "last_update": "2026-03-23T21:50:00Z",
                            "outcomes": [
                                {"name": "Bad Price A", "price": "N/A"},
                                {"name": "Bad Price B", "price": 0},
                                {"name": "", "price": 250},
                                {"name": "Valid Name", "price": -110},
                            ],
                        }
                    ],
                }
            ],
        },
        {"id": None, "bookmakers": []},
    ]

    rows = TheOddsApiAdapter(source_name="the-odds-api").normalize(raw_events, now=now)

    assert len(rows) == 1
    assert rows[0].provider_player_name_raw == "Valid Name"
    assert rows[0].market_odds_american == -110


def test_the_odds_api_adapter_skips_stale_rows() -> None:
    now = datetime(2026, 3, 23, 22, 0, tzinfo=timezone.utc)
    stale_update = (now - timedelta(minutes=45)).isoformat().replace("+00:00", "Z")
    raw_events = [
        {
            "id": "evt-100",
            "bookmakers": [
                {
                    "key": "fanduel",
                    "markets": [
                        {
                            "key": "player_goal_scorer_first",
                            "last_update": stale_update,
                            "outcomes": [{"name": "Artemi Panarin", "price": 425}],
                        }
                    ],
                }
            ],
        }
    ]

    rows = TheOddsApiAdapter(source_name="the-odds-api").normalize(raw_events, now=now)
    assert rows == []


def test_the_odds_api_client_fetches_event_odds_from_event_endpoints() -> None:
    selected_date = date(2026, 3, 23)
    events_payload = [
        {"id": "evt-1", "commence_time": "2026-03-23T22:00:00Z"},
        {"id": "evt-2", "commence_time": "2026-03-24T02:00:00Z"},
        {"id": None},
    ]
    event_1_odds_payload = {
        "id": "evt-1",
        "away_team": "New York Rangers",
        "home_team": "Boston Bruins",
        "bookmakers": [],
    }
    event_2_odds_payload = {
        "id": "evt-2",
        "away_team": "Los Angeles Kings",
        "home_team": "Seattle Kraken",
        "bookmakers": [],
    }

    responses = [
        BytesIO(json.dumps(events_payload).encode("utf-8")),
        BytesIO(json.dumps(event_1_odds_payload).encode("utf-8")),
        BytesIO(json.dumps(event_2_odds_payload).encode("utf-8")),
    ]

    class _Response:
        def __init__(self, body: BytesIO):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *args, **kwargs):
            return self._body.read(*args, **kwargs)

    requested_urls: list[str] = []

    def _fake_urlopen(request, timeout=10):  # noqa: ANN001
        requested_urls.append(request.full_url)
        return _Response(responses.pop(0))

    client = TheOddsApiClient(api_key="test-key")
    with patch("app.services.odds_provider.urlopen", side_effect=_fake_urlopen):
        rows = client.fetch_raw_events(selected_date)

    assert len(rows) == 2
    assert rows[0]["id"] == "evt-1"
    assert rows[1]["id"] == "evt-2"
    assert "/events?" in requested_urls[0]
    assert "/events/evt-1/odds?" in requested_urls[1]
    assert "/events/evt-2/odds?" in requested_urls[2]


def test_the_odds_api_client_applies_eastern_slate_window_after_events_fetch() -> None:
    selected_date = date(2026, 3, 24)

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *args, **kwargs):
            return json.dumps(
                [
                    {"id": "outside-window", "commence_time": "2026-03-24T03:59:59Z"},
                    {"id": "inside-window-1", "commence_time": "2026-03-24T04:00:00Z"},
                    {"id": "inside-window-2", "commence_time": "2026-03-25T03:59:59Z"},
                    {"id": "outside-window-2", "commence_time": "2026-03-25T04:00:00Z"},
                ]
            ).encode("utf-8")

    requested_urls: list[str] = []

    def _fake_urlopen(request, timeout=10):  # noqa: ANN001
        requested_urls.append(request.full_url)
        return _Response()

    client = TheOddsApiClient(api_key="test-key")
    with patch("app.services.odds_provider.urlopen", side_effect=_fake_urlopen):
        event_ids = client.fetch_event_ids_for_slate(selected_date)

    assert event_ids == ["inside-window-1", "inside-window-2"]
    assert len(requested_urls) == 1

    parsed = urlparse(requested_urls[0])
    query = parse_qs(parsed.query)
    assert query == {"apiKey": ["test-key"], "dateFormat": ["iso"]}


def test_the_odds_api_client_event_level_odds_request_uses_expected_params() -> None:
    event_odds_payload = {"id": "evt-1", "bookmakers": []}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *args, **kwargs):
            return json.dumps(event_odds_payload).encode("utf-8")

    requested_urls: list[str] = []

    def _fake_urlopen(request, timeout=10):  # noqa: ANN001
        requested_urls.append(request.full_url)
        return _Response()

    client = TheOddsApiClient(api_key="test-key")
    with patch("app.services.odds_provider.urlopen", side_effect=_fake_urlopen):
        payload = client._fetch_event_odds("evt-1")

    assert payload == event_odds_payload
    assert len(requested_urls) == 1
    assert "/events/evt-1/odds?" in requested_urls[0]
    parsed = urlparse(requested_urls[0])
    query = parse_qs(parsed.query)
    assert query == {
        "apiKey": ["test-key"],
        "regions": ["us"],
        "bookmakers": ["draftkings"],
        "markets": ["player_goal_scorer_first"],
        "oddsFormat": ["american"],
        "dateFormat": ["iso"],
    }


def test_the_odds_api_adapter_uses_description_for_generic_yes_no_outcome_names() -> None:
    now = datetime(2026, 3, 25, 22, 0, tzinfo=timezone.utc)
    raw_events = [
        {
            "id": "evt-200",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": "player_goal_scorer_first",
                            "last_update": "2026-03-25T21:55:00Z",
                            "outcomes": [
                                {"name": "Yes", "description": "Artemi Panarin", "price": "+750"},
                                {"name": "No", "description": "Artemi Panarin", "price": "-1800"},
                                {"name": "Over", "description": "Connor McDavid", "price": "+650"},
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    rows = TheOddsApiAdapter(source_name="the-odds-api").normalize(raw_events, now=now)

    assert len(rows) == 3
    assert rows[0].provider_player_name_raw == "Artemi Panarin"
    assert rows[1].provider_player_name_raw == "Artemi Panarin"
    assert rows[2].provider_player_name_raw == "Connor McDavid"


def test_the_odds_api_adapter_skips_generic_outcome_name_without_player_description() -> None:
    now = datetime(2026, 3, 25, 22, 0, tzinfo=timezone.utc)
    raw_events = [
        {
            "id": "evt-201",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": "player_goal_scorer_first",
                            "last_update": "2026-03-25T21:55:00Z",
                            "outcomes": [
                                {"name": "Yes", "price": "+750"},
                                {"name": "No", "description": "No", "price": "+100"},
                                {"name": "Filip Forsberg", "price": "+800"},
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    rows = TheOddsApiAdapter(source_name="the-odds-api").normalize(raw_events, now=now)

    assert len(rows) == 1
    assert rows[0].provider_player_name_raw == "Filip Forsberg"
