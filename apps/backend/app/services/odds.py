from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


STALE_ODDS_THRESHOLD = timedelta(minutes=30)


@dataclass(frozen=True)
class NormalizedPlayerOdds:
    """Normalized first-goal player pricing from any odds provider."""

    game_id: str
    player_id: str
    market_odds_american: int
    snapshot_at: datetime


def normalize_snapshot_timestamp(snapshot_at: datetime) -> datetime:
    """Ensure snapshot timestamps are timezone-aware UTC."""
    if snapshot_at.tzinfo is None:
        return snapshot_at.replace(tzinfo=timezone.utc)
    return snapshot_at.astimezone(timezone.utc)


def is_stale(snapshot_at: datetime, now: datetime | None = None) -> bool:
    reference_now = now or datetime.now(timezone.utc)
    normalized_snapshot = normalize_snapshot_timestamp(snapshot_at)
    return reference_now - normalized_snapshot > STALE_ODDS_THRESHOLD


def american_to_implied_probability(american_odds: int) -> float | None:
    """Convert American odds to implied probability in [0, 1]."""
    if american_odds == 0:
        return None

    if american_odds > 0:
        return 100 / (american_odds + 100)

    absolute_odds = abs(american_odds)
    return absolute_odds / (absolute_odds + 100)


def fair_american_odds(model_probability: float) -> int | None:
    """Convert a model probability to no-vig fair American odds."""
    if model_probability <= 0 or model_probability >= 1:
        return None

    if model_probability < 0.5:
        fair_value = 100 * ((1 - model_probability) / model_probability)
        return int(round(fair_value))

    fair_value = -100 * (model_probability / (1 - model_probability))
    return int(round(fair_value))


def expected_value_per_unit(model_probability: float, american_odds: int) -> float | None:
    """Expected value for 1 unit risk using American odds net payout."""
    if model_probability <= 0 or model_probability >= 1 or american_odds == 0:
        return None

    payout_multiple = american_odds / 100 if american_odds > 0 else 100 / abs(american_odds)
    return (model_probability * payout_multiple) - (1 - model_probability)
