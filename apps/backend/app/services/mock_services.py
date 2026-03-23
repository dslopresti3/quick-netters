from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import logging
import re

from app.services.projection_store import build_mock_projection_provider

from app.api.schemas import GameSummary, Recommendation, TeamProjectionLeader
from app.services.interfaces import (
    AvailabilityProvider,
    ScheduleProvider,
    OddsProvider,
    PlayerProjectionCandidate,
    ProjectionProvider,
    RecommendationsProvider,
)
from app.services.odds_provider import LiveOddsProvider
from app.services.odds import (
    NormalizedPlayerOdds,
    american_to_implied_probability,
    expected_value_per_unit,
    fair_american_odds,
    is_stale,
)

logger = logging.getLogger(__name__)


_RAW_NHL_TEAM_ALIASES = (
    ("Anaheim Ducks", "Anaheim", "Ducks", "ANA"),
    ("Boston Bruins", "Boston", "Bruins", "BOS"),
    ("Buffalo Sabres", "Buffalo", "Sabres", "BUF"),
    ("Calgary Flames", "Calgary", "Flames", "CGY"),
    ("Carolina Hurricanes", "Carolina", "Hurricanes", "Canes", "CAR"),
    ("Chicago Blackhawks", "Chicago", "Blackhawks", "Hawks", "CHI"),
    ("Colorado Avalanche", "Colorado", "Avalanche", "Avs", "COL"),
    ("Columbus Blue Jackets", "Columbus", "Blue Jackets", "Jackets", "CBJ"),
    ("Dallas Stars", "Dallas", "Stars", "DAL"),
    ("Detroit Red Wings", "Detroit", "Red Wings", "Wings", "DET"),
    ("Edmonton Oilers", "Edmonton", "Oilers", "EDM"),
    ("Florida Panthers", "Florida", "Panthers", "FLA"),
    ("Los Angeles Kings", "Los Angeles", "LA Kings", "Kings", "LAK"),
    ("Minnesota Wild", "Minnesota", "Wild", "MIN"),
    ("Montreal Canadiens", "Montreal", "Canadiens", "Habs", "MTL"),
    ("Nashville Predators", "Nashville", "Predators", "Preds", "NSH"),
    ("New Jersey Devils", "New Jersey", "NJ Devils", "Devils", "NJD"),
    ("New York Islanders", "NY Islanders", "New York Islanders", "Islanders", "NYI"),
    ("New York Rangers", "NY Rangers", "New York Rangers", "Rangers", "NYR"),
    ("Ottawa Senators", "Ottawa", "Senators", "Sens", "OTT"),
    ("Philadelphia Flyers", "Philadelphia", "Flyers", "PHI"),
    ("Pittsburgh Penguins", "Pittsburgh", "Penguins", "Pens", "PIT"),
    ("San Jose Sharks", "San Jose", "Sharks", "SJS"),
    ("Seattle Kraken", "Seattle", "Kraken", "SEA"),
    ("St. Louis Blues", "St Louis", "St. Louis", "Blues", "STL"),
    ("Tampa Bay Lightning", "Tampa Bay", "Lightning", "Bolts", "TBL"),
    ("Toronto Maple Leafs", "Toronto", "Maple Leafs", "Leafs", "TOR"),
    ("Utah Hockey Club", "Utah", "UTAH", "UTA"),
    ("Vancouver Canucks", "Vancouver", "Canucks", "VAN"),
    ("Vegas Golden Knights", "Vegas", "Golden Knights", "Knights", "VGK"),
    ("Washington Capitals", "Washington", "Capitals", "Caps", "WSH"),
    ("Winnipeg Jets", "Winnipeg", "Jets", "WPG"),
)


def _normalize_team_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


_TEAM_TOKEN_ALIASES: dict[str, set[str]] = {}
for alias_group in _RAW_NHL_TEAM_ALIASES:
    tokens = {_normalize_team_token(alias) for alias in alias_group if alias.strip()}
    for token in tokens:
        _TEAM_TOKEN_ALIASES.setdefault(token, set()).update(tokens)


