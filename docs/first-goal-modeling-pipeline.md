# First-Goal Modeling Pipeline (NHL, v1)

This pipeline estimates player first-goal probabilities in two layers:

1. `P(team scores first)`
2. `P(player scores first for team | team scores first)`

Final output per player:

`P(player scores first) = P(team scores first) * P(player | team first)`

## Implementation

Code location: `packages/modeling/src/quick_netters_modeling/first_goal/`

- `config.py`: config dataclasses + JSON loader
- `schemas.py`: typed input/output contracts
- `pipeline.py`: stable v1 estimators (empirical rates + config-driven blending/shrinkage)
- `io.py`: CSV/JSON output writers

Default config: `packages/modeling/config/first_goal_model_config.json`

## v1 behavior (config-driven)

- **Seasons**: supports last season + current season by weighting each row via `season_weights`.
  - `season_weights.last_season` and `season_weights.current_season` control base contribution.
  - Early in season, date-aware ramping adjusts these base values using:
    - `season_weights.early_season_last_season_multiplier`
    - `season_weights.early_season_current_season_multiplier`
    - `season_weights.in_season_ramp_games`
- **Team layer**:
  - long-window weighted rate,
  - recent-window weighted rate,
  - blend via `rolling_windows.team_recent_weight`,
  - shrink toward league baseline via `shrinkage.team_prior_strength`,
  - optional home/away adjustment.
- **Player layer**:
  - long/recent weighted player first-goal counts,
  - team and player minimum-sample guards,
  - regression of player current-season rate toward prior-season baseline when sample is limited (`shrinkage.player_current_baseline_games`),
  - shrink toward lineup prior via `shrinkage.player_prior_strength`,
  - TOI-based prior when enabled, otherwise uniform lineup prior.

## Outputs

Predictions are emitted per scheduled game/player and include:

- team first-goal probability,
- player conditional share,
- final player first-goal probability.

In backend recommendation payloads, this final player probability is exposed as `model_probability`.
The backend service layer then combines `model_probability` with market odds to compute `implied_probability`, `edge`, `ev`, and final recommendation buckets.
