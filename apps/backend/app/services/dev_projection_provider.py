from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Protocol

from app.api.schemas import GameSummary
from app.services.nhl_api_data import fetch_player_first_goal_history, fetch_team_roster_current, team_abbrev_for_name
from app.services.interfaces import (
    PlayerHistoricalProduction,
    PlayerProjectionCandidate,
    PlayerRosterEligibility,
    ProjectionProvider,
    ScheduleProvider,
)

logger = logging.getLogger(__name__)

HistoryLoader = Callable[[date, set[str], Path], dict[str, PlayerHistoricalProduction]]


class ActiveRosterSource(Protocol):
    def active_players_for_team(self, team_name: str) -> list[ActiveRosterPlayer]:
        ...


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


class NhlApiActiveRosterRepository:
    """Loads active roster directly from NHL API roster endpoint."""

    def __init__(self) -> None:
        self._cache_by_team_name: dict[str, list[ActiveRosterPlayer]] = {}

    def active_players_for_team(self, team_name: str) -> list[ActiveRosterPlayer]:
        team_key = team_name.strip().lower()
        cached = self._cache_by_team_name.get(team_key)
        if cached is not None:
            return [player for player in cached]

        team_abbrev = team_abbrev_for_name(team_name)
        if team_abbrev is None:
            logger.warning("No NHL team abbreviation mapping found", extra={"team_name": team_name})
            return []

        roster_players = fetch_team_roster_current(team_abbrev=team_abbrev)
        rows: list[ActiveRosterPlayer] = []
        for player in roster_players:
            rows.append(
                ActiveRosterPlayer(
                    player_id=player.player_id,
                    player_name=player.player_name,
                    active_team_name=team_name,
                    is_active_roster=True,
                )
            )
        self._cache_by_team_name[team_key] = [player for player in rows]
        return rows


@dataclass(frozen=True)
class _ProjectionTemplate:
    base_probability: float
    decrement_per_rank: float


_DEFAULT_TEMPLATE = _ProjectionTemplate(base_probability=0.17, decrement_per_rank=0.025)


