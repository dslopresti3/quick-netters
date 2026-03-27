# NHL API Historical Coverage Audit (Existing Integration)

_Date:_ 2026-03-27

## Scope and constraints applied

- Audited only the app's **existing NHL API integration** (`api-web.nhle.com/v1`) used in backend services.
- Focused on game-level data flow and season/date filtering behavior already present in code.
- Did **not** redesign recommendation logic or swap in a new primary game data source.

## Current NHL API endpoints in use

The backend currently uses these NHL API endpoints:

1. **Daily schedule**
   - `GET /v1/schedule/{YYYY-MM-DD}`
   - Used by both the production schedule provider and first-goal-derived backfill/refresh routines.
2. **Game play-by-play**
   - `GET /v1/gamecenter/{gameId}/play-by-play`
   - Used to identify the first goal scorer and first-period goal scorers.
3. **Current team roster**
   - `GET /v1/roster/{TEAM_ABBREV}/current`
   - Used to build eligible player pools in real mode.
4. **Player game log by season and game type**
   - `GET /v1/player/{playerId}/game-log/{season}/2`
   - Currently hardcoded to game-type segment `2` (regular season) for player historical stats.

## Where endpoints are called from

- `NhlScheduleProvider.fetch(...)` calls `/schedule/{date}` for slate-level game retrieval.
- `refresh_incremental_first_goal_derived_data(...)` calls `/schedule/{date}` then `/gamecenter/{id}/play-by-play`.
- `backfill_current_regular_season_first_goal_derived_data(...)` scans `/schedule/{date}` across a date range and calls `/gamecenter/{id}/play-by-play` for filtered games.
- `fetch_team_roster_current(...)` calls `/roster/{team}/current`.
- `fetch_player_first_goal_history(...)` calls `/player/{id}/game-log/{season}/2`.
- `fetch_first_goal_scorer_player_id(...)` in recommendation performance uses `/gamecenter/{id}/play-by-play`.

## Game-level fields already being pulled

### Schedule-level fields currently consumed

From schedule payloads, current code uses:

- `id` -> internal `game_id`
- `startTimeUTC` -> internal `game_time`
- `awayTeam.commonName.default` / `homeTeam.commonName.default`
- `gameState` or fallback `gameScheduleState` -> internal `status`
- `gameType` / `gameTypeId` for regular-season filtering in backfill
- `season` / `seasonId` for season scoping in backfill

### Play-by-play fields currently consumed

From play-by-play payloads, current code uses:

- `plays[]`
- `typeDescKey == "goal"`
- `sortOrder` (first chronological goal)
- `details.scoringPlayerId`
- `periodDescriptor.number` (or fallback `period`) for first-period attribution

### Player game-log fields currently consumed

From player game logs, current code uses:

- `gameLog`/`games`/`playerGameLog` list variants
- `firstGoals`, `firstGoal`, or `isFirstGoal`
- `goals`, `shots`, `firstPeriodGoals`
- one of `firstPeriodShots` / `shotsFirstPeriod` / `period1Shots` / `shotsInFirstPeriod`

## How season/date filtering currently works

1. **Slate filtering by date (schedule provider):**
   - The provider requests one schedule date, then keeps games whose `startTimeUTC`, converted to **America/New_York**, equals `selected_date`.
   - This intentionally handles late UTC starts that still belong to the selected Eastern-day slate.

2. **Current-season derivation:**
   - `_season_from_date` maps dates to season keys using Sep-Aug season boundaries (e.g., March 2026 -> `20252026`).

3. **Backfill regular-season filter (existing):**
   - Requires all of:
     - completed game state (`FINAL` or `OFF`),
     - regular season game type (`gameType == 2`),
     - matching season key (`season == active season`).
   - This logic already excludes preseason (`gameType == 1`) and postseason (`gameType == 3`) for that specific routine.

## Historical season coverage from the current integration approach

### What is confirmed in-code

- The integration pattern itself is date/season-parameterized, not hardcoded to “today-only”.
- `schedule/{date}` can be called for arbitrary dates by construction.
- `player/{id}/game-log/{season}/{segment}` is season-addressable by key.
- Existing tests explicitly model and assert game types `1`, `2`, and `3` in schedule payload handling, confirming the app expects and can branch on those values.

### Practical coverage conclusion for next step

- With the current API approach, historical access should be treated as **season-iterable** via:
  - schedule by date (`/schedule/{date}`), and
  - game-level expansion via `/gamecenter/{gameId}/play-by-play`.
- Because environment network access was unavailable during this audit run, exact NHL API earliest-year boundary could not be verified live here.
- Therefore, the ingestion plan should include a lightweight **capability probe** job that detects first/last accessible seasons in your deployment environment before full backfill.

## Clean retrieval strategy for historical game-level data

### Required game types

- Include: **Regular season** (`gameType == 2`) and **Postseason** (`gameType == 3`)
- Exclude: **Preseason** (`gameType == 1`)

### Recommended filter function (shared)

Use one canonical helper for schedule rows:

- parse `gameType` from `gameType` or `gameTypeId` (int/string tolerant)
- include only `{2, 3}`
- ignore `1`
- optionally enforce completed states (`FINAL`, `OFF`) for finalized historical outcomes

## Concrete implementation plan (next prompts)

1. **Add shared NHL schedule game-type classifier**
   - Centralize parsing of `gameType`/`gameTypeId` into a single helper returning `int | None`.
   - Add `is_modeled_game_type(game)` that returns true only for types `2` and `3`.

2. **Add season coverage discovery utility (lightweight)**
   - New script/service that probes schedule dates across candidate season windows and records:
     - first season with any modeled game,
     - last season with data,
     - per-season counts by game type.
   - Persist a small JSON capability artifact for reproducibility.

3. **Historical game ingestion (schedule-first)**
   - Iterate season keys (e.g., `YYYYYYYY+1`) and scan dates from Sep 1 through Jun 30 (or until no active windows).
   - For each schedule day:
     - expand games from `gameWeek`/`games`,
     - keep only modeled types `{2,3}`,
     - drop preseason `1`,
     - record core game metadata.

4. **Outcome enrichment (play-by-play second pass)**
   - For retained game IDs, call `/gamecenter/{id}/play-by-play`.
   - Extract first-goal scorer, first-period goal scorers, and any additional modeling-needed per-game outcomes.

5. **Normalization/storage design for modeling inputs**
   - Create a canonical `games` table/CSV/Parquet partitioned by season, keyed by `(season, game_id)`.
   - Suggested normalized columns:
     - identifiers: `season`, `game_id`, `game_type`, `game_date_local`, `start_time_utc`
     - teams: `home_team_name`, `away_team_name`, optional IDs/abbrevs when present
     - status/result: `game_state`, `is_final`
     - derived targets: `first_goal_scorer_id`, `first_period_goal_scorer_ids`
     - lineage: `source_endpoint`, `ingested_at_utc`
   - Keep raw payload snapshots in season-partitioned storage for reprocessing/debug.

6. **Quality controls**
   - Deduplicate by `(season, game_id)`.
   - Validate no preseason rows enter modeled dataset.
   - Report season-level counts: total, regular-season, postseason, preseason-excluded.

## Why this is the cleanest path

- Reuses existing production NHL API endpoints and parsing patterns already in code.
- Requires minimal architectural change: mostly shared filters + seasonal iterators.
- Supports both regular season and postseason while explicitly excluding preseason.
