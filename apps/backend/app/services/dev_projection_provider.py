from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.api.schemas import GameSummary
from app.services.interfaces import (
    PlayerHistoricalProduction,
    PlayerProjectionCandidate,
    PlayerRosterEligibility,
    ProjectionProvider,
    ScheduleProvider,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ProjectionTemplate:
    suffix: str
    probability: float


_AWAY_TEMPLATES: tuple[_ProjectionTemplate, ...] = (
    _ProjectionTemplate(suffix="Skater A", probability=0.16),
    _ProjectionTemplate(suffix="Skater B", probability=0.12),
    _ProjectionTemplate(suffix="Skater C", probability=0.09),
)

_HOME_TEMPLATES: tuple[_ProjectionTemplate, ...] = (
    _ProjectionTemplate(suffix="Skater A", probability=0.15),
    _ProjectionTemplate(suffix="Skater B", probability=0.11),
    _ProjectionTemplate(suffix="Skater C", probability=0.08),
)


class AutoGeneratingProjectionProvider(ProjectionProvider):
    """Use stored projections when available; generate deterministic development rows for missing dates."""

    def __init__(self, base_provider: ProjectionProvider, schedule_provider: ScheduleProvider, artifact_path: Path) -> None:
        self._base_provider = base_provider
        self._schedule_provider = schedule_provider
        self._artifact_path = artifact_path

    def fetch_player_first_goal_projections(self, selected_date: date) -> list[PlayerProjectionCandidate]:
        existing = self._base_provider.fetch_player_first_goal_projections(selected_date)
        if existing:
            return existing

        scheduled_games = self._schedule_provider.fetch(selected_date)
        if not scheduled_games:
            return []

        generated = _generate_candidates(selected_date=selected_date, scheduled_games=scheduled_games)
        _upsert_generated_rows(artifact_path=self._artifact_path, selected_date=selected_date, rows=generated)
        return generated


def _generate_candidates(selected_date: date, scheduled_games: list[GameSummary]) -> list[PlayerProjectionCandidate]:
    rows: list[PlayerProjectionCandidate] = []
    for game in scheduled_games:
        for team_name, side, templates in (
            (game.away_team, "away", _AWAY_TEMPLATES),
            (game.home_team, "home", _HOME_TEMPLATES),
        ):
            team_slug = _slug(team_name)
            for index, template in enumerate(templates, start=1):
                rows.append(
                    PlayerProjectionCandidate(
                        game_id=game.game_id,
                        nhl_player_id=f"dev-{game.game_id}-{side}-{team_slug}-{index}",
                        player_name=f"{team_name} {template.suffix}",
                        projected_team_name=team_name,
                        model_probability=template.probability,
                        historical_production=PlayerHistoricalProduction(
                            season_first_goals=float(2 + index),
                            season_games_played=float(60 + index),
                        ),
                        roster_eligibility=PlayerRosterEligibility(active_team_name=team_name, is_active_roster=True),
                    )
                )
    logger.info(
        "Generated development projection rows for missing date",
        extra={"selected_date": selected_date.isoformat(), "generated_rows_count": len(rows)},
    )
    return rows


def _upsert_generated_rows(artifact_path: Path, selected_date: date, rows: list[PlayerProjectionCandidate]) -> None:
    if not rows:
        return

    payload = _load_artifact(artifact_path)
    existing = payload.get("projections")
    if not isinstance(existing, list):
        logger.warning("Projection artifact malformed; skipping generated projection persistence", extra={"path": str(artifact_path)})
        return

    target_date_iso = selected_date.isoformat()
    retained = [row for row in existing if isinstance(row, dict) and row.get("date") != target_date_iso]
    retained.extend(_as_serializable_rows(selected_date=selected_date, rows=rows))
    payload["schema_version"] = 1
    payload["projections"] = sorted(
        retained,
        key=lambda row: (str(row.get("date", "")), str(row.get("game_id", "")), str(row.get("nhl_player_id", ""))),
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _as_serializable_rows(selected_date: date, rows: list[PlayerProjectionCandidate]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for row in rows:
        serialized.append(
            {
                "date": selected_date.isoformat(),
                "game_id": row.game_id,
                "nhl_player_id": row.nhl_player_id,
                "player_name": row.player_name,
                "team_name": row.projected_team_name,
                "active_team_name": row.roster_eligibility.active_team_name,
                "is_active_roster": row.roster_eligibility.is_active_roster,
                "historical_season_first_goals": row.historical_production.season_first_goals,
                "historical_season_games_played": row.historical_production.season_games_played,
                "model_probability": row.model_probability,
            }
        )
    return serialized


def _load_artifact(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "projections": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _slug(value: str) -> str:
    lowered = value.lower().strip()
    chars = [ch if ch.isalnum() else "-" for ch in lowered]
    squashed = "".join(chars)
    while "--" in squashed:
        squashed = squashed.replace("--", "-")
    return squashed.strip("-") or "unknown"
