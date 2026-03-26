from __future__ import annotations

from typing import Literal

Market = Literal["first_goal", "anytime"]

DEFAULT_MARKET: Market = "first_goal"

FIRST_GOAL_ODDS_API_KEY = "player_goal_scorer_first"
ANYTIME_ODDS_API_KEY = "player_goal_scorer_anytime"

ODDS_API_MARKET_KEY_BY_MARKET: dict[Market, str] = {
    "first_goal": FIRST_GOAL_ODDS_API_KEY,
    "anytime": ANYTIME_ODDS_API_KEY,
}


def resolve_market(raw_market: str | None) -> Market:
    if raw_market == "anytime":
        return "anytime"
    return DEFAULT_MARKET


def odds_api_market_key_for_market(market: Market) -> str:
    return ODDS_API_MARKET_KEY_BY_MARKET[market]
