from datetime import date, datetime, timedelta, timezone

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
                            "key": "player_first_goal_scorer",
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
                            "key": "player_first_goal_scorer",
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
                            "key": "player_first_goal_scorer",
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
