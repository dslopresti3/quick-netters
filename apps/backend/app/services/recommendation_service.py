from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import logging
import os
from zoneinfo import ZoneInfo

from app.api.schemas import GameSummary, Recommendation, RecommendationModelDebug, TeamProjectionLeader
from app.services.dev_projection_provider import _DEFAULT_TEMPLATE, _is_goalie, _player_model_features
from app.services.identity import name_aliases, normalize_name, normalize_team_token, team_alias_tokens
from app.services.interfaces import (
    AvailabilityProvider,
    OddsProvider,
    PlayerProjectionCandidate,
    ProjectionProvider,
    RecommendationsProvider,
    ScheduleProvider,
)
from app.services.markets import Market
from app.services.probabilities import estimate_anytime_goal_probability
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
DEFAULT_EVENT_MATCH_TIMEZONE = "America/New_York"
_SCORE_WEIGHTS = {
    "probability": 0.5,
    "value": 0.3,
    "confidence": 0.20,
}

TOP_PLAY_MIN_ODDS = 1000
TOP_PLAY_MAX_ODDS = 2500
TOP_PLAY_MIN_MODEL_PROBABILITY = 0.03
TOP_THREE_MIN_MODEL_PROBABILITY = 0.03
TOP_THREE_MIN_EV = -0.02
TOP_THREE_MIN_EDGE = -0.01

UNDERDOG_MIN_ODDS = 1800
UNDERDOG_MAX_ODDS = 4000
UNDERDOG_MIN_MODEL_PROBABILITY = 0.025


