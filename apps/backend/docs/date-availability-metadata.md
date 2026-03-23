# Date Availability Metadata Contract

The backend now exposes `GET /availability/date?date=YYYY-MM-DD` so the frontend can render date-picker and empty-state UX from server truth instead of local mocks.

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

1. Call `/availability/date` whenever the selected date changes (or during initial load).
2. Bind your date picker directly to `min_allowed_date` and `max_allowed_date`.
3. Use `valid_by_product_rule` + `status` to choose UI state:
   - `invalid_date`: block data requests and show `messages`.
   - `no_schedule`: show no-games state.
   - `missing_projections`: show schedule only; disable value picks.
   - `missing_odds`: show schedule/projections; disable value picks.
   - `ready`: proceed with full recommendations experience.
4. Keep calling existing data endpoints (`/games`, `/recommendations/daily`, `/recommendations/game`) only when state supports it.

## Product-rule restriction

By default, users may select only UTC today and UTC tomorrow.

- This is enforced by validation in `ensure_date_not_more_than_one_day_ahead`.
- If `STRICT_TODAY_TOMORROW_DATE_WINDOW=false` is explicitly configured, historical dates are allowed while the upper bound remains tomorrow.
