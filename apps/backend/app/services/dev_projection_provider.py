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
    position_code: str | None = None
    historical_season_first_goals: float | None = None
    historical_season_games_played: float | None = None
    historical_season_total_goals: float | None = None
    historical_season_total_shots: float | None = None
    historical_season_first_period_goals: float | None = None


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
                position_code=_normalize_position_code(raw.get("position_code")),
                historical_season_first_goals=_as_float(raw.get("historical_season_first_goals")),
                historical_season_games_played=_as_float(raw.get("historical_season_games_played")),
                historical_season_total_goals=_as_float(raw.get("historical_season_total_goals")),
                historical_season_total_shots=_as_float(raw.get("historical_season_total_shots")),
                historical_season_first_period_goals=_as_float(raw.get("historical_season_first_period_goals")),
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
                    position_code=_normalize_position_code(getattr(player, "position_code", None)),
                )
            )
        self._cache_by_team_name[team_key] = [player for player in rows]
        return rows


@dataclass(frozen=True)
class _ProjectionTemplate:
    first_goal_weight: float
    total_goals_weight: float
    shot_volume_weight: float
    first_period_goal_weight: float
    team_offense_weight: float
    team_defense_weight: float


_DEFAULT_TEMPLATE = _ProjectionTemplate(
    first_goal_weight=0.65,
    total_goals_weight=0.2,
    shot_volume_weight=0.1,
    first_period_goal_weight=0.05,
    team_offense_weight=0.65,
    team_defense_weight=0.35,
)
_GOALIE_POSITION_CODES = {"G", "GOALIE", "GK"}
_FORWARD_POSITION_CODES = {"C", "LW", "RW", "F"}


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
        scheduled_games = self._schedule_provider.fetch(selected_date)
        if not scheduled_games:
            return []
        valid_game_ids = {game.game_id for game in scheduled_games}
        valid_teams_by_game_id = {
            game.game_id: {game.away_team.strip().lower(), game.home_team.strip().lower()}
            for game in scheduled_games
        }

        cached_generated = self._generated_cache_by_date.get(selected_date)
        if cached_generated is not None:
            if _rows_match_scheduled_slate(
                rows=cached_generated,
                valid_game_ids=valid_game_ids,
                valid_teams_by_game_id=valid_teams_by_game_id,
            ) and not _is_stale_projection_snapshot(cached_generated):
                logger.info(
                    "games projection cache hit",
                    extra={
                        "selected_date": selected_date.isoformat(),
                        "projection_count": len(cached_generated),
                        "projection_cache_source": "memory",
                    },
                )
                return [row for row in cached_generated]
            logger.info(
                "games projection memory cache stale snapshot detected; regenerating",
                extra={
                    "selected_date": selected_date.isoformat(),
                    "projection_count": len(cached_generated),
                    "projection_cache_source": "memory",
                },
            )
            self._generated_cache_by_date.pop(selected_date, None)

        cached_artifact_rows = _load_projection_rows_for_date_from_artifact(self._artifact_path, selected_date)
        if cached_artifact_rows:
            if _is_stale_projection_snapshot(cached_artifact_rows) or not _rows_match_scheduled_slate(
                rows=cached_artifact_rows,
                valid_game_ids=valid_game_ids,
                valid_teams_by_game_id=valid_teams_by_game_id,
            ):
                logger.info(
                    "games projection cache stale snapshot detected; regenerating",
                    extra={
                        "selected_date": selected_date.isoformat(),
                        "projection_count": len(cached_artifact_rows),
                        "projection_cache_source": "artifact",
                    },
                )
                _delete_projection_rows_for_date(self._artifact_path, selected_date)
            else:
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
            ranked = sorted(_filter_and_prioritize_roster(players=players, projected_team_name=team_name), key=lambda p: p.player_name.lower())
            for player in ranked:
                pool.append(
                    _EligiblePlayerCandidate(
                        game_id=game.game_id,
                        projected_team_name=team_name,
                        player=player,
                    )
                )
    return pool