class ValueRecommendationService(RecommendationsProvider, AvailabilityProvider):
    """Build value recommendations by comparing model probabilities against market odds."""

    def __init__(self, schedule_provider: ScheduleProvider, projection_provider: ProjectionProvider, odds_provider: OddsProvider) -> None:
        self._schedule_provider = schedule_provider
        self._projection_provider = projection_provider
        self._odds_provider = odds_provider
        self._projection_cache_by_date: dict[date, list[PlayerProjectionCandidate]] = {}
        self._odds_cache_by_date_market: dict[tuple[date, Market], list[NormalizedPlayerOdds]] = {}

    def fetch_daily(self, selected_date: date, market: Market = "first_goal") -> list[Recommendation]:
        recommendations = self._build_ranked_recommendations(selected_date, market=market)
        return recommendations[:3]

    def fetch_for_game(self, selected_date: date, game_id: str, market: Market = "first_goal") -> list[Recommendation]:
        top_plays, _, _ = self.fetch_game_recommendation_buckets(selected_date, game_id, market=market)
        return top_plays

    def fetch_game_recommendation_buckets(
        self,
        selected_date: date,
        game_id: str,
        market: Market = "first_goal",
    ) -> tuple[list[Recommendation], Recommendation | None, Recommendation | None]:
        game_recommendations = [
            recommendation for recommendation in self._build_ranked_recommendations(selected_date, market=market) if recommendation.game_id == game_id
        ]
        top_plays, best_bet = _select_top_play_bucket(game_recommendations)
        underdog = _select_underdog_bucket(game_recommendations, best_bet=best_bet)
        return top_plays, best_bet, underdog

    def projections_available(self, selected_date: date, market: Market = "first_goal") -> bool:
        games = self._schedule_provider.fetch(selected_date)
        _, projections_available = self._build_top_projection_lookup(selected_date, games)
        return projections_available

    def odds_available(self, selected_date: date, market: Market = "first_goal") -> bool:
        scheduled_games = self._schedule_provider.fetch(selected_date)
        projections = self._eligible_projection_candidates(selected_date, scheduled_games)
        if not projections:
            return False
        snapshots = self._odds_rows_for_date(selected_date, market=market)
        mapped_rows = self._map_odds_rows(selected_date, scheduled_games, projections, snapshots)
        return any(_is_valid_matched_odds_row(row) for row in mapped_rows)

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

    def _build_ranked_recommendations(self, selected_date: date, market: Market = "first_goal") -> list[Recommendation]:
        scheduled_games = self._schedule_provider.fetch(selected_date)
        projections = self._eligible_projection_candidates(selected_date, scheduled_games)
        if not projections:
            return []
        raw_odds_snapshots = self._odds_rows_for_date(selected_date, market=market)
        odds_snapshots = self._map_odds_rows(selected_date, scheduled_games, projections, raw_odds_snapshots)
        games_by_id = {game.game_id: game for game in scheduled_games}
        projections_by_game_player = {(row.game_id, row.nhl_player_id): row for row in projections}

        recommendations: list[Recommendation] = []
        for (game_id, player_id), projection in projections_by_game_player.items():
            game = games_by_id.get(game_id)
            odds_snapshot = _latest_snapshot_for_player(odds_snapshots, game_id, player_id)
            market_probability = _market_probability_for_projection(projection=projection, market=market)

            if game is None or odds_snapshot is None or not _is_valid_matched_odds_row(odds_snapshot) or market_probability is None:
                continue

            implied_probability = american_to_implied_probability(odds_snapshot.market_odds_american)
            decimal_odds = _american_to_decimal_odds(odds_snapshot.market_odds_american)
            fair_odds = fair_american_odds(market_probability)
            ev = expected_value_per_unit(market_probability, odds_snapshot.market_odds_american)

            if implied_probability is None or decimal_odds is None or fair_odds is None or ev is None:
                continue

            edge = market_probability - implied_probability

            confidence_score = _confidence_score(
                projection=projection,
                market_odds=odds_snapshot.market_odds_american,
            )

            recommendations.append(
                Recommendation(
                    game_id=game_id,
                    game_time=game.game_time,
                    away_team=game.away_team,
                    home_team=game.home_team,
                    player_id=player_id,
                    player_name=projection.player_name,
                    player_team=projection.projected_team_name,
                    team_name=projection.projected_team_name,
                    model_probability=round(market_probability, 4),
                    fair_odds=fair_odds,
                    market_odds=odds_snapshot.market_odds_american,
                    decimal_odds=round(decimal_odds, 4),
                    edge=round(edge, 4),
                    ev=round(ev, 4),
                    confidence_score=round(confidence_score, 4),
                    recommendation_score=None,
                    model_debug=(
                        _build_model_debug_payload(
                            projection=projection,
                            fair_odds=fair_odds,
                            edge=edge,
                            ev=ev,
                            confidence_score=confidence_score,
                            recommendation_score=0.0,
                        )
                        if _debug_transparency_enabled()
                        else None
                    ),
                    implied_probability=round(implied_probability, 4),
                    odds_snapshot_at=odds_snapshot.snapshot_at,
                    confidence_tag=_confidence_tag(ev, confidence_score),
                    goals_this_year=projection.historical_production.season_total_goals,
                    first_goals_this_year=projection.historical_production.season_first_goals,
                )
            )

        grouped_by_game: dict[str, list[Recommendation]] = defaultdict(list)
        for recommendation in recommendations:
            grouped_by_game[recommendation.game_id].append(recommendation)

        for game_recommendations in grouped_by_game.values():
            _attach_play_scores(game_recommendations)

        return sorted(
            recommendations,
            key=lambda rec: (
                rec.recommendation_score or 0.0,
                rec.model_probability,
                rec.edge,
                rec.ev,
            ),
            reverse=True,
        )

    def _eligible_projection_candidates(self, selected_date: date, games: list[GameSummary] | None) -> list[PlayerProjectionCandidate]:
        projection_rows = self._projection_rows_for_date(selected_date)
        if games is None:
            return [
                projection
                for projection in projection_rows
                if projection.roster_eligibility.is_active_roster
                and not _is_goalie(projection.roster_eligibility.position_code)
            ]

        game_team_lookup: dict[str, set[str]] = {}
        for game in games:
            game_team_lookup[game.game_id] = team_alias_tokens(game.away_team) | team_alias_tokens(game.home_team)

        eligible_rows: list[PlayerProjectionCandidate] = []
        for projection in projection_rows:
            if not projection.roster_eligibility.is_active_roster:
                continue
            if _is_goalie(projection.roster_eligibility.position_code):
                continue

            team_tokens = team_alias_tokens(projection.roster_eligibility.active_team_name)
            game_tokens = game_team_lookup.get(projection.game_id)
            if not team_tokens or game_tokens is None:
                continue
            if team_tokens.isdisjoint(game_tokens):
                continue
            eligible_rows.append(projection)

        return eligible_rows

    def _projection_rows_for_date(self, selected_date: date) -> list[PlayerProjectionCandidate]:
        cached = self._projection_cache_by_date.get(selected_date)
        if cached is not None:
            return cached
        rows = self._projection_provider.fetch_player_first_goal_projections(selected_date)
        self._projection_cache_by_date[selected_date] = rows
        return rows

    def _odds_rows_for_date(self, selected_date: date, market: Market = "first_goal") -> list[NormalizedPlayerOdds]:
        cache_key = (selected_date, market)
        cached = self._odds_cache_by_date_market.get(cache_key)
        if cached is not None:
            return cached
        try:
            rows = self._odds_provider.fetch_player_first_goal_odds(selected_date, market=market)
        except TypeError:
            rows = self._odds_provider.fetch_player_first_goal_odds(selected_date)
        self._odds_cache_by_date_market[cache_key] = rows
        return rows

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

    event_match_timezone = os.getenv("ODDS_EVENT_MATCH_TIMEZONE", DEFAULT_EVENT_MATCH_TIMEZONE)
    candidates: list[tuple[int, float, GameSummary]] = []
    for game in scheduled_games:
        away_tokens = team_alias_tokens(game.away_team)
        home_tokens = team_alias_tokens(game.home_team)
        away_match = away_normalized in away_tokens
        home_match = home_normalized in home_tokens
        if not away_match or not home_match:
            continue
        time_delta = _event_start_delta_seconds(
            provider_start_time=row.provider_start_time,
            canonical_start_time=game.game_time,
            local_timezone_name=event_match_timezone,
        )
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


