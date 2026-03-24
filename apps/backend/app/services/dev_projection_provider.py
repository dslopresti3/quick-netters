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
class ActiveRosterPlayer:
    player_id: str
    player_name: str
    active_team_name: str
    is_active_roster: bool
    historical_season_first_goals: float | None = None
    historical_season_games_played: float | None = None


class ActiveRosterRepository:
    """Loads canonical player identities and active-team eligibility from a roster artifact."""

    def __init__(self, roster_path: Path) -> None:
        self._roster_path = roster_path
        self._cached: dict[str, list[ActiveRosterPlayer]] | None = None

    def active_players_for_team(self, team_name: str) -> list[ActiveRosterPlayer]:
        rosters = self._load()
        players = rosters.get(team_name.strip().lower(), [])
        return [player for player in players if player.is_active_roster]

    def _load(self) -> dict[str, list[ActiveRosterPlayer]]:
        if self._cached is not None:
            return self._cached

        if not self._roster_path.exists():
            logger.warning("Active roster artifact not found", extra={"path": str(self._roster_path)})
            self._cached = {}
            return self._cached

        payload = json.loads(self._roster_path.read_text(encoding="utf-8"))
        raw_players = payload.get("players", [])
        loaded: dict[str, list[ActiveRosterPlayer]] = {}
        if not isinstance(raw_players, list):
            self._cached = {}
            return self._cached

        for raw in raw_players:
            if not isinstance(raw, dict):
                continue
            player_id = str(raw.get("player_id", "")).strip()
            player_name = str(raw.get("player_name", "")).strip()
            active_team_name = str(raw.get("active_team_name", "")).strip()
            if not player_id or not player_name or not active_team_name:
                continue
            is_active_roster = bool(raw.get("is_active_roster", True))
            player = ActiveRosterPlayer(
                player_id=player_id,
                player_name=player_name,
                active_team_name=active_team_name,
                is_active_roster=is_active_roster,
                historical_season_first_goals=_as_float(raw.get("historical_season_first_goals")),
                historical_season_games_played=_as_float(raw.get("historical_season_games_played")),
            )
            loaded.setdefault(active_team_name.lower(), []).append(player)

        self._cached = loaded
        return loaded


@dataclass(frozen=True)
class _ProjectionTemplate:
    base_probability: float
    decrement_per_rank: float


_DEFAULT_TEMPLATE = _ProjectionTemplate(base_probability=0.17, decrement_per_rank=0.025)


class AutoGeneratingProjectionProvider(ProjectionProvider):
    """Use stored projections when available; otherwise generate real-player rows from active rosters.

    Placeholder development generator can be enabled explicitly via `enable_dev_fallback`.
    """

    def __init__(
        self,
        base_provider: ProjectionProvider,
        schedule_provider: ScheduleProvider,
        artifact_path: Path,
        roster_repository: ActiveRosterRepository,
        *,
        enable_dev_fallback: bool = False,
    ) -> None:
        self._base_provider = base_provider
        self._schedule_provider = schedule_provider
        self._artifact_path = artifact_path
        self._roster_repository = roster_repository
        self._enable_dev_fallback = enable_dev_fallback

    def fetch_player_first_goal_projections(self, selected_date: date) -> list[PlayerProjectionCandidate]:
        existing = self._base_provider.fetch_player_first_goal_projections(selected_date)
        if existing and not _contains_dev_placeholder_rows(existing):
            return existing

        scheduled_games = self._schedule_provider.fetch(selected_date)
        if not scheduled_games:
            return existing if existing else []

        generated = _generate_candidates_from_active_rosters(
            scheduled_games=scheduled_games,
            roster_repository=self._roster_repository,
        )

        if generated:
            _upsert_generated_rows(artifact_path=self._artifact_path, selected_date=selected_date, rows=generated)
            return generated

        if existing:
            logger.warning(
                "Retaining existing projections because active-roster generation yielded no rows",
                extra={"selected_date": selected_date.isoformat(), "artifact_path": str(self._artifact_path)},
            )
            return existing

        if self._enable_dev_fallback:
            generated = _generate_placeholder_candidates(scheduled_games=scheduled_games)
            _upsert_generated_rows(artifact_path=self._artifact_path, selected_date=selected_date, rows=generated)
            return generated

        return []


