from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.identity import name_aliases, team_alias_tokens
from app.services.interfaces import (
    PlayerHistoricalProduction,
    PlayerProjectionCandidate,
    PlayerRosterEligibility,
    ProjectionProvider,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlayerFirstGoalProjectionRow:
    projection_date: date
    game_id: str
    nhl_player_id: str
    player_name: str
    projected_team_name: str
    active_team_name: str
    is_active_roster: bool
    historical_production: PlayerHistoricalProduction
    model_probability: float


class ProjectionStoreValidationError(ValueError):
    """Raised when a projection store payload is malformed."""


class PlayerFirstGoalProjectionStore:
    """Interface for loading daily first-goal projection rows from a structured store."""

    def load_for_date(self, selected_date: date) -> list[PlayerFirstGoalProjectionRow]:
        raise NotImplementedError


class JsonArtifactProjectionStore(PlayerFirstGoalProjectionStore):
    """Read projection rows from a JSON artifact persisted by model pipelines."""

    def __init__(self, artifact_path: str | Path) -> None:
        self._artifact_path = Path(artifact_path)

    def load_for_date(self, selected_date: date) -> list[PlayerFirstGoalProjectionRow]:
        if not self._artifact_path.exists():
            return []

        with self._artifact_path.open("r", encoding="utf-8") as infile:
            payload = json.load(infile)

        return _parse_projection_payload(payload=payload, selected_date=selected_date)


class StoreBackedProjectionProvider(ProjectionProvider):
    """Projection provider that adapts a structured projection store to the provider interface."""

    def __init__(self, store: PlayerFirstGoalProjectionStore) -> None:
        self._store = store

    def fetch_player_first_goal_projections(self, selected_date: date) -> list[PlayerProjectionCandidate]:
        try:
            rows = self._store.load_for_date(selected_date)
        except ProjectionStoreValidationError as exc:
            logger.warning(
                "Projection artifact validation failed; treating date as unavailable",
                extra={"selected_date": selected_date.isoformat(), "error": str(exc)},
            )
            return []
        return [
            PlayerProjectionCandidate(
                game_id=row.game_id,
                nhl_player_id=row.nhl_player_id,
                player_name=row.player_name,
                projected_team_name=row.projected_team_name,
                model_probability=row.model_probability,
                historical_production=row.historical_production,
                roster_eligibility=PlayerRosterEligibility(
                    active_team_name=row.active_team_name,
                    is_active_roster=row.is_active_roster,
                ),
            )
            for row in rows
        ]


_PROJECTED_ROOT = Path(__file__).resolve().parents[1] / "data" / "projections"
_ROSTER_ARTIFACT = Path(__file__).resolve().parents[1] / "data" / "rosters" / "current_active_rosters.json"


@dataclass(frozen=True)
class ProjectionArtifactDataSource:
    """Structured projection artifact path resolution independent of route logic."""

    artifact_path: Path

    @staticmethod
    def real_from_env() -> "ProjectionArtifactDataSource":
        raw_path = os.getenv("BACKEND_PROJECTION_ARTIFACT_PATH")
        if isinstance(raw_path, str) and raw_path.strip():
            return ProjectionArtifactDataSource(artifact_path=Path(raw_path.strip()))
        return ProjectionArtifactDataSource(artifact_path=_PROJECTED_ROOT / "player_first_goal_projections.json")

    @staticmethod
    def mock_default() -> "ProjectionArtifactDataSource":
        return ProjectionArtifactDataSource(artifact_path=_PROJECTED_ROOT / "mock_player_first_goal_projections.json")


def build_real_projection_provider_from_env() -> StoreBackedProjectionProvider:
    projection_source = build_real_projection_data_source_from_env()
    return StoreBackedProjectionProvider(store=JsonArtifactProjectionStore(artifact_path=projection_source.artifact_path))


def build_mock_projection_provider() -> StoreBackedProjectionProvider:
    projection_source = ProjectionArtifactDataSource.mock_default()
    return StoreBackedProjectionProvider(store=JsonArtifactProjectionStore(artifact_path=projection_source.artifact_path))


def build_real_projection_data_source_from_env() -> ProjectionArtifactDataSource:
    return ProjectionArtifactDataSource.real_from_env()


def _parse_projection_payload(payload: dict[str, Any], selected_date: date) -> list[PlayerFirstGoalProjectionRow]:
    projections = payload.get("projections")
    if not isinstance(projections, list):
        raise ProjectionStoreValidationError("Projection artifact must contain a list field named 'projections'.")

    validated_rows: list[PlayerFirstGoalProjectionRow] = []
    seen_keys: set[tuple[date, str, str]] = set()

    for idx, raw_row in enumerate(projections):
        if not isinstance(raw_row, dict):
            raise ProjectionStoreValidationError(f"Projection row at index {idx} must be an object.")

        row = _parse_projection_row(raw_row=raw_row, idx=idx)
        dedupe_key = (row.projection_date, row.game_id, row.nhl_player_id)
        if dedupe_key in seen_keys:
            raise ProjectionStoreValidationError(
                "Duplicate projection row for key "
                f"(date={row.projection_date.isoformat()}, game_id={row.game_id}, player_id={row.nhl_player_id})."
            )
        seen_keys.add(dedupe_key)

        if row.projection_date == selected_date:
            validated_rows.append(row)

    return validated_rows


def _parse_projection_row(raw_row: dict[str, Any], idx: int) -> PlayerFirstGoalProjectionRow:
    projection_date_raw = raw_row.get("date")
    game_id_raw = raw_row.get("game_id")
    nhl_player_id_raw = raw_row.get("nhl_player_id")
    player_id_raw = raw_row.get("player_id")
    player_name_raw = raw_row.get("player_name")
    team_name_raw = raw_row.get("team_name")
    if team_name_raw is None:
        team_name_raw = raw_row.get("team")
    active_team_name_raw = raw_row.get("active_team_name")
    is_active_roster_raw = raw_row.get("is_active_roster", True)
    season_first_goals_raw = _coalesce(
        raw_row.get("historical_season_first_goals"),
        raw_row.get("season_first_goals"),
        raw_row.get("first_goals_this_year"),
    )
    season_games_played_raw = raw_row.get("historical_season_games_played")
    season_total_goals_raw = _coalesce(
        raw_row.get("historical_season_total_goals"),
        raw_row.get("season_total_goals"),
        raw_row.get("goals_this_year"),
    )
    probability_raw = raw_row.get("model_probability")
    if probability_raw is None:
        probability_raw = raw_row.get("probability")

    if not isinstance(projection_date_raw, str):
        raise ProjectionStoreValidationError(f"Projection row at index {idx} has an invalid or missing 'date'.")

    try:
        projection_date = date.fromisoformat(projection_date_raw)
    except ValueError as exc:
        raise ProjectionStoreValidationError(
            f"Projection row at index {idx} contains an invalid ISO date '{projection_date_raw}'."
        ) from exc

    if not isinstance(game_id_raw, str) or not game_id_raw.strip():
        raise ProjectionStoreValidationError(f"Projection row at index {idx} has a missing or empty 'game_id'.")

    canonical_player_id = nhl_player_id_raw if isinstance(nhl_player_id_raw, str) and nhl_player_id_raw.strip() else player_id_raw
    if not isinstance(canonical_player_id, str) or not canonical_player_id.strip():
        raise ProjectionStoreValidationError(f"Projection row at index {idx} has a missing or empty 'player_id'.")

    if not isinstance(player_name_raw, str) or not player_name_raw.strip():
        raise ProjectionStoreValidationError(f"Projection row at index {idx} has a missing or empty 'player_name'.")

    if not isinstance(team_name_raw, str) or not team_name_raw.strip():
        raise ProjectionStoreValidationError(f"Projection row at index {idx} has a missing or empty 'team_name'.")
    if active_team_name_raw is None:
        active_team_name_raw = team_name_raw
    if not isinstance(active_team_name_raw, str) or not active_team_name_raw.strip():
        raise ProjectionStoreValidationError(f"Projection row at index {idx} has a missing or empty 'active_team_name'.")
    if not isinstance(is_active_roster_raw, bool):
        raise ProjectionStoreValidationError(f"Projection row at index {idx} has a non-boolean 'is_active_roster'.")

    if not isinstance(probability_raw, (int, float)):
        raise ProjectionStoreValidationError(f"Projection row at index {idx} has a non-numeric 'model_probability'.")

    probability = float(probability_raw)
    if probability <= 0 or probability >= 1:
        raise ProjectionStoreValidationError(
            f"Projection row at index {idx} has an invalid 'model_probability' ({probability}); expected 0 < p < 1."
        )

    season_first_goals: float | None = None
    if season_first_goals_raw is not None:
        if not isinstance(season_first_goals_raw, (int, float)):
            raise ProjectionStoreValidationError(
                f"Projection row at index {idx} has a non-numeric 'historical_season_first_goals'."
            )
        season_first_goals = float(season_first_goals_raw)

    season_games_played: float | None = None
    if season_games_played_raw is not None:
        if not isinstance(season_games_played_raw, (int, float)):
            raise ProjectionStoreValidationError(
                f"Projection row at index {idx} has a non-numeric 'historical_season_games_played'."
            )
        season_games_played = float(season_games_played_raw)

    canonical_player_id_value = canonical_player_id.strip()
    if not canonical_player_id_value.isdigit():
        resolved_player_id = _resolve_nhl_player_id_from_roster(
            player_name=player_name_raw.strip(),
            team_name=active_team_name_raw.strip() if isinstance(active_team_name_raw, str) else team_name_raw.strip(),
        )
        if resolved_player_id is not None:
            canonical_player_id_value = resolved_player_id

    season_total_goals: float | None = None
    if season_total_goals_raw is not None:
        if not isinstance(season_total_goals_raw, (int, float)):
            raise ProjectionStoreValidationError(
                f"Projection row at index {idx} has a non-numeric season total goals field."
            )
        season_total_goals = float(season_total_goals_raw)

    return PlayerFirstGoalProjectionRow(
        projection_date=projection_date,
        game_id=game_id_raw.strip(),
        nhl_player_id=canonical_player_id_value,
        player_name=player_name_raw.strip(),
        projected_team_name=team_name_raw.strip(),
        active_team_name=active_team_name_raw.strip(),
        is_active_roster=is_active_roster_raw,
        historical_production=PlayerHistoricalProduction(
            season_first_goals=season_first_goals,
            season_games_played=season_games_played,
            season_total_goals=season_total_goals,
        ),
        model_probability=probability,
    )


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


@lru_cache(maxsize=1)
def _load_roster_player_ids() -> dict[tuple[str, str], str]:
    if not _ROSTER_ARTIFACT.exists():
        return {}
    with _ROSTER_ARTIFACT.open("r", encoding="utf-8") as infile:
        payload = json.load(infile)
    if isinstance(payload, dict):
        payload = payload.get("players")
    if not isinstance(payload, list):
        return {}

    mapping: dict[tuple[str, str], str] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        player_name = row.get("player_name")
        player_id = row.get("player_id")
        active_team_name = row.get("active_team_name")
        if not isinstance(player_name, str) or not player_name.strip():
            continue
        if not isinstance(player_id, str) or not player_id.strip() or not player_id.strip().isdigit():
            continue
        if not isinstance(active_team_name, str) or not active_team_name.strip():
            continue
        for name_alias in name_aliases(player_name):
            for team_alias in team_alias_tokens(active_team_name):
                mapping[(name_alias, team_alias)] = player_id.strip()

    return mapping


def _resolve_nhl_player_id_from_roster(player_name: str, team_name: str) -> str | None:
    roster_map = _load_roster_player_ids()
    if not roster_map:
        return None
    for name_alias in name_aliases(player_name):
        for team_alias in team_alias_tokens(team_name):
            mapped = roster_map.get((name_alias, team_alias))
            if mapped is not None:
                return mapped
    return None