def _market_probability_for_projection(projection: PlayerProjectionCandidate, market: Market) -> float | None:
    market_probability = projection.probability_for_market(market)
    if market_probability is not None:
        return market_probability
    if market == "anytime":
        return estimate_anytime_goal_probability(projection.historical_production)
    return None


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
    event_team_tokens = team_alias_tokens(row.away_team_raw or "") | team_alias_tokens(row.home_team_raw or "")
    apply_team_context_filter = bool(team_context_tokens)
    if apply_team_context_filter and event_team_tokens and team_context_tokens.isdisjoint(event_team_tokens):
        # Some books populate outcome.description with non-team metadata (e.g. "Any Other Player").
        # In those cases, enforcing team context eliminates all valid player candidates.
        apply_team_context_filter = False

    scored_candidates: list[tuple[float, PlayerProjectionCandidate]] = []
    for projection in projections:
        if not projection.roster_eligibility.is_active_roster:
            continue
        projection_team_tokens = team_alias_tokens(projection.roster_eligibility.active_team_name)
        if apply_team_context_filter and team_context_tokens.isdisjoint(projection_team_tokens):
            continue
        projection_aliases = name_aliases(projection.player_name)
        if provider_aliases.isdisjoint(projection_aliases):
            continue
        score = _player_candidate_match_score(
            provider_player_name_raw=player_name_raw,
            provider_aliases=provider_aliases,
            projection=projection,
            projection_aliases=projection_aliases,
            projection_team_tokens=projection_team_tokens,
            team_context_tokens=team_context_tokens,
        )
        scored_candidates.append((score, projection))

    if not scored_candidates:
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
    scored_candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, player = scored_candidates[0]
    top_tied = [candidate for score, candidate in scored_candidates if score == best_score]
    if len(top_tied) > 1:
        return OddsPlayerMapping(
            provider_name=provider_name,
            provider_player_id=row.provider_player_id,
            provider_player_name_raw=player_name_raw,
            provider_team_raw=provider_team_raw,
            nhl_player_id=None,
            nhl_player_name=None,
            nhl_team=None,
            match_status="ambiguous",
            match_confidence=0.4,
            matched_at=matched_at,
        )
    confidence = min(max(best_score, 0.5), 1.0)
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


def _player_candidate_match_score(
    provider_player_name_raw: str,
    provider_aliases: set[str],
    projection: PlayerProjectionCandidate,
    projection_aliases: set[str],
    projection_team_tokens: set[str],
    team_context_tokens: set[str],
) -> float:
    score = 0.5
    normalized_provider_name = normalize_name(provider_player_name_raw)
    normalized_projection_name = normalize_name(projection.player_name)

    if normalized_provider_name == normalized_projection_name:
        score += 0.4
    else:
        shared_aliases = provider_aliases & projection_aliases
        if shared_aliases:
            longest_alias = max(len(alias) for alias in shared_aliases)
            score += min(0.3, longest_alias / 50)
        if normalized_provider_name.replace(" ", "") == normalized_projection_name.replace(" ", ""):
            score += 0.2

    if team_context_tokens and not team_context_tokens.isdisjoint(projection_team_tokens):
        score += 0.1

    return round(score, 4)