class AutoGeneratingProjectionProvider(ProjectionProvider):
    """Strict real-mode projection pipeline sourced from schedule -> rosters -> player history."""

    def __init__(
        self,
        schedule_provider: ScheduleProvider,
        artifact_path: Path,
        roster_repository: ActiveRosterSource,
        *,
        enable_dev_fallback: bool = False,
        history_loader: HistoryLoader | None = None,
    ) -> None:
        self._schedule_provider = schedule_provider
        self._artifact_path = artifact_path
        self._roster_repository = roster_repository
        self._enable_dev_fallback = enable_dev_fallback
        self._history_loader = history_loader or _load_player_first_goal_history_from_artifact
        self._generated_cache_by_date: dict[date, list[PlayerProjectionCandidate]] = {}

    def fetch_player_first_goal_projections(self, selected_date: date) -> list[PlayerProjectionCandidate]:
        cached_generated = self._generated_cache_by_date.get(selected_date)
        if cached_generated is not None:
            logger.info(
                "games projection cache hit",
                extra={
                    "selected_date": selected_date.isoformat(),
                    "projection_count": len(cached_generated),
                    "projection_cache_source": "memory",
                },
            )
            return [row for row in cached_generated]

        cached_artifact_rows = _load_projection_rows_for_date_from_artifact(self._artifact_path, selected_date)
        if cached_artifact_rows:
            logger.info(
                "games projection cache hit",
                extra={
                    "selected_date": selected_date.isoformat(),
                    "projection_count": len(cached_artifact_rows),
                    "projection_cache_source": "artifact",
                },
            )
            self._generated_cache_by_date[selected_date] = [row for row in cached_artifact_rows]
            return cached_artifact_rows

        scheduled_games = self._schedule_provider.fetch(selected_date)
        if not scheduled_games:
            return []

        active_rosters_started = perf_counter()
        eligible_player_pool = _build_eligible_player_pool(
            scheduled_games=scheduled_games,
            roster_repository=self._roster_repository,
            selected_date=selected_date,
        )
        active_rosters_elapsed_ms = round((perf_counter() - active_rosters_started) * 1000, 2)
        logger.info(
            "games active roster fetches timing",
            extra={
                "selected_date": selected_date.isoformat(),
                "active_roster_fetches_elapsed_ms": active_rosters_elapsed_ms,
                "eligible_player_pool_count": len(eligible_player_pool),
            },
        )
        logger.info(
            "games player first-goal history fetch start",
            extra={
                "selected_date": selected_date.isoformat(),
                "eligible_player_count": len({candidate.player.player_id for candidate in eligible_player_pool}),
            },
        )
        history_started = perf_counter()
        player_history = self._history_loader(
            selected_date,
            {candidate.player.player_id for candidate in eligible_player_pool},
            self._artifact_path,
        )
        history_elapsed_ms = round((perf_counter() - history_started) * 1000, 2)
        logger.info(
            "games player first-goal history fetch end",
            extra={
                "selected_date": selected_date.isoformat(),
                "history_player_count": len(player_history),
                "player_history_load_elapsed_ms": history_elapsed_ms,
            },
        )

        logger.info("games projection generation start", extra={"selected_date": selected_date.isoformat()})
        generation_started = perf_counter()
        generated = _generate_candidates_from_eligible_player_pool(
            eligible_player_pool=eligible_player_pool,
            player_history=player_history,
        )
        generation_elapsed_ms = round((perf_counter() - generation_started) * 1000, 2)
        logger.info(
            "games projection generation end",
            extra={
                "selected_date": selected_date.isoformat(),
                "generated_projection_count": len(generated),
                "projection_generation_elapsed_ms": generation_elapsed_ms,
            },
        )

        if generated:
            _upsert_generated_rows(artifact_path=self._artifact_path, selected_date=selected_date, rows=generated)
            self._generated_cache_by_date[selected_date] = [row for row in generated]
            return generated

        if self._enable_dev_fallback:
            generated = _generate_placeholder_candidates(scheduled_games=scheduled_games)
            _upsert_generated_rows(artifact_path=self._artifact_path, selected_date=selected_date, rows=generated)
            self._generated_cache_by_date[selected_date] = [row for row in generated]
            return generated

        return []


@dataclass(frozen=True)
class _EligiblePlayerCandidate:
    game_id: str
    projected_team_name: str
    player: ActiveRosterPlayer


def _build_eligible_player_pool(
    scheduled_games: list[GameSummary],
    roster_repository: ActiveRosterSource,
    selected_date: date,
) -> list[_EligiblePlayerCandidate]:
    pool: list[_EligiblePlayerCandidate] = []
    for game in scheduled_games:
        for team_name in (game.away_team, game.home_team):
            logger.info(
                "games active roster fetch start",
                extra={"selected_date": selected_date.isoformat(), "team_name": team_name, "game_id": game.game_id},
            )
            players = roster_repository.active_players_for_team(team_name)
            logger.info(
                "games active roster fetch end",
                extra={
                    "selected_date": selected_date.isoformat(),
                    "team_name": team_name,
                    "game_id": game.game_id,
                    "active_roster_count": len(players),
                },
            )
            ranked = sorted(
                players,
                key=lambda p: (
                    -(p.historical_season_first_goals or 0.0),
                    -((p.historical_season_first_goals or 0.0) / max((p.historical_season_games_played or 82.0), 1.0)),
                    p.player_name.lower(),
                ),
            )
            for player in ranked:
                pool.append(
                    _EligiblePlayerCandidate(
                        game_id=game.game_id,
                        projected_team_name=team_name,
                        player=player,
                    )
                )
    return pool