def _filter_and_prioritize_roster(players: list[ActiveRosterPlayer], projected_team_name: str) -> list[ActiveRosterPlayer]:
    eligible = [
        player
        for player in players
        if player.is_active_roster
        and player.active_team_name.strip().lower() == projected_team_name.strip().lower()
        and not _is_goalie(player.position_code)
    ]
    forwards = [player for player in eligible if _is_forward(player.position_code)]
    return forwards if forwards else eligible


def _is_goalie(position_code: str | None) -> bool:
    normalized = _normalize_position_code(position_code)
    return normalized in _GOALIE_POSITION_CODES


def _is_forward(position_code: str | None) -> bool:
    normalized = _normalize_position_code(position_code)
    return normalized in _FORWARD_POSITION_CODES


def _generate_candidates_from_eligible_player_pool(
    eligible_player_pool: list[_EligiblePlayerCandidate],
    player_history: dict[str, PlayerHistoricalProduction],
    template: _ProjectionTemplate = _DEFAULT_TEMPLATE,
) -> list[PlayerProjectionCandidate]:
    rows: list[PlayerProjectionCandidate] = []
    debug_game_id = os.getenv("GAMES_PROJECTION_DEBUG_GAME_ID", "").strip()
    debug_logged = False
    team_candidates: dict[tuple[str, str], list[_EligiblePlayerCandidate]] = {}
    game_team_names: dict[str, set[str]] = {}
    for candidate in eligible_player_pool:
        rank_key = (candidate.game_id, candidate.projected_team_name)
        team_candidates.setdefault(rank_key, []).append(candidate)
        game_team_names.setdefault(candidate.game_id, set()).add(candidate.projected_team_name)

    team_strength_by_game_team: dict[tuple[str, str], float] = {}
    for game_id, team_names in game_team_names.items():
        for team_name in team_names:
            own_key = (game_id, team_name)
            opponent_team_name = next((name for name in team_names if name != team_name), None)
            opponent_candidates = team_candidates.get((game_id, opponent_team_name), []) if opponent_team_name else []
            offense_strength = _team_offense_strength(team_candidates.get(own_key, []), player_history)
            defense_vulnerability = _team_defense_vulnerability(opponent_candidates, player_history)
            team_strength_by_game_team[own_key] = (
                template.team_offense_weight * offense_strength
                + template.team_defense_weight * defense_vulnerability
            )

    team_probability_by_game_team: dict[tuple[str, str], float] = {}
    for game_id, team_names in game_team_names.items():
        keys = [(game_id, team_name) for team_name in team_names]
        total_strength = sum(max(team_strength_by_game_team.get(key, 0.0), 0.01) for key in keys)
        for key in keys:
            team_probability_by_game_team[key] = max(team_strength_by_game_team.get(key, 0.01), 0.01) / max(total_strength, 0.01)

    for rank_key, candidates in team_candidates.items():
        scored_players: list[tuple[_EligiblePlayerCandidate, PlayerHistoricalProduction, float, float]] = []
        for candidate in candidates:
            player_historical = player_history.get(
                candidate.player.player_id,
                PlayerHistoricalProduction(
                    season_first_goals=candidate.player.historical_season_first_goals,
                    season_games_played=candidate.player.historical_season_games_played,
                    season_total_goals=candidate.player.historical_season_total_goals,
                    season_total_shots=candidate.player.historical_season_total_shots,
                    season_first_period_goals=candidate.player.historical_season_first_period_goals,
                ),
            )
            raw_player_score = _player_first_goal_score(player_historical, template)
            games_played = max(_history_value(player_historical.season_games_played), 1.0)
            shots_per_game = _history_value(player_historical.season_total_shots) / games_played
            scored_players.append((candidate, player_historical, raw_player_score, shots_per_game))

        scored_players = [row for row in scored_players if row[2] > 0]
        total_player_score = sum(score for _, _, score, _ in scored_players)
        if total_player_score <= 0:
            fallback_rows: list[tuple[_EligiblePlayerCandidate, PlayerHistoricalProduction, float, float]] = []
            fallback_candidates = sorted(candidates, key=lambda row: row.player.player_name.lower())
            fallback_size = len(fallback_candidates)
            for idx, candidate in enumerate(fallback_candidates):
                fallback_rows.append(
                    (
                        candidate,
                        PlayerHistoricalProduction(
                            season_first_goals=candidate.player.historical_season_first_goals,
                            season_games_played=candidate.player.historical_season_games_played,
                            season_total_goals=candidate.player.historical_season_total_goals,
                            season_total_shots=candidate.player.historical_season_total_shots,
                            season_first_period_goals=candidate.player.historical_season_first_period_goals,
                        ),
                        float(fallback_size - idx),
                        0.0,
                    )
                )
            scored_players = fallback_rows
            total_player_score = sum(score for _, _, score, _ in scored_players)
            logger.warning(
                "games projection generation applied differentiated fallback scores",
                extra={
                    "game_id": rank_key[0],
                    "projected_team_name": rank_key[1],
                    "candidate_count": len(candidates),
                },
            )
        team_probability = team_probability_by_game_team.get(rank_key, 0.5)
        scored_sorted = sorted(scored_players, key=lambda row: (-row[2], row[0].player.player_name.lower()))
        debug_rows: list[dict[str, Any]] = []
        for candidate, player_historical, player_score, shots_per_game in scored_sorted:
            player_share_within_team = player_score / max(total_player_score, 1e-9)
            probability = team_probability * player_share_within_team
            debug_rows.append(
                {
                    "player_name": candidate.player.player_name,
                    "position": candidate.player.position_code,
                    "season_first_goals": _history_value(player_historical.season_first_goals),
                    "season_total_goals": _history_value(player_historical.season_total_goals),
                    "shots_per_game": round(shots_per_game, 4),
                    "player_score_before_normalization": round(player_score, 6),
                    "final_probability_after_normalization": round(probability, 6),
                }
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
                        position_code=candidate.player.position_code,
                    ),
                )
            )
        if debug_game_id and not debug_logged and rank_key[0] == debug_game_id:
            debug_logged = True
            logger.info(
                "games projection debug for one game team",
                extra={
                    "game_id": rank_key[0],
                    "team_name": rank_key[1],
                    "candidate_count_before_filter": len(candidates),
                    "candidate_rows": debug_rows,
                },
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
                            season_total_goals=float(12 + (2 * index)),
                            season_total_shots=float(100 + (20 * index)),
                        ),
                        roster_eligibility=PlayerRosterEligibility(active_team_name=team_name, is_active_roster=True, position_code="F"),
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


