# Date Availability Metadata Contract

The backend exposes `GET /availability/date?date=YYYY-MM-DD` so the frontend can drive date-picker limits and empty-state UX from API truth.

## Response schema

`DateAvailabilityResponse`

- `selected_date`: date requested by the client.
- `min_allowed_date`: product-rule lower bound for user selection.
- `max_allowed_date`: product-rule upper bound for user selection.
- `valid_by_product_rule`: `true` only when `selected_date` is within `[min_allowed_date, max_allowed_date]`.
- `schedule_available`: whether scheduled games exist for the date.
- `projections_available`: whether projection rows exist for the date.
- `odds_available`: whether odds snapshots exist for the date.
- `status`:
  - `invalid_date`
  - `no_schedule`
  - `missing_projections`
  - `missing_odds`
  - `ready`
- `messages`: UI-ready messages that explain current availability.

## Frontend integration guidance

1. Call `/availability/date` whenever selected date changes (or on initial load).
2. Bind date picker bounds directly to `min_allowed_date` and `max_allowed_date`.
3. Use `valid_by_product_rule` + `status` to drive UI state:
   - `invalid_date`: block data requests and show `messages`.
   - `no_schedule`: show no-games state.
   - `missing_projections`: show schedule-only state; hide recommendation buckets.
   - `missing_odds`: show schedule/projection context; hide value buckets.
   - `ready`: render full recommendation experience.
4. Call `/games`, `/recommendations/daily`, and `/recommendations/game` only when state supports it.

## Interaction with recommendation buckets

For game detail UX, full bucket rendering requires `status=ready`:

- Top 3 Plays
- Best Bet
- Underdog Value Play

If underdog data is unavailable for a ready game, `underdog_value_play` may be `null`; the UI should hide that section gracefully.

## Product-rule restriction

By default, users may select only UTC today and UTC tomorrow.

- Enforced by `ensure_date_not_more_than_one_day_ahead`.
- If `STRICT_TODAY_TOMORROW_DATE_WINDOW=false` is explicitly configured, historical dates are allowed while the upper bound remains tomorrow.
