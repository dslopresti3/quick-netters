from __future__ import annotations

from datetime import date, datetime, timezone
import logging
import os

from app.api.schemas import GameSummary, Recommendation, TeamProjectionLeader
from app.services.identity import name_aliases, normalize_name, normalize_team_token, team_alias_tokens
from app.services.interfaces import (
    AvailabilityProvider,
    OddsProvider,
    PlayerProjectionCandidate,
    ProjectionProvider,
    RecommendationsProvider,
    ScheduleProvider,
)
from app.services.odds import (
    NormalizedPlayerOdds,
    OddsEventMapping,
    OddsPlayerMapping,
    american_to_implied_probability,
    expected_value_per_unit,
    fair_american_odds,
    is_stale,
)

logger = logging.getLogger(__name__)


class ValueRecommendationService(RecommendationsProvider, AvailabilityProvider):
    """Build value recommendations by comparing model probabilities against market odds."""

    def __init__(self, schedule_provider: ScheduleProvider, projection_provider: ProjectionProvider, odds_provider: OddsProvider) -> None:
        self._schedule_provider = schedule_provider
        self._projection_provider = projection_provider
        self._odds_provider = odds_provider

    def fetch_daily(self, selected_date: date) -> list[Recommendation]:
        recommendations = self._build_ranked_recommendations(selected_date)
        return recommendations[:3]

    def fetch_for_game(self, selected_date: date, game_id: str) -> list[Recommendation]:
        recommendations = self._build_ranked_recommendations(selected_date)
        game_recommendations = [recommendation for recommendation in recommendations if recommendation.game_id == game_id]
        return game_recommendations[:3]

    def projections_available(self, selected_date: date) -> bool:
        games = self._schedule_provider.fetch(selected_date)
        _, projections_available = self._build_top_projection_lookup(selected_date, games)
        return projections_available

    def odds_available(self, selected_date: date) -> bool:
        scheduled_games = self._schedule_provider.fetch(selected_date)
        projections = self._eligible_projection_candidates(selected_date, scheduled_games)
        if not projections:
            return False
        snapshots = self._odds_provider.fetch_player_first_goal_odds(selected_date)
        mapped_rows = self._map_odds_rows(selected_date, scheduled_games, projections, snapshots)
        return any(row.market_odds_american != 0 and not is_stale(row.snapshot_at) for row in mapped_rows)

    def attach_top_projected_scorers(self, selected_date: date, games: list[GameSummary]) -> list[GameSummary]:
        top_by_game_team, _ = self._build_top_projection_lookup(selected_date, games)

        enriched_games: list[GameSummary] = []
        for game in games:
            enriched = game.model_copy(deep=True)
            away_pick = top_by_game_team.get((game.game_id, game.away_team))
            home_pick = top_by_game_team.get((game.game_id, game.home_team))

            if away_pick:
                enriched.away_top_projected_scorer = TeamProjectionLeader(
                    team=away_pick.projected_team_name,
                    player_id=away_pick.nhl_player_id,
                    player_name=away_pick.player_name,
                    model_probability=round(away_pick.model_probability, 4),
                )

            if home_pick:
                enriched.home_top_projected_scorer = TeamProjectionLeader(
                    team=home_pick.projected_team_name,
                    player_id=home_pick.nhl_player_id,
                    player_name=home_pick.player_name,
                    model_probability=round(home_pick.model_probability, 4),
                )

            enriched_games.append(enriched)

        return enriched_games

    def _build_top_projection_lookup(
        self,
        selected_date: date,
        games: list[GameSummary] | None,
    ) -> tuple[dict[tuple[str, str], PlayerProjectionCandidate], bool]:
        projection_rows = self._eligible_projection_candidates(selected_date, games)
        valid_game_ids: set[str] | None = None
        game_team_lookup: dict[tuple[str, str], str] = {}
        if games is not None:
            valid_game_ids = {game.game_id for game in games}
            for game in games:
                for team_name in (game.away_team, game.home_team):
                    for alias_token in team_alias_tokens(team_name):
                        game_team_lookup[(game.game_id, alias_token)] = team_name

        top_by_game_team: dict[tuple[str, str], PlayerProjectionCandidate] = {}
        attached_projection_count = 0
        seen_projection_keys: set[tuple[str, str]] = set()

        for projection in projection_rows:
            if projection.model_probability <= 0 or projection.model_probability >= 1:
                logger.warning(
                    "Skipping projection row with invalid probability",
                    extra={"selected_date": selected_date.isoformat(), "value": projection.model_probability},
                )
                continue

            game_id_value = projection.game_id.strip()
            projection_team_name = projection.roster_eligibility.active_team_name.strip()
            resolved_team_name = projection_team_name
            if valid_game_ids is not None:
                if game_id_value not in valid_game_ids:
                    continue
                team_aliases = team_alias_tokens(projection_team_name)
                if not team_aliases:
                    continue
                matched_team = None
                for alias_token in team_aliases:
                    candidate = game_team_lookup.get((game_id_value, alias_token))
                    if candidate is not None:
                        matched_team = candidate
                        break
                if matched_team is None:
                    continue
                resolved_team_name = matched_team

            projection_key = (game_id_value, resolved_team_name)

            dedupe_key = (projection_key[0], projection.nhl_player_id.strip())
            if dedupe_key in seen_projection_keys:
                logger.warning(
                    "Skipping duplicate projection row",
                    extra={
                        "selected_date": selected_date.isoformat(),
                        "game_id": projection_key[0],
                        "player_id": projection.nhl_player_id.strip(),
                    },
                )
                continue
            seen_projection_keys.add(dedupe_key)

            attached_projection_count += 1
            normalized_projection = PlayerProjectionCandidate(
                game_id=projection_key[0],
                nhl_player_id=projection.nhl_player_id.strip(),
                player_name=projection.player_name.strip(),
                projected_team_name=resolved_team_name,
                model_probability=projection.model_probability,
                historical_production=projection.historical_production,
                roster_eligibility=projection.roster_eligibility,
            )
            existing = top_by_game_team.get(projection_key)
            if existing is None or projection.model_probability > existing.model_probability:
                top_by_game_team[projection_key] = normalized_projection

        return top_by_game_team, attached_projection_count > 0

    def _build_ranked_recommendations(self, selected_date: date) -> list[Recommendation]:
        scheduled_games = self._schedule_provider.fetch(selected_date)
        projections = self._eligible_projection_candidates(selected_date, scheduled_games)
        if not projections:
            return []
        raw_odds_snapshots = self._odds_provider.fetch_player_first_goal_odds(selected_date)
        odds_snapshots = self._map_odds_rows(selected_date, scheduled_games, projections, raw_odds_snapshots)
        games_by_id = {game.game_id: game for game in scheduled_games}
        projections_by_game_player = {(row.game_id, row.nhl_player_id): row for row in projections}

        recommendations: list[Recommendation] = []
        for (game_id, player_id), projection in projections_by_game_player.items():
            game = games_by_id.get(game_id)
            odds_snapshot = _latest_snapshot_for_player(odds_snapshots, game_id, player_id)

            if game is None or odds_snapshot is None or is_stale(odds_snapshot.snapshot_at):
                continue

            implied_probability = american_to_implied_probability(odds_snapshot.market_odds_american)
            fair_odds = fair_american_odds(projection.model_probability)
            ev = expected_value_per_unit(projection.model_probability, odds_snapshot.market_odds_american)

            if implied_probability is None or fair_odds is None or ev is None:
                continue

            edge = projection.model_probability - implied_probability
            if edge <= 0:
                continue

            recommendations.append(
                Recommendation(
                    game_id=game_id,
                    game_time=game.game_time,
                    away_team=game.away_team,
                    home_team=game.home_team,
                    player_id=player_id,
                    player_name=projection.player_name,
                    model_probability=round(projection.model_probability, 4),
                    fair_odds=fair_odds,
                    market_odds=odds_snapshot.market_odds_american,
                    edge=round(edge, 4),
                    ev=round(ev, 4),
                    implied_probability=round(implied_probability, 4),
                    odds_snapshot_at=odds_snapshot.snapshot_at,
                    confidence_tag=_confidence_tag(ev),
                )
            )

        return sorted(recommendations, key=lambda rec: (rec.ev, rec.edge, rec.model_probability), reverse=True)

    def _eligible_projection_candidates(self, selected_date: date, games: list[GameSummary] | None) -> list[PlayerProjectionCandidate]:
        projection_rows = self._projection_provider.fetch_player_first_goal_projections(selected_date)
        if games is None:
            return [projection for projection in projection_rows if projection.roster_eligibility.is_active_roster]

        game_team_lookup: dict[str, set[str]] = {}
        for game in games:
            game_team_lookup[game.game_id] = team_alias_tokens(game.away_team) | team_alias_tokens(game.home_team)

        eligible_rows: list[PlayerProjectionCandidate] = []
        for projection in projection_rows:
            if not projection.roster_eligibility.is_active_roster:
                continue

            team_tokens = team_alias_tokens(projection.roster_eligibility.active_team_name)
            game_tokens = game_team_lookup.get(projection.game_id)
            if not team_tokens or game_tokens is None:
                continue
            if team_tokens.isdisjoint(game_tokens):
                continue
            eligible_rows.append(projection)

        return eligible_rows

    def _map_odds_rows(
        self,
        selected_date: date,
        scheduled_games: list[GameSummary],
        projections: list[PlayerProjectionCandidate],
        odds_rows: list[NormalizedPlayerOdds],
    ) -> list[NormalizedPlayerOdds]:
        tolerance_minutes = int(os.getenv("ODDS_EVENT_TIME_TOLERANCE_MINUTES", "90"))
        tolerance_seconds = tolerance_minutes * 60
        matched_at = datetime.now(timezone.utc)
        projections_by_game: dict[str, list[PlayerProjectionCandidate]] = {}
        for projection in projections:
            projections_by_game.setdefault(projection.game_id, []).append(projection)

        mapped_rows: list[NormalizedPlayerOdds] = []
        for row in odds_rows:
            event_mapping = _match_event_to_game(row=row, scheduled_games=scheduled_games, tolerance_seconds=tolerance_seconds, matched_at=matched_at)
            player_mapping = _match_player_to_projection(
                row=row,
                event_mapping=event_mapping,
                projections=projections_by_game.get(event_mapping.nhl_game_id or "", []),
                matched_at=matched_at,
            )
            if event_mapping.match_status != "matched" or player_mapping.match_status != "matched":
                continue
            mapped_rows.append(
                NormalizedPlayerOdds(
                    nhl_game_id=event_mapping.nhl_game_id,
                    nhl_player_id=player_mapping.nhl_player_id,
                    market_odds_american=row.market_odds_american,
                    snapshot_at=row.snapshot_at,
                    provider_name=row.provider_name,
                    provider_event_id=row.provider_event_id,
                    provider_player_id=row.provider_player_id,
                    provider_player_name_raw=row.provider_player_name_raw,
                    provider_team_raw=row.provider_team_raw,
                    away_team_raw=row.away_team_raw,
                    home_team_raw=row.home_team_raw,
                    provider_start_time=row.provider_start_time,
                    source=row.source,
                    book=row.book,
                    freshness_seconds=row.freshness_seconds,
                    freshness_status=row.freshness_status,
                    is_fresh=row.is_fresh,
                    event_mapping=event_mapping,
                    player_mapping=player_mapping,
                )
            )
        return mapped_rows