def _delete_projection_rows_for_date(artifact_path: Path, selected_date: date) -> None:
    payload = _load_artifact(artifact_path)
    existing = payload.get("projections")
    if not isinstance(existing, list):
        return
    selected_date_iso = selected_date.isoformat()
    filtered = [row for row in existing if not isinstance(row, dict) or row.get("date") != selected_date_iso]
    if len(filtered) == len(existing):
        return
    payload["projections"] = filtered
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
                "position_code": row.roster_eligibility.position_code,
                "historical_season_first_goals": row.historical_production.season_first_goals,
                "historical_season_games_played": row.historical_production.season_games_played,
                "historical_season_total_goals": row.historical_production.season_total_goals,
                "historical_season_total_shots": row.historical_production.season_total_shots,
                "historical_season_first_period_goals": row.historical_production.season_first_period_goals,
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
        total_goals = _as_float(row.get("historical_season_total_goals"))
        total_shots = _as_float(row.get("historical_season_total_shots"))
        first_period_goals = _as_float(row.get("historical_season_first_period_goals"))
        if first_goals is None and games_played is None and total_goals is None and total_shots is None:
            continue
        current = history.get(player_id)
        if current is None:
            history[player_id] = PlayerHistoricalProduction(
                season_first_goals=first_goals,
                season_games_played=games_played,
                season_total_goals=total_goals,
                season_total_shots=total_shots,
                season_first_period_goals=first_period_goals,
            )
            continue

        history[player_id] = PlayerHistoricalProduction(
            season_first_goals=max(_history_value(current.season_first_goals), _history_value(first_goals)),
            season_games_played=max(_history_value(current.season_games_played), _history_value(games_played)),
            season_total_goals=max(_history_value(current.season_total_goals), _history_value(total_goals)),
            season_total_shots=max(_history_value(current.season_total_shots), _history_value(total_shots)),
            season_first_period_goals=max(_history_value(current.season_first_period_goals), _history_value(first_period_goals)),
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


def _player_first_goal_score(player_historical: PlayerHistoricalProduction, template: _ProjectionTemplate) -> float:
    first_goals = _history_value(player_historical.season_first_goals)
    total_goals = _history_value(player_historical.season_total_goals)
    total_shots = _history_value(player_historical.season_total_shots)
    first_period_goals = _history_value(player_historical.season_first_period_goals)
    games_played = max(_history_value(player_historical.season_games_played), 1.0)
    shots_per_game = total_shots / games_played
    return max(
        (
            template.first_goal_weight * first_goals
            + template.total_goals_weight * total_goals
            + template.shot_volume_weight * shots_per_game
            + template.first_period_goal_weight * first_period_goals
        ),
        0.0,
    )


def _team_offense_strength(
    candidates: list[_EligiblePlayerCandidate],
    player_history: dict[str, PlayerHistoricalProduction],
) -> float:
    if not candidates:
        return 0.01
    total_goals = 0.0
    for candidate in candidates:
        historical = player_history.get(
            candidate.player.player_id,
            PlayerHistoricalProduction(season_total_goals=candidate.player.historical_season_total_goals),
        )
        total_goals += _history_value(historical.season_total_goals)
    return max(total_goals / max(len(candidates), 1), 0.01)


def _team_defense_vulnerability(
    candidates: list[_EligiblePlayerCandidate],
    player_history: dict[str, PlayerHistoricalProduction],
) -> float:
    if not candidates:
        return 0.01
    total_first_goals = 0.0
    for candidate in candidates:
        historical = player_history.get(
            candidate.player.player_id,
            PlayerHistoricalProduction(season_first_goals=candidate.player.historical_season_first_goals),
        )
        total_first_goals += _history_value(historical.season_first_goals)
    return 1.0 / max((total_first_goals / max(len(candidates), 1)) + 1.0, 0.01)


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
        position_code = _normalize_position_code(row.get("position_code"))
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
        if position_code is None:
            continue
        if _is_goalie(position_code):
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
                    season_total_goals=_as_float(row.get("historical_season_total_goals")),
                    season_total_shots=_as_float(row.get("historical_season_total_shots")),
                    season_first_period_goals=_as_float(row.get("historical_season_first_period_goals")),
                ),
                roster_eligibility=PlayerRosterEligibility(
                    active_team_name=active_team_name_raw.strip(),
                    is_active_roster=bool(row.get("is_active_roster", True)),
                    position_code=position_code,
                ),
            )
        )
    return rows