def _latest_snapshot_for_player(
    snapshots: list[NormalizedPlayerOdds], game_id: str, player_id: str
) -> NormalizedPlayerOdds | None:
    candidates = [snapshot for snapshot in snapshots if snapshot.nhl_game_id == game_id and snapshot.nhl_player_id == player_id]
    if not candidates:
        return None
    return max(candidates, key=lambda snapshot: snapshot.snapshot_at)


def _american_to_decimal_odds(american_odds: int) -> float | None:
    if american_odds > 0:
        return 1 + (american_odds / 100)
    if american_odds < 0:
        return 1 + (100 / abs(american_odds))
    return None


def _min_max_normalize(value: float, min_value: float, max_value: float) -> float:
    if max_value == min_value:
        return 0.5
    return (value - min_value) / (max_value - min_value)


def _top_play_eligible(recommendation: Recommendation) -> bool:
    return (
        recommendation.ev > 0
        and recommendation.edge > 0
        and recommendation.model_probability >= TOP_PLAY_MIN_MODEL_PROBABILITY
        and recommendation.market_odds >= TOP_PLAY_MIN_ODDS
        and recommendation.market_odds <= TOP_PLAY_MAX_ODDS
    )


def _top_three_eligible(recommendation: Recommendation) -> bool:
    return (
        recommendation.model_probability >= TOP_THREE_MIN_MODEL_PROBABILITY
        and recommendation.ev >= TOP_THREE_MIN_EV
        and recommendation.edge >= TOP_THREE_MIN_EDGE
        and recommendation.market_odds <= TOP_PLAY_MAX_ODDS
    )


def _underdog_eligible(recommendation: Recommendation) -> bool:
    return (
        recommendation.ev > 0
        and recommendation.edge > 0
        and recommendation.model_probability >= UNDERDOG_MIN_MODEL_PROBABILITY
        and recommendation.market_odds >= UNDERDOG_MIN_ODDS
        and recommendation.market_odds <= UNDERDOG_MAX_ODDS
    )


def _attach_play_scores(game_recommendations: list[Recommendation]) -> None:
    eligible_top_plays = [recommendation for recommendation in game_recommendations if _top_three_eligible(recommendation)]
    if not eligible_top_plays:
        for recommendation in game_recommendations:
            recommendation.recommendation_score = 0.0
        return

    min_probability = min(recommendation.model_probability for recommendation in eligible_top_plays)
    max_probability = max(recommendation.model_probability for recommendation in eligible_top_plays)
    min_edge = min(recommendation.edge for recommendation in eligible_top_plays)
    max_edge = max(recommendation.edge for recommendation in eligible_top_plays)
    min_ev = min(recommendation.ev for recommendation in eligible_top_plays)
    max_ev = max(recommendation.ev for recommendation in eligible_top_plays)

    for recommendation in game_recommendations:
        recommendation.recommendation_score = 0.0

    for recommendation in eligible_top_plays:
        p_norm = _min_max_normalize(recommendation.model_probability, min_probability, max_probability)
        edge_norm = _min_max_normalize(recommendation.edge, min_edge, max_edge)
        ev_norm = _min_max_normalize(recommendation.ev, min_ev, max_ev)
        play_score = (0.50 * p_norm) + (0.25 * edge_norm) + (0.25 * ev_norm)
        recommendation.recommendation_score = round(play_score, 4)


def _select_top_play_bucket(game_recommendations: list[Recommendation]) -> tuple[list[Recommendation], Recommendation | None]:
    eligible_top_plays = [recommendation for recommendation in game_recommendations if _top_three_eligible(recommendation)]
    sorted_top_plays = sorted(
        eligible_top_plays,
        key=lambda recommendation: (
            recommendation.recommendation_score or 0.0,
            recommendation.model_probability,
            recommendation.edge,
            recommendation.ev,
        ),
        reverse=True,
    )
    top_plays = sorted_top_plays[:3]

    if len(top_plays) < 3:
        fallback_candidates = sorted(
            (recommendation for recommendation in game_recommendations if recommendation.player_id not in {pick.player_id for pick in top_plays}),
            key=lambda recommendation: (
                recommendation.recommendation_score or 0.0,
                recommendation.model_probability,
                recommendation.edge,
                recommendation.ev,
            ),
            reverse=True,
        )
        for recommendation in fallback_candidates:
            top_plays.append(recommendation)
            if len(top_plays) == 3:
                break

    strict_top_plays = [recommendation for recommendation in sorted_top_plays if _top_play_eligible(recommendation)]
    best_bet = strict_top_plays[0] if strict_top_plays else None
    return top_plays, best_bet