def _match_event_to_game(
    row: NormalizedPlayerOdds,
    scheduled_games: list[GameSummary],
    tolerance_seconds: int,
    matched_at: datetime,
) -> OddsEventMapping:
    away_normalized = normalize_team_token(row.away_team_raw or "")
    home_normalized = normalize_team_token(row.home_team_raw or "")
    if not away_normalized or not home_normalized or row.provider_start_time is None:
        return OddsEventMapping(
            provider_name=row.provider_name,
            provider_event_id=row.provider_event_id,
            nhl_game_id=None,
            away_team_raw=row.away_team_raw,
            home_team_raw=row.home_team_raw,
            away_team_normalized=away_normalized or None,
            home_team_normalized=home_normalized or None,
            provider_start_time=row.provider_start_time,
            nhl_start_time=None,
            match_status="unmatched",
            match_confidence=0.0,
            matched_at=matched_at,
        )

    candidates: list[tuple[int, float, GameSummary]] = []
    for game in scheduled_games:
        away_tokens = team_alias_tokens(game.away_team)
        home_tokens = team_alias_tokens(game.home_team)
        away_match = away_normalized in away_tokens
        home_match = home_normalized in home_tokens
        if not away_match or not home_match:
            continue
        time_delta = abs(int((game.game_time - row.provider_start_time).total_seconds()))
        if time_delta > tolerance_seconds:
            continue
        confidence = max(0.0, 1.0 - (time_delta / max(tolerance_seconds, 1)))
        candidates.append((time_delta, confidence, game))

    if not candidates:
        return OddsEventMapping(
            provider_name=row.provider_name,
            provider_event_id=row.provider_event_id,
            nhl_game_id=None,
            away_team_raw=row.away_team_raw,
            home_team_raw=row.home_team_raw,
            away_team_normalized=away_normalized,
            home_team_normalized=home_normalized,
            provider_start_time=row.provider_start_time,
            nhl_start_time=None,
            match_status="unmatched",
            match_confidence=0.0,
            matched_at=matched_at,
        )

    candidates.sort(key=lambda item: item[0])
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return OddsEventMapping(
            provider_name=row.provider_name,
            provider_event_id=row.provider_event_id,
            nhl_game_id=None,
            away_team_raw=row.away_team_raw,
            home_team_raw=row.home_team_raw,
            away_team_normalized=away_normalized,
            home_team_normalized=home_normalized,
            provider_start_time=row.provider_start_time,
            nhl_start_time=None,
            match_status="ambiguous",
            match_confidence=0.25,
            matched_at=matched_at,
        )

    _, confidence, game = candidates[0]
    return OddsEventMapping(
        provider_name=row.provider_name,
        provider_event_id=row.provider_event_id,
        nhl_game_id=game.game_id,
        away_team_raw=row.away_team_raw,
        home_team_raw=row.home_team_raw,
        away_team_normalized=away_normalized,
        home_team_normalized=home_normalized,
        provider_start_time=row.provider_start_time,
        nhl_start_time=game.game_time,
        match_status="matched",
        match_confidence=round(confidence, 4),
        matched_at=matched_at,
    )