def _generate_candidates_from_eligible_player_pool(
    eligible_player_pool: list[_EligiblePlayerCandidate],
    player_history: dict[str, PlayerHistoricalProduction],
    template: _ProjectionTemplate = _DEFAULT_TEMPLATE,
) -> list[PlayerProjectionCandidate]:
    rows: list[PlayerProjectionCandidate] = []
    rank_by_game_team: dict[tuple[str, str], int] = {}
    for candidate in eligible_player_pool:
        rank_key = (candidate.game_id, candidate.projected_team_name)
        rank = rank_by_game_team.get(rank_key, 0)
        rank_by_game_team[rank_key] = rank + 1
        probability = max(template.base_probability - (rank * template.decrement_per_rank), 0.01)
        player_historical = player_history.get(
            candidate.player.player_id,
            PlayerHistoricalProduction(
                season_first_goals=candidate.player.historical_season_first_goals,
                season_games_played=candidate.player.historical_season_games_played,
            ),
        )
        rows.append(
            PlayerProjectionCandidate(
                game_id=candidate.game_id,
                nhl_player_id=candidate.player.player_id,
                player_name=candidate.player.player_name,
                projected_team_name=candidate.projected_team_name,
                model_probability=round(probability, 4),
                historical_production=player_historical,
                roster_eligibility=PlayerRosterEligibility(
                    active_team_name=candidate.player.active_team_name,
                    is_active_roster=candidate.player.is_active_roster,
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


def _load_player_first_goal_history_from_artifact(
    selected_date: date,
    eligible_player_ids: set[str],
    path: Path,
) -> dict[str, PlayerHistoricalProduction]:
    if not eligible_player_ids:
        return {}
    payload = _load_artifact(path)
    projections = payload.get("projections")
    if not isinstance(projections, list):
        return {}

    history: dict[str, PlayerHistoricalProduction] = {}
    for row in projections:
        if not isinstance(row, dict):
            continue
        raw_player_id = row.get("nhl_player_id", row.get("player_id"))
        if not isinstance(raw_player_id, str) or not raw_player_id.strip():
            continue
        player_id = raw_player_id.strip()
        if player_id not in eligible_player_ids:
            continue
        first_goals = _as_float(row.get("historical_season_first_goals"))
        games_played = _as_float(row.get("historical_season_games_played"))
        if first_goals is None and games_played is None:
            continue
        current = history.get(player_id)
        if current is None:
            history[player_id] = PlayerHistoricalProduction(
                season_first_goals=first_goals,
                season_games_played=games_played,
            )
            continue

        history[player_id] = PlayerHistoricalProduction(
            season_first_goals=max(_history_value(current.season_first_goals), _history_value(first_goals)),
            season_games_played=max(_history_value(current.season_games_played), _history_value(games_played)),
        )
    return history


def load_player_first_goal_history_from_nhl_api(
    selected_date: date,
    eligible_player_ids: set[str],
    path: Path,
) -> dict[str, PlayerHistoricalProduction]:
    if not eligible_player_ids:
        return {}

    cached_history = _load_player_first_goal_history_from_artifact(
        selected_date=selected_date,
        eligible_player_ids=eligible_player_ids,
        path=path,
    )
    season_key = _season_key(selected_date)
    missing_player_ids = sorted(player_id for player_id in eligible_player_ids if player_id not in cached_history)
    resolved_from_memory = 0
    for player_id in missing_player_ids[:]:
        cached = _PLAYER_HISTORY_CACHE_BY_PLAYER_SEASON.get((player_id, season_key))
        if cached is None:
            continue
        cached_history[player_id] = cached
        missing_player_ids.remove(player_id)
        resolved_from_memory += 1
    if resolved_from_memory:
        logger.info(
            "Reused in-memory NHL player history cache",
            extra={
                "selected_date": selected_date.isoformat(),
                "season_key": season_key,
                "resolved_from_memory_count": resolved_from_memory,
            },
        )

    max_live_history_requests = max(
        0,
        int(
            os.getenv(
                "NHL_HISTORY_MAX_LIVE_REQUESTS_PER_GAMES",
                os.getenv("NHL_HISTORY_MAX_LIVE_REQUESTS_PER_GAME", "500"),
            )
        ),
    )
    if max_live_history_requests == 0:
        if missing_player_ids:
            logger.warning(
                "Skipping live NHL history fetches in /games path",
                extra={
                    "selected_date": selected_date.isoformat(),
                    "missing_player_history_count": len(missing_player_ids),
                    "max_live_history_requests": max_live_history_requests,
                },
            )
        return cached_history

    fetch_budget = min(max_live_history_requests, len(missing_player_ids))
    for player_id in missing_player_ids[:fetch_budget]:
        try:
            production = fetch_player_first_goal_history(player_id=player_id, selected_date=selected_date)
            cached_history[player_id] = production
            _PLAYER_HISTORY_CACHE_BY_PLAYER_SEASON[(player_id, season_key)] = production
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Live NHL player history fetch failed; continuing without this player history",
                extra={
                    "selected_date": selected_date.isoformat(),
                    "player_id": player_id,
                    "error": str(exc),
                },
            )

    skipped_due_to_budget = len(missing_player_ids) - fetch_budget
    if skipped_due_to_budget > 0:
        logger.warning(
            "Skipped live NHL history fetches due to request budget",
            extra={
                "selected_date": selected_date.isoformat(),
                "skipped_player_history_count": skipped_due_to_budget,
                "max_live_history_requests": max_live_history_requests,
            },
        )

    return cached_history


def _history_value(value: float | None) -> float:
    if value is None:
        return 0.0
    return value


def _season_key(selected_date: date) -> str:
    start_year = selected_date.year if selected_date.month >= 9 else selected_date.year - 1
    return f"{start_year}{start_year + 1}"


def _load_projection_rows_for_date_from_artifact(path: Path, selected_date: date) -> list[PlayerProjectionCandidate]:
    payload = _load_artifact(path)
    projections = payload.get("projections")
    if not isinstance(projections, list):
        return []

    rows: list[PlayerProjectionCandidate] = []
    selected_date_iso = selected_date.isoformat()
    for row in projections:
        if not isinstance(row, dict):
            continue
        if row.get("date") != selected_date_iso:
            continue
        player_id_raw = row.get("nhl_player_id", row.get("player_id"))
        if not isinstance(player_id_raw, str) or not player_id_raw.strip():
            continue
        game_id_raw = row.get("game_id")
        player_name_raw = row.get("player_name")
        team_name_raw = row.get("team_name")
        active_team_name_raw = row.get("active_team_name", team_name_raw)
        probability_raw = row.get("model_probability", row.get("probability"))
        if not isinstance(game_id_raw, str) or not game_id_raw.strip():
            continue
        if not isinstance(player_name_raw, str) or not player_name_raw.strip():
            continue
        if not isinstance(team_name_raw, str) or not team_name_raw.strip():
            continue
        if not isinstance(active_team_name_raw, str) or not active_team_name_raw.strip():
            continue
        if not isinstance(probability_raw, (int, float)):
            continue
        probability = float(probability_raw)
        if not (0 < probability < 1):
            continue
        rows.append(
            PlayerProjectionCandidate(
                game_id=game_id_raw.strip(),
                nhl_player_id=player_id_raw.strip(),
                player_name=player_name_raw.strip(),
                projected_team_name=team_name_raw.strip(),
                model_probability=probability,
                historical_production=PlayerHistoricalProduction(
                    season_first_goals=_as_float(row.get("historical_season_first_goals")),
                    season_games_played=_as_float(row.get("historical_season_games_played")),
                ),
                roster_eligibility=PlayerRosterEligibility(
                    active_team_name=active_team_name_raw.strip(),
                    is_active_roster=bool(row.get("is_active_roster", True)),
                ),
            )
        )
    return rows


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


_PLAYER_HISTORY_CACHE_BY_PLAYER_SEASON: dict[tuple[str, str], PlayerHistoricalProduction] = {}
