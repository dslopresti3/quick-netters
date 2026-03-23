# Odds and value layer assumptions

This document describes the assumptions and formulas used by the backend odds/value recommendation layer.

## Service boundaries

- Odds ingestion is abstracted behind `OddsProvider`.
- Recommendation ranking uses a `RecommendationsProvider` implementation (`ValueRecommendationService`) that depends on `OddsProvider`.
- Current implementation includes `MockOddsService` as a placeholder provider.

## Normalized odds shape

Each provider record is normalized into `NormalizedPlayerOdds`:

- `game_id` (string)
- `player_id` (string)
- `market_odds_american` (int)
- `snapshot_at` (UTC datetime)

When multiple snapshots exist for the same game/player, only the latest timestamp is used.

## Freshness / stale handling

- Snapshot recency threshold is **30 minutes** (`STALE_ODDS_THRESHOLD`).
- Stale snapshots are skipped.
- Missing snapshots are skipped.

## Pricing validity

A player is excluded from recommendations when:

- `market_odds_american == 0` (invalid odds)
- implied probability cannot be computed
- fair odds cannot be computed from model probability
- expected value cannot be computed

## Formulas

### Implied probability from American odds

- Positive odds (`+X`): `100 / (X + 100)`
- Negative odds (`-X`): `X / (X + 100)` using `X = abs(odds)`

### Fair American odds from model probability `p`

- If `p < 0.5` (underdog): `+ 100 * (1 - p) / p`
- If `p >= 0.5` (favorite): `- 100 * p / (1 - p)`
- `p <= 0` or `p >= 1` is invalid

### Edge

- `edge = model_probability - implied_probability`
- Only positive edge recommendations are kept.

### Expected value (per 1 unit risk)

Let `b` be the net payout multiplier for 1 unit risk:

- Positive odds `+X`: `b = X / 100`
- Negative odds `-X`: `b = 100 / X` using `X = abs(odds)`

Then:

- `EV = p * b - (1 - p)`

## Ranking

Recommendations are sorted descending by:

1. `ev`
2. `edge`
3. `model_probability`

Returned results are:

- top 3 daily value picks
- top 3 picks for a specific game

## API additions

Recommendations now include:

- `implied_probability`
- `odds_snapshot_at`
