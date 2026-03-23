from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class SeasonWeights:
    last_season: float = 0.7
    current_season: float = 1.0


@dataclass(slots=True)
class RollingWindowConfig:
    team_games: int = 15
    player_games: int = 20
    team_recent_weight: float = 0.35
    player_recent_weight: float = 0.4


@dataclass(slots=True)
class MinimumSampleConfig:
    team_games: int = 12
    player_games: int = 8
    team_first_goals: int = 4


@dataclass(slots=True)
class ShrinkageConfig:
    team_prior_strength: float = 20.0
    player_prior_strength: float = 12.0


@dataclass(slots=True)
class HomeAwayAdjustments:
    enabled: bool = True
    home_ice_advantage: float = 0.12


@dataclass(slots=True)
class FeatureToggles:
    use_projected_lineup: bool = True
    use_toi_projection: bool = True


@dataclass(slots=True)
class FirstGoalModelConfig:
    season_weights: SeasonWeights = field(default_factory=SeasonWeights)
    rolling_windows: RollingWindowConfig = field(default_factory=RollingWindowConfig)
    minimum_samples: MinimumSampleConfig = field(default_factory=MinimumSampleConfig)
    shrinkage: ShrinkageConfig = field(default_factory=ShrinkageConfig)
    home_away: HomeAwayAdjustments = field(default_factory=HomeAwayAdjustments)
    feature_toggles: FeatureToggles = field(default_factory=FeatureToggles)

    @classmethod
    def from_dict(cls, payload: dict) -> "FirstGoalModelConfig":
        return cls(
            season_weights=SeasonWeights(**payload.get("season_weights", {})),
            rolling_windows=RollingWindowConfig(**payload.get("rolling_windows", {})),
            minimum_samples=MinimumSampleConfig(**payload.get("minimum_samples", {})),
            shrinkage=ShrinkageConfig(**payload.get("shrinkage", {})),
            home_away=HomeAwayAdjustments(**payload.get("home_away", {})),
            feature_toggles=FeatureToggles(**payload.get("feature_toggles", {})),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "FirstGoalModelConfig":
        with Path(path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls.from_dict(payload)
