# First-goal modeling pipeline (NHL)

This pipeline estimates first-goal scorer probabilities in two interpretable layers:

1. **Team layer**: `P(team scores first)`
2. **Player layer**: `P(player scores first for team | team scores first)`

Final score:

`P(player scores first) = P(team scores first) * P(player scores first | team scores first)`

## Implementation

Code lives in `packages/modeling/src/quick_netters_modeling/first_goal/`.

- `config.py`: model settings dataclasses + JSON loader.
- `schemas.py`: typed inputs and outputs.
- `pipeline.py`: estimation logic with season weighting, rolling windows, shrinkage, and optional lineup/TOI adjustments.
- `io.py`: CSV/JSON prediction writers.

A default config template is included at `packages/modeling/config/first_goal_model_config.json`.

## Inputs

The pipeline expects:

- historical `TeamGameSample` rows covering last season + current season,
- historical `PlayerGameSample` rows covering last season + current season,
- `ScheduledGame` rows to score,
- `ScheduledLineupPlayer` rows to constrain/weight players.

## Design choices

- **Interpretable and stable**: empirical rates with explicit shrinkage and recency blending.
- **Configurable season weighting** for last/current season balance.
- **Configurable small-sample behavior** via minimum thresholds and prior strengths.
- **Modular**: each layer can be replaced later (e.g., logistic regression or Bayesian hierarchy) without changing output contracts.