def _contains_dev_placeholder_rows(rows: list[PlayerProjectionCandidate]) -> bool:
    return any(row.nhl_player_id.startswith("dev-") or " skater " in row.player_name.lower() for row in rows)


def _generate_candidates_from_active_rosters(
    scheduled_games: list[GameSummary],
    roster_repository: ActiveRosterRepository,
) -> list[PlayerProjectionCandidate]:
    rows: list[PlayerProjectionCandidate] = []
    for game in scheduled_games:
        rows.extend(_project_team_candidates(game_id=game.game_id, team_name=game.away_team, roster_repository=roster_repository))
        rows.extend(_project_team_candidates(game_id=game.game_id, team_name=game.home_team, roster_repository=roster_repository))
    return rows


def _project_team_candidates(
    game_id: str,
    team_name: str,
    roster_repository: ActiveRosterRepository,
    template: _ProjectionTemplate = _DEFAULT_TEMPLATE,
) -> list[PlayerProjectionCandidate]:
    players = roster_repository.active_players_for_team(team_name)
    ranked = sorted(
        players,
        key=lambda p: (
            p.historical_season_first_goals or 0.0,
            (p.historical_season_first_goals or 0.0) / max((p.historical_season_games_played or 82.0), 1.0),
            p.player_name,
        ),
        reverse=True,
    )

    rows: list[PlayerProjectionCandidate] = []
    for idx, player in enumerate(ranked):
        probability = max(template.base_probability - (idx * template.decrement_per_rank), 0.01)
        rows.append(
            PlayerProjectionCandidate(
                game_id=game_id,
                nhl_player_id=player.player_id,
                player_name=player.player_name,
                projected_team_name=team_name,
                model_probability=round(probability, 4),
                historical_production=PlayerHistoricalProduction(
                    season_first_goals=player.historical_season_first_goals,
                    season_games_played=player.historical_season_games_played,
                ),
                roster_eligibility=PlayerRosterEligibility(
                    active_team_name=player.active_team_name,
                    is_active_roster=player.is_active_roster,
                ),
            )
        )

    return rows


def _generate_placeholder_candidates(scheduled_games: list[GameSummary]) -> list[PlayerProjectionCandidate]:
    rows: list[PlayerProjectionCandidate] = []
    for game in scheduled_games:
        for team_name, side in ((game.away_team, "away"), (game.home_team, "home")):
            team_slug = _slug(team_name)
            for index, probability in enumerate((0.16, 0.12, 0.09), start=1):
                rows.append(
                    PlayerProjectionCandidate(
                        game_id=game.game_id,
                        nhl_player_id=f"dev-{game.game_id}-{side}-{team_slug}-{index}",
                        player_name=f"{team_name} Skater {chr(ord('A') + index - 1)}",
                        projected_team_name=team_name,
                        model_probability=probability,
                        historical_production=PlayerHistoricalProduction(
                            season_first_goals=float(2 + index),
                            season_games_played=float(60 + index),
                        ),
                        roster_eligibility=PlayerRosterEligibility(active_team_name=team_name, is_active_roster=True),
                    )
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
        key=lambda row: (str(row.get("date", "")), str(row.get("game_id", "")), str(row.get("player_id", ""))),
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
                "player_id": row.nhl_player_id,
                "nhl_player_id": row.nhl_player_id,
                "player_name": row.player_name,
                "team_name": row.projected_team_name,
                "active_team_name": row.roster_eligibility.active_team_name,
                "is_active_roster": row.roster_eligibility.is_active_roster,
                "historical_season_first_goals": row.historical_production.season_first_goals,
                "historical_season_games_played": row.historical_production.season_games_played,
                "probability": row.model_probability,
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


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None