def _match_player_to_projection(
    row: NormalizedPlayerOdds,
    event_mapping: OddsEventMapping,
    projections: list[PlayerProjectionCandidate],
    matched_at: datetime,
) -> OddsPlayerMapping:
    provider_name = row.provider_name
    player_name_raw = row.provider_player_name_raw or ""
    provider_team_raw = row.provider_team_raw
    if event_mapping.match_status != "matched" or not player_name_raw:
        return OddsPlayerMapping(
            provider_name=provider_name,
            provider_player_id=row.provider_player_id,
            provider_player_name_raw=player_name_raw,
            provider_team_raw=provider_team_raw,
            nhl_player_id=None,
            nhl_player_name=None,
            nhl_team=None,
            match_status="unmatched",
            match_confidence=0.0,
            matched_at=matched_at,
        )

    provider_aliases = name_aliases(player_name_raw)
    team_context_tokens = team_alias_tokens(provider_team_raw) if provider_team_raw else set()

    candidates: list[PlayerProjectionCandidate] = []
    for projection in projections:
        if not projection.roster_eligibility.is_active_roster:
            continue
        if team_context_tokens and team_context_tokens.isdisjoint(team_alias_tokens(projection.roster_eligibility.active_team_name)):
            continue
        if provider_aliases.isdisjoint(name_aliases(projection.player_name)):
            continue
        candidates.append(projection)

    if len(candidates) != 1:
        return OddsPlayerMapping(
            provider_name=provider_name,
            provider_player_id=row.provider_player_id,
            provider_player_name_raw=player_name_raw,
            provider_team_raw=provider_team_raw,
            nhl_player_id=None,
            nhl_player_name=None,
            nhl_team=None,
            match_status="unmatched" if not candidates else "ambiguous",
            match_confidence=0.0 if not candidates else 0.4,
            matched_at=matched_at,
        )

    player = candidates[0]
    confidence = 0.8
    if normalize_name(player.player_name) == normalize_name(player_name_raw):
        confidence = 1.0
    return OddsPlayerMapping(
        provider_name=provider_name,
        provider_player_id=row.provider_player_id,
        provider_player_name_raw=player_name_raw,
        provider_team_raw=provider_team_raw,
        nhl_player_id=player.nhl_player_id,
        nhl_player_name=player.player_name,
        nhl_team=player.roster_eligibility.active_team_name,
        match_status="matched",
        match_confidence=confidence,
        matched_at=matched_at,
    )


def _latest_snapshot_for_player(
    snapshots: list[NormalizedPlayerOdds], game_id: str, player_id: str
) -> NormalizedPlayerOdds | None:
    candidates = [snapshot for snapshot in snapshots if snapshot.nhl_game_id == game_id and snapshot.nhl_player_id == player_id]
    if not candidates:
        return None
    return max(candidates, key=lambda snapshot: snapshot.snapshot_at)


def _confidence_tag(ev: float) -> str:
    if ev >= 0.06:
        return "high"
    if ev >= 0.03:
        return "medium"
    return "watch"
