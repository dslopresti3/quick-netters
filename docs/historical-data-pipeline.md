# Historical Data Pipeline Design (Quick Netters)

This document defines ingestion, normalization, and feature-ready historical outputs for hockey workflows.

## Scope

- Uses **last season + current season** as the modeling history window.
- Uses **MoneyPuck shot-level files** as the historical event source.
- Expects **public NHL endpoints** for schedule/roster inputs.
- Expects an **odds provider** for market price inputs where needed.
- Does **not** include model training orchestration or backend recommendation serving.

## Folder conventions

`data_root` defaults to `packages/modeling/data`.

### Raw conventions

```text
packages/modeling/data/raw/
  moneypuck/season=YYYY/shots.csv
  nhl_schedule/season=YYYY/*.json
  nhl_roster/season=YYYY/*.json
  odds/season=YYYY/odds.json
```

### Processed conventions

```text
packages/modeling/data/processed/
  shot_events/season=YYYY/shot_events.csv
  games/season=YYYY/games.csv
  player_games/season=YYYY/player_games.csv
  team_games/season=YYYY/team_games.csv
  features/season=YYYY/model_features.csv
```

## Normalized schemas

### Shot events (`shot_events`)

Primary key: `(season, game_id, event_id)`

Core columns:

- season
- game_id
- event_id
- event_time_utc (ISO-8601)
- period
- period_seconds
- team_id
- shooter_id
- goalie_id
- x_coord
- y_coord
- shot_type
- strength_state
- is_goal
- expected_goal

### Game table (`games`)

Primary key: `(season, game_id)`

Columns:

- season
- game_id
- game_date
- home_team_id
- away_team_id
- home_goals
- away_goals
- total_shots
- total_xg

### Player-game aggregates (`player_games`)

Primary key: `(season, game_id, player_id)`

Columns:

- season
- game_id
- player_id
- team_id
- shots
- goals
- xg

### Team-game aggregates (`team_games`)

Primary key: `(season, game_id, team_id)`

Columns:

- season
- game_id
- team_id
- opponent_team_id
- shots_for
- shots_against
- goals_for
- goals_against
- xg_for
- xg_against

## Feature-ready outputs

`model_features.csv` is generated at the team-game grain and includes:

- required `team_games`-derived features,
- market fields where available:
  - `market_moneyline`
  - `market_total`

## Validation checks

The pipeline enforces:

- missing table protection (`table is empty`),
- required column checks,
- missing value checks for key fields,
- duplicate primary key checks.

## Running

From repository root:

```bash
PYTHONPATH=packages/modeling/src python -m quick_netters_modeling.historical.cli --current-season 2026 --data-root packages/modeling/data
```

Alternative helper script:

```bash
PYTHONPATH=packages/modeling/src python packages/modeling/scripts/run_historical_pipeline.py --current-season 2026
```

## Historical NHL game backfill (regular season + postseason)

A dedicated backfill script now ingests historical game-level data directly from the same NHL API source used by the app (`api-web.nhle.com`).

### Endpoint used

- `GET /v1/schedule-season/{seasonKey}`

Where `seasonKey` is an NHL season key such as `20252026`.

### Game-type filtering at ingestion time

During ingestion, game rows are normalized and filtered immediately:

- include `gameType == 2` (regular season)
- include `gameType == 3` (postseason/playoffs)
- exclude `gameType == 1` (preseason)

Preseason games are not written into the normalized historical games output.

### Storage

- Raw snapshot per season:
  - `packages/modeling/data/raw/nhl_schedule/season=YYYYYYYY/schedule_season.json`
- Durable normalized merged table:
  - `packages/modeling/data/processed/historical_games/nhl_games.csv`

Rows are merged by `(season, game_id)` so reruns upsert without duplicating records.

### Manual run examples

Single season key:

```bash
PYTHONPATH=packages/modeling/src python packages/modeling/scripts/backfill_historical_nhl_games.py --season 20252026
```

Season start-year range:

```bash
PYTHONPATH=packages/modeling/src python packages/modeling/scripts/backfill_historical_nhl_games.py --season-start 2018 --season-end 2025
```

All discoverable supported seasons (probe-based):

```bash
PYTHONPATH=packages/modeling/src python packages/modeling/scripts/backfill_historical_nhl_games.py --all-supported --probe-start-year 1917
```
