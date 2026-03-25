# Odds and Value Recommendation Layer

This document describes the backend service logic that converts model projections + market odds into recommendation buckets.

## Service boundaries

- Odds ingestion is abstracted behind `OddsProvider`.
- Projection ingestion is abstracted behind `ProjectionProvider`.
- Bucket selection and recommendation math are computed in `ValueRecommendationService` (backend/service layer).
- API routes expose precomputed recommendation objects; they do not recompute pricing math.

## Recommendation buckets (single-game)

For `GET /recommendations/game`, the backend returns three bucketed outputs:

- `top_plays` (Top 3 Plays)
- `best_bet`
- `underdog_value_play`

It also returns `recommendations` for compatibility, which currently aligns with `top_plays`.

### Bucket intent

- **Top 3 Plays**: broader blended ranking of strongest overall candidates.
  - Not simply the top 3 by model probability.
- **Best Bet**: strongest strict value play from tighter eligibility filters.
- **Underdog Value Play**: higher-odds value option with positive EV and edge.
  - May be `null` if no underdog candidate qualifies.

## Recommendation fields

Each recommendation includes these value metrics:

- `model_probability`
- `market_odds`
- `decimal_odds`
- `implied_probability`
- `edge`
- `ev`

Additional metadata (for example confidence and timestamps) is included where available.

## Normalized odds shape

Provider records are normalized into `NormalizedPlayerOdds`:

- `game_id` (string)
- `player_id` (string)
- `market_odds_american` (int)
- `snapshot_at` (UTC datetime)

When multiple snapshots exist for the same game/player, the latest timestamp is used.

## Freshness and validity handling

A player is excluded when odds are stale/invalid or pricing math cannot be computed.

Current checks include:

- stale snapshot filtering (30-minute threshold),
- `market_odds_american == 0` exclusion,
- invalid probability/odds conversions,
- non-positive edge/EV for strict value buckets.

## Core formulas

### Implied probability from American odds

- Positive odds (`+X`): `100 / (X + 100)`
- Negative odds (`-X`): `X / (X + 100)`, where `X = abs(odds)`

### Fair American odds from model probability `p`

- If `p < 0.5`: `+100 * (1 - p) / p`
- If `p >= 0.5`: `-100 * p / (1 - p)`
- `p <= 0` or `p >= 1` is invalid

### Edge

- `edge = model_probability - implied_probability`

### EV (per 1 unit risk)

Let `b` be net payout multiplier for 1 unit risk:

- Positive odds `+X`: `b = X / 100`
- Negative odds `-X`: `b = 100 / X`, where `X = abs(odds)`

Then:

- `ev = p * b - (1 - p)`

## Ranking notes

- Game-level Top 3 Plays are selected via blended play scoring within eligibility constraints.
- Best Bet is selected from stricter value-eligible candidates.
- Underdog Value Play uses a separate higher-odds scoring/eligibility path.
