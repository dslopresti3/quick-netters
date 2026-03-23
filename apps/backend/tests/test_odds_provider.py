from datetime import date, datetime, timedelta, timezone

from app.services.odds_provider import TheOddsApiAdapter


def test_the_odds_api_adapter_normalizes_rows_into_internal_schema() -> None:
    now = datetime(2026, 3, 23, 22, 0, tzinfo=timezone.utc)
    raw_events = [
        {
            "id": "evt-100",
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
    assert rows[0].game_id == "evt-100"
    assert rows[0].player_id == "player-artemi-panarin"
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
    assert rows[0].player_id == "player-valid-name"
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