def _team_alias_tokens(team_name: str) -> set[str]:
    normalized = _normalize_team_token(team_name)
    if not normalized:
        return set()
    return {normalized} | _TEAM_TOKEN_ALIASES.get(normalized, set())


class MockGamesService(ScheduleProvider):
    def __init__(self) -> None:
        self._cache: dict[date, list[GameSummary]] = {}

    def fetch(self, selected_date: date) -> list[GameSummary]:
        if selected_date in self._cache:
            return [game.model_copy(deep=True) for game in self._cache[selected_date]]

        self._cache[selected_date] = _build_games(selected_date)
        return [game.model_copy(deep=True) for game in self._cache[selected_date]]


class MockProjectionService(ProjectionProvider):
    """Mock provider that reads first-goal projections from a structured artifact store."""

    def __init__(self) -> None:
        self._provider = build_mock_projection_provider()

    def fetch_player_first_goal_projections(self, selected_date: date) -> list[PlayerProjectionCandidate]:
        if selected_date == date.today() + timedelta(days=1):
            return []
        return self._provider.fetch_player_first_goal_projections(selected_date)


class MockOddsService(OddsProvider):
    """Mock-mode wrapper around the live odds provider contract."""

    def __init__(self) -> None:
        self._provider = LiveOddsProvider()

    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        return self._provider.fetch_player_first_goal_odds(selected_date)


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
        snapshots = self._odds_provider.fetch_player_first_goal_odds(selected_date)
        return any(snapshot.market_odds_american != 0 for snapshot in snapshots)

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
                    for alias_token in _team_alias_tokens(team_name):
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
                team_aliases = _team_alias_tokens(projection_team_name)
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
        games_by_id = {game.game_id: game for game in scheduled_games}
        odds_snapshots = self._odds_provider.fetch_player_first_goal_odds(selected_date)
        projections = self._eligible_projection_candidates(selected_date, scheduled_games)

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
            game_team_lookup[game.game_id] = _team_alias_tokens(game.away_team) | _team_alias_tokens(game.home_team)

        eligible_rows: list[PlayerProjectionCandidate] = []
        for projection in projection_rows:
            if not projection.roster_eligibility.is_active_roster:
                continue

            team_tokens = _team_alias_tokens(projection.roster_eligibility.active_team_name)
            game_tokens = game_team_lookup.get(projection.game_id)
            if not team_tokens or game_tokens is None:
                continue
            if team_tokens.isdisjoint(game_tokens):
                continue
            eligible_rows.append(projection)

        return eligible_rows


def _build_games(selected_date: date) -> list[GameSummary]:
    if selected_date > date.today() + timedelta(days=1):
        return []

    return [
        GameSummary(
            game_id="g-nyr-vs-bos",
            game_time=datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc),
            away_team="NY Rangers",
            home_team="Boston Bruins",
        ),
        GameSummary(
            game_id="g-col-vs-dal",
            game_time=datetime.combine(selected_date + timedelta(days=1), time(0, 30), tzinfo=timezone.utc),
            away_team="Colorado Avalanche",
            home_team="Dallas Stars",
        ),
        GameSummary(
            game_id="g-lak-vs-vgk",
            game_time=datetime.combine(selected_date + timedelta(days=1), time(3, 0), tzinfo=timezone.utc),
            away_team="LA Kings",
            home_team="Vegas Golden Knights",
        ),
    ]


def _latest_snapshot_for_player(
    snapshots: list[NormalizedPlayerOdds], game_id: str, player_id: str
) -> NormalizedPlayerOdds | None:
    candidates = [snapshot for snapshot in snapshots if snapshot.game_id == game_id and snapshot.player_id == player_id]
    if not candidates:
        return None
    return max(candidates, key=lambda snapshot: snapshot.snapshot_at)


def _confidence_tag(ev: float) -> str:
    if ev >= 0.06:
        return "high"
    if ev >= 0.03:
        return "medium"
    return "watch"




class MockRecommendationsService(ValueRecommendationService):
    def __init__(self) -> None:
        schedule_provider = MockGamesService()
        projection_provider = MockProjectionService()
        odds_provider = MockOddsService()
        super().__init__(schedule_provider=schedule_provider, projection_provider=projection_provider, odds_provider=odds_provider)