def _select_underdog_bucket(game_recommendations: list[Recommendation], best_bet: Recommendation | None) -> Recommendation | None:
    underdogs = [recommendation for recommendation in game_recommendations if _underdog_eligible(recommendation)]
    if not underdogs:
        return None

    min_probability = min(recommendation.model_probability for recommendation in underdogs)
    max_probability = max(recommendation.model_probability for recommendation in underdogs)
    min_edge = min(recommendation.edge for recommendation in underdogs)
    max_edge = max(recommendation.edge for recommendation in underdogs)
    min_ev = min(recommendation.ev for recommendation in underdogs)
    max_ev = max(recommendation.ev for recommendation in underdogs)
    min_odds = min(recommendation.market_odds for recommendation in underdogs)
    max_odds = max(recommendation.market_odds for recommendation in underdogs)

    scored = []
    for recommendation in underdogs:
        p_norm = _min_max_normalize(recommendation.model_probability, min_probability, max_probability)
        edge_norm = _min_max_normalize(recommendation.edge, min_edge, max_edge)
        ev_norm = _min_max_normalize(recommendation.ev, min_ev, max_ev)
        odds_norm = _min_max_normalize(float(recommendation.market_odds), float(min_odds), float(max_odds))
        underdog_score = (0.30 * p_norm) + (0.20 * edge_norm) + (0.30 * ev_norm) + (0.20 * odds_norm)
        scored.append((round(underdog_score, 4), recommendation))

    scored.sort(
        key=lambda item: (
            item[0],
            item[1].model_probability,
            item[1].edge,
            item[1].ev,
            item[1].market_odds,
        ),
        reverse=True,
    )

    if best_bet is not None:
        for _, recommendation in scored:
            if recommendation.player_id != best_bet.player_id:
                return recommendation
    return scored[0][1]


def _confidence_tag(ev: float, confidence_score: float) -> str:
    if ev >= 0.06 and confidence_score >= 0.65:
        return "high"
    if ev >= 0.03 and confidence_score >= 0.45:
        return "medium"
    return "watch"


def _recommendation_score(probability: float, edge: float, ev: float, market_odds: int, confidence_score: float) -> float:
    # Smoothly scale components to avoid hard top-end saturation from clipped
    # min/max bounds while still keeping the score interpretable in [0, 100].
    probability_component = _saturating_component(probability, half_saturation=0.14)
    ev_component = _saturating_component(ev, half_saturation=1.0)
    edge_component = _saturating_component(edge, half_saturation=0.18)
    value_component = (0.65 * ev_component) + (0.35 * edge_component)
    value_component *= _long_odds_value_dampener(probability=probability, market_odds=market_odds)
    combined = (
        (_SCORE_WEIGHTS["probability"] * probability_component)
        + (_SCORE_WEIGHTS["value"] * value_component)
        + (_SCORE_WEIGHTS["confidence"] * confidence_score)
    )
    return round(100 * combined, 4)


def _confidence_score(projection: PlayerProjectionCandidate, market_odds: int) -> float:
    history = projection.historical_production
    games_played = max(0.0, float(history.season_games_played or 0.0))
    shots_per_game = (float(history.season_total_shots or 0.0) / games_played) if games_played > 0 else 0.0
    first_goal_rate = (float(history.season_first_goals or 0.0) / games_played) if games_played > 0 else 0.0
    recent_5_first_goal_rate = (float(history.recent_5_first_goals or 0.0) / min(5.0, games_played)) if games_played > 0 else 0.0
    recent_10_first_goal_rate = (float(history.recent_10_first_goals or 0.0) / min(10.0, games_played)) if games_played > 0 else 0.0

    sample_score = _bounded_scale(games_played, floor=8.0, ceiling=65.0)
    process_score = _bounded_scale(shots_per_game, floor=0.8, ceiling=4.0)
    role_score = _bounded_scale(projection.model_probability, floor=0.01, ceiling=0.16)

    recent_spike = max(0.0, recent_5_first_goal_rate - first_goal_rate) + max(0.0, recent_10_first_goal_rate - first_goal_rate)
    recency_penalty = _bounded_scale(recent_spike, floor=0.0, ceiling=0.45)

    extreme_longshot_penalty = 0.0
    if market_odds >= 900 and projection.model_probability < 0.03:
        extreme_longshot_penalty = _bounded_scale(float(market_odds), floor=900.0, ceiling=2500.0)

    confidence = (
        (0.42 * sample_score)
        + (0.33 * process_score)
        + (0.25 * role_score)
        - (0.16 * recency_penalty)
        - (0.14 * extreme_longshot_penalty)
    )
    return max(0.05, min(0.99, confidence))