def _rows_match_scheduled_slate(
    rows: list[PlayerProjectionCandidate],
    valid_game_ids: set[str],
    valid_teams_by_game_id: dict[str, set[str]],
) -> bool:
    if not rows:
        return False
    for row in rows:
        game_id = row.game_id.strip()
        if game_id not in valid_game_ids:
            return False
        valid_teams = valid_teams_by_game_id.get(game_id, set())
        if row.projected_team_name.strip().lower() not in valid_teams:
            return False
        if row.roster_eligibility.active_team_name.strip().lower() not in valid_teams:
            return False
    return True


def _is_stale_projection_snapshot(rows: list[PlayerProjectionCandidate]) -> bool:
    if not rows:
        return False
    includes_goalie = any(_is_goalie(row.roster_eligibility.position_code) for row in rows)
    unique_probabilities = {round(row.model_probability, 4) for row in rows}
    has_flat_probabilities = len(unique_probabilities) <= 2 and len(rows) >= 6
    has_near_flat_probabilities = len(unique_probabilities) <= 3
    has_missing_position_codes = any(row.roster_eligibility.position_code is None for row in rows)
    missing_enriched_history = any(
        row.historical_production.season_total_goals is None
        and row.historical_production.season_total_shots is None
        and row.historical_production.season_first_period_goals is None
        for row in rows
    )
    return (
        includes_goalie
        or has_missing_position_codes
        or has_flat_probabilities
        or (has_near_flat_probabilities and missing_enriched_history)
    )


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


def _normalize_position_code(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip().upper()
    return None


_PLAYER_HISTORY_CACHE_BY_PLAYER_SEASON: dict[tuple[str, str], PlayerHistoricalProduction] = {}
