# First-goal modeling pipeline (NHL, v1)

This pipeline estimates first-goal scorer probabilities in two layers:

1. `P(team scores first)`
2. `P(player scores first for team | team scores first)`

Final output per player:

`P(player scores first) = P(team scores first) * P(player | team first)`

## Implementation

Code location: `packages/modeling/src/quick_netters_modeling/first_goal/`

- `config.py`: config dataclasses + JSON loader.
- `schemas.py`: typed input/output contracts.
- `pipeline.py`: stable v1 estimators (empirical rates + config-driven blending/shrinkage).
- `io.py`: CSV/JSON output writers.

Default config: `packages/modeling/config/first_goal_model_config.json`

## v1 behavior (config-driven)

- **Seasons**: supports last season + current season by weighting each row via `season_weights`.
  - `season_weights.last_season` and `season_weights.current_season` control base contribution.
  - Early in the season, date-aware ramping adjusts these base values using:
    - `season_weights.early_season_last_season_multiplier`
    - `season_weights.early_season_current_season_multiplier`
    - `season_weights.in_season_ramp_games`
  - Tuning guidance:
    - Increase `early_season_last_season_multiplier` to lean more on prior season signal in October/November.
    - Decrease `early_season_current_season_multiplier` to reduce noisy current-season impact early.
    - Lower `in_season_ramp_games` to trust current-season results sooner.
- **Team layer**:
  - long-window weighted rate,
  - recent-window weighted rate,
  - blend by `rolling_windows.team_recent_weight`,
  - shrink toward league baseline with `shrinkage.team_prior_strength`,
  - optional home/away adjustment.
- **Player layer**:
  - long/recent weighted player first-goal counts (per player rolling form),
  - team and player minimum-sample guards,
  - regression of player current-season rate toward prior-season baseline when current-season samples are limited (`shrinkage.player_current_baseline_games`),
  - shrink toward lineup prior using `shrinkage.player_prior_strength`,
  - prior is TOI-based when enabled, otherwise uniform lineup prior.

- **Rolling form features**:
  - Team rolling form: `rolling_windows.team_games` + `rolling_windows.team_recent_weight`.
  - Player rolling form: `rolling_windows.player_games` + `rolling_windows.player_recent_weight`.

## Outputs

Predictions are structured per scheduled game and player, including:

- team first-goal probability,
- player conditional share,
- final player first-goal probability.

This keeps the implementation interpretable and stable while leaving clear extension points for future model upgrades.