def _bounded_scale(value: float, floor: float, ceiling: float) -> float:
    if ceiling <= floor:
        return 0.0
    clipped = min(max(value, floor), ceiling)
    return (clipped - floor) / (ceiling - floor)


def _saturating_component(value: float, half_saturation: float) -> float:
    if value <= 0 or half_saturation <= 0:
        return 0.0
    return value / (value + half_saturation)


def _long_odds_value_dampener(probability: float, market_odds: int) -> float:
    if market_odds <= 1200:
        return 1.0
    odds_excess = max(0.0, float(market_odds - 1200))
    odds_scale = _saturating_component(odds_excess, half_saturation=1200.0)
    probability_weakness = _bounded_scale(0.22 - probability, floor=0.0, ceiling=0.12)
    penalty = 0.16 * odds_scale * probability_weakness
    return max(0.82, 1.0 - penalty)


def _debug_transparency_enabled() -> bool:
    return os.getenv("RECOMMENDATION_DEBUG_FIELDS", "").strip().lower() in {"1", "true", "yes", "on"}


def _build_model_debug_payload(
    projection: PlayerProjectionCandidate,
    fair_odds: int,
    edge: float,
    ev: float,
    confidence_score: float,
    recommendation_score: float,
) -> RecommendationModelDebug:
    features = _player_model_features(projection.historical_production)
    stable_baseline = (
        _DEFAULT_TEMPLATE.player_first_goal_weight * features.first_goals_per_game
        + _DEFAULT_TEMPLATE.player_total_goal_weight * features.goals_per_game
        + _DEFAULT_TEMPLATE.player_first_period_goal_weight * features.first_period_goals_per_game
        + _DEFAULT_TEMPLATE.player_first_period_shot_weight * features.first_period_shots_per_game
        + _DEFAULT_TEMPLATE.player_shots_per_game_weight * features.shots_per_game
    )
    process_weight = features.stability_score / max(_DEFAULT_TEMPLATE.recent_process_shrinkage_games / 60.0, 1.0)
    outcome_weight = features.stability_score / max(_DEFAULT_TEMPLATE.recent_outcome_shrinkage_games / 60.0, 1.0)
    recent_process_adjustment = _DEFAULT_TEMPLATE.player_recent_process_weight * process_weight * features.recent_process_form
    recent_outcome_adjustment = _DEFAULT_TEMPLATE.player_recent_outcome_weight * outcome_weight * features.recent_outcome_form
    stable_component = stable_baseline * features.offensive_tier_multiplier

    return RecommendationModelDebug(
        stable_baseline=round(stable_baseline, 6),
        offensive_tier_multiplier=round(features.offensive_tier_multiplier, 6),
        stable_component=round(stable_component, 6),
        recent_process_form=round(features.recent_process_form, 6),
        recent_outcome_form=round(features.recent_outcome_form, 6),
        recent_process_adjustment=round(recent_process_adjustment, 6),
        recent_outcome_adjustment=round(recent_outcome_adjustment, 6),
        model_probability=round(projection.model_probability, 6),
        fair_odds=fair_odds,
        edge=round(edge, 6),
        ev=round(ev, 6),
        confidence_score=round(confidence_score, 6),
        recommendation_score=round(recommendation_score, 6),
    )


def _event_start_delta_seconds(provider_start_time: datetime, canonical_start_time: datetime, local_timezone_name: str) -> int:
    """Best-event-time delta in seconds using UTC and configured local timezone clocks."""
    utc_delta = abs(int((canonical_start_time - provider_start_time).total_seconds()))
    try:
        local_zone = ZoneInfo(local_timezone_name)
    except Exception:
        return utc_delta

    provider_local = provider_start_time.astimezone(local_zone)
    canonical_local = canonical_start_time.astimezone(local_zone)
    local_delta = abs(int((canonical_local - provider_local).total_seconds()))
    return min(utc_delta, local_delta)


def _is_valid_matched_odds_row(row: NormalizedPlayerOdds) -> bool:
    if row.market_odds_american == 0 or is_stale(row.snapshot_at):
        return False
    if row.nhl_game_id is None or row.nhl_player_id is None:
        return False
    if row.event_mapping is None or row.player_mapping is None:
        return False
    if row.event_mapping.match_status != "matched":
        return False
    if row.player_mapping.match_status != "matched":
        return False
    return True
