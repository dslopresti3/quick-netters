"""Modeling package scaffold for Quick Netters."""

from quick_netters_modeling.first_goal import (
    FirstGoalModelConfig,
    FirstGoalProbabilityPipeline,
    PlayerFirstGoalPrediction,
)
from quick_netters_modeling.historical import HistoricalDataPipeline, SeasonConfig
from quick_netters_modeling.interfaces import FeaturePipeline, ModelArtifact, Prediction

__all__ = [
    "FeaturePipeline",
    "ModelArtifact",
    "Prediction",
    "HistoricalDataPipeline",
    "SeasonConfig",
    "FirstGoalModelConfig",
    "FirstGoalProbabilityPipeline",
    "PlayerFirstGoalPrediction",
]
