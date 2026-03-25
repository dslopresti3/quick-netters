from datetime import date, datetime, time, timedelta, timezone
import os

from app.api.schemas import GameSummary
from app.services.interfaces import (
    OddsProvider,
    PlayerHistoricalProduction,
    PlayerProjectionCandidate,
    PlayerRosterEligibility,
    ProjectionProvider,
    ScheduleProvider,
)
from app.services.recommendation_service import ValueRecommendationService
from app.services.odds import NormalizedPlayerOdds


class StaticScheduleProvider(ScheduleProvider):
    def __init__(self, games: list[GameSummary]) -> None:
        self._games = games

    def fetch(self, selected_date: date) -> list[GameSummary]:
        return [game.model_copy(deep=True) for game in self._games]


class StaticProjectionProvider(ProjectionProvider):
    def __init__(self, rows: list[PlayerProjectionCandidate]) -> None:
        self._rows = rows

    def fetch_player_first_goal_projections(self, selected_date: date) -> list[PlayerProjectionCandidate]:
        return list(self._rows)


class StaticOddsProvider(OddsProvider):
    def __init__(self, rows: list[NormalizedPlayerOdds]) -> None:
        self._rows = rows

    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        return list(self._rows)


class RecordingProjectionProvider(ProjectionProvider):
    def __init__(self, rows: list[PlayerProjectionCandidate], calls: list[str]) -> None:
        self._rows = rows
        self._calls = calls

    def fetch_player_first_goal_projections(self, selected_date: date) -> list[PlayerProjectionCandidate]:
        self._calls.append("projections")
        return list(self._rows)


class RecordingOddsProvider(OddsProvider):
    def __init__(self, rows: list[NormalizedPlayerOdds], calls: list[str]) -> None:
        self._rows = rows
        self._calls = calls

    def fetch_player_first_goal_odds(self, selected_date: date) -> list[NormalizedPlayerOdds]:
        self._calls.append("odds")
        return list(self._rows)


def _projection(
    game_id: str,
    player_id: str,
    name: str,
    projected_team: str,
    active_team: str,
    active: bool = True,
    model_probability: float = 0.22,
) -> PlayerProjectionCandidate:
    return PlayerProjectionCandidate(
        game_id=game_id,
        nhl_player_id=player_id,
        player_name=name,
        projected_team_name=projected_team,
        model_probability=model_probability,
        historical_production=PlayerHistoricalProduction(season_first_goals=2, season_games_played=50),
        roster_eligibility=PlayerRosterEligibility(active_team_name=active_team, is_active_roster=active),
    )


def _raw_odds(name: str, away: str, home: str, start_time: datetime, *, team: str | None = None, event_id: str = "evt-1") -> NormalizedPlayerOdds:
    return NormalizedPlayerOdds(
        nhl_game_id=None,
        nhl_player_id=None,
        market_odds_american=400,
        snapshot_at=start_time - timedelta(minutes=5),
        provider_name="the-odds-api",
        provider_event_id=event_id,
        provider_player_name_raw=name,
        provider_team_raw=team,
        away_team_raw=away,
        home_team_raw=home,
        provider_start_time=start_time,
        freshness_status="fresh",
        is_fresh=True,
    )


def test_game_mapping_by_team_and_time_drives_odds_available() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026020001", game_time=game_time, away_team="NY Rangers", home_team="Boston Bruins")
    projections = [_projection("2026020001", "847123", "Artemi Panarin", "NY Rangers", "NY Rangers")]
    odds_rows = [_raw_odds("Artemi Panarin", "New York Rangers", "Boston", game_time + timedelta(minutes=10), team="NY Rangers")]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    assert service.odds_available(selected_date) is True


def test_player_mapping_by_team_and_name_aliases() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026020001", game_time=game_time, away_team="NY Rangers", home_team="Boston Bruins")
    projections = [_projection("2026020001", "847123", "Artemi Panarin", "NY Rangers", "NY Rangers")]
    odds_rows = [_raw_odds("A. Panarín", "NY Rangers", "Boston Bruins", game_time, team="Rangers")]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    recs = service.fetch_daily(selected_date)
    assert len(recs) == 1
    assert recs[0].player_id == "847123"


def test_player_mapping_supports_last_first_book_format_with_team_suffix() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026021001", game_time=game_time, away_team="Toronto Maple Leafs", home_team="Florida Panthers")
    projections = [_projection("2026021001", "8479318", "Auston Matthews", "Toronto Maple Leafs", "Toronto Maple Leafs")]
    odds_rows = [_raw_odds("Matthews, Auston (TOR)", "Toronto Maple Leafs", "Florida Panthers", game_time, team="Toronto")]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    recs = service.fetch_daily(selected_date)
    assert len(recs) == 1
    assert recs[0].player_id == "8479318"


def test_player_mapping_supports_market_suffix_embedded_in_bookmaker_name() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026021007", game_time=game_time, away_team="Edmonton Oilers", home_team="Calgary Flames")
    projections = [_projection("2026021007", "8478402", "Connor McDavid", "Edmonton Oilers", "Edmonton Oilers")]
    odds_rows = [_raw_odds("Connor McDavid - To Score First Goal", "Edmonton Oilers", "Calgary Flames", game_time, team="Edmonton")]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    recs = service.fetch_daily(selected_date)
    assert len(recs) == 1
    assert recs[0].player_id == "8478402"


def test_player_mapping_supports_punctuation_differences() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026021002", game_time=game_time, away_team="Boston Bruins", home_team="NY Rangers")
    projections = [_projection("2026021002", "player-smith-jones", "Jake Smith-Jones", "Boston Bruins", "Boston Bruins")]
    odds_rows = [_raw_odds("J. Smith Jones", "Boston Bruins", "NY Rangers", game_time, team="Boston")]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    recs = service.fetch_daily(selected_date)
    assert len(recs) == 1
    assert recs[0].player_id == "player-smith-jones"


def test_player_mapping_uses_team_context_to_disambiguate_shared_name_aliases() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026021003", game_time=game_time, away_team="Carolina Hurricanes", home_team="NY Islanders")
    projections = [
        _projection("2026021003", "car-sebastian-aho", "Sebastian Aho", "Carolina Hurricanes", "Carolina Hurricanes"),
        _projection("2026021003", "nyi-sebastian-aho", "Sebastian Aho", "NY Islanders", "NY Islanders"),
    ]
    odds_rows = [_raw_odds("S. Aho", "Carolina Hurricanes", "NY Islanders", game_time, team="Carolina")]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    recs = service.fetch_daily(selected_date)
    assert len(recs) == 1
    assert recs[0].player_id == "car-sebastian-aho"


def test_player_mapping_prefers_best_alias_match_from_full_game_candidate_pool() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026021010", game_time=game_time, away_team="Washington Capitals", home_team="Boston Bruins")
    projections = [
        _projection("2026021010", "wash-jake-guentzel", "Jake Guentzel", "Washington Capitals", "Washington Capitals"),
        _projection("2026021010", "wash-john-carlson", "John Carlson", "Washington Capitals", "Washington Capitals"),
        _projection("2026021010", "bos-jake-debrusk", "Jake DeBrusk", "Boston Bruins", "Boston Bruins"),
    ]
    odds_rows = [_raw_odds("Jake Guentzel", "Washington Capitals", "Boston Bruins", game_time, team="Washington")]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    recs = service.fetch_daily(selected_date)
    assert len(recs) == 1
    assert recs[0].player_id == "wash-jake-guentzel"


def test_player_mapping_ignores_non_team_bookmaker_description_context() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026021004", game_time=game_time, away_team="NY Rangers", home_team="Boston Bruins")
    projections = [_projection("2026021004", "847123", "Artemi Panarin", "NY Rangers", "NY Rangers")]
    # Live books sometimes use non-team metadata in description for first-goal markets.
    odds_rows = [_raw_odds("Artemi Panarin", "NY Rangers", "Boston Bruins", game_time, team="Any Other Player")]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    recs = service.fetch_daily(selected_date)
    assert len(recs) == 1
    assert recs[0].player_id == "847123"


def test_player_mapping_uses_full_projection_candidate_pool_per_matched_game() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026021005", game_time=game_time, away_team="Dallas Stars", home_team="Colorado Avalanche")
    projections = [
        _projection("2026021005", "top-player", "Top Shooter", "Dallas Stars", "Dallas Stars", model_probability=0.31),
        _projection("2026021005", "depth-player", "Depth Finisher", "Dallas Stars", "Dallas Stars", model_probability=0.24),
        _projection("2026021005", "opp-player", "Opponent Sniper", "Colorado Avalanche", "Colorado Avalanche", model_probability=0.26),
    ]
    odds_rows = [_raw_odds("Depth Finisher", "Dallas Stars", "Colorado Avalanche", game_time, team="Dallas")]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    recs = service.fetch_daily(selected_date)
    assert len(recs) == 1
    assert recs[0].player_id == "depth-player"


def test_active_roster_only_eligibility_and_traded_player_behavior() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026020001", game_time=game_time, away_team="Colorado Avalanche", home_team="Dallas Stars")
    projections = [
        _projection("2026020001", "player-traded", "Mikko Rantanen", "Colorado Avalanche", "Dallas Stars", active=True),
        _projection("2026020001", "player-inactive", "Depth Skater", "Colorado Avalanche", "Colorado Avalanche", active=False),
    ]
    odds_rows = [
        _raw_odds("Mikko Rantanen", "Colorado", "Dallas", game_time, team="Dallas"),
        _raw_odds("Depth Skater", "Colorado", "Dallas", game_time, team="Colorado", event_id="evt-2"),
    ]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    recs = service.fetch_daily(selected_date)
    assert len(recs) == 1
    assert recs[0].player_id == "player-traded"


def test_unmatched_odds_rows_and_stale_rows_are_excluded_without_breaking_response() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026020001", game_time=game_time, away_team="NY Rangers", home_team="Boston Bruins")
    projections = [_projection("2026020001", "847123", "Artemi Panarin", "NY Rangers", "NY Rangers")]
    odds_rows = [
        _raw_odds("Artemi Panarin", "Wrong Team", "Also Wrong", game_time, team="Rangers"),
        NormalizedPlayerOdds(
            nhl_game_id=None,
            nhl_player_id=None,
            market_odds_american=400,
            snapshot_at=game_time - timedelta(minutes=10),
            provider_name="the-odds-api",
            provider_event_id="evt-malformed",
            provider_player_name_raw=None,
            provider_team_raw="NY Rangers",
            away_team_raw="NY Rangers",
            home_team_raw="Boston Bruins",
            provider_start_time=game_time,
            freshness_status="fresh",
            is_fresh=True,
        ),
        NormalizedPlayerOdds(
            nhl_game_id=None,
            nhl_player_id=None,
            market_odds_american=400,
            snapshot_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            provider_name="the-odds-api",
            provider_event_id="evt-stale",
            provider_player_name_raw="Artemi Panarin",
            provider_team_raw="NY Rangers",
            away_team_raw="NY Rangers",
            home_team_raw="Boston Bruins",
            provider_start_time=game_time,
            freshness_status="stale",
            is_fresh=False,
        ),
    ]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    assert service.fetch_daily(selected_date) == []
    assert service.odds_available(selected_date) is False


def test_odds_mapping_does_not_require_provider_ids_to_equal_nhl_ids() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026020001", game_time=game_time, away_team="NY Rangers", home_team="Boston Bruins")
    projections = [_projection("2026020001", "847123", "Artemi Panarin", "NY Rangers", "NY Rangers")]
    odds_rows = [
        NormalizedPlayerOdds(
            nhl_game_id=None,
            nhl_player_id=None,
            market_odds_american=400,
            snapshot_at=game_time - timedelta(minutes=3),
            provider_name="the-odds-api",
            provider_event_id="provider-event-999",
            provider_player_id="provider-player-xyz",
            provider_player_name_raw="Artemi Panarin",
            provider_team_raw="New York Rangers",
            away_team_raw="New York Rangers",
            home_team_raw="Boston Bruins",
            provider_start_time=game_time + timedelta(minutes=5),
            freshness_status="fresh",
            is_fresh=True,
        )
    ]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    recs = service.fetch_daily(selected_date)
    assert len(recs) == 1
    assert recs[0].game_id == "2026020001"
    assert recs[0].player_id == "847123"


def test_team_alias_mapping_is_populated_before_event_match_for_utah_rename() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026020002", game_time=game_time, away_team="Utah Mammoth", home_team="Boston Bruins")
    projections = [_projection("2026020002", "847999", "Clayton Keller", "Utah Mammoth", "Utah Mammoth")]
    odds_rows = [_raw_odds("Clayton Keller", "Utah Hockey Club", "Boston Bruins", game_time, team="Utah")]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    assert service.odds_available(selected_date) is True


def test_recommendations_fetch_projections_before_odds_and_require_projections_first() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026020001", game_time=game_time, away_team="NY Rangers", home_team="Boston Bruins")
    calls: list[str] = []
    projections = [_projection("2026020001", "847123", "Artemi Panarin", "NY Rangers", "NY Rangers")]
    odds_rows = [_raw_odds("Artemi Panarin", "NY Rangers", "Boston Bruins", game_time, team="NY Rangers")]
    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=RecordingProjectionProvider(projections, calls=calls),
        odds_provider=RecordingOddsProvider(odds_rows, calls=calls),
    )

    recs = service.fetch_daily(selected_date)

    assert recs
    assert calls == ["projections", "odds"]


def test_recommendations_do_not_pull_odds_when_no_projections_exist() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026020001", game_time=game_time, away_team="NY Rangers", home_team="Boston Bruins")
    calls: list[str] = []
    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=RecordingProjectionProvider([], calls=calls),
        odds_provider=RecordingOddsProvider([_raw_odds("Artemi Panarin", "NY Rangers", "Boston Bruins", game_time)], calls=calls),
    )

    recs = service.fetch_daily(selected_date)

    assert recs == []
    assert calls == ["projections"]


def test_recommendation_fields_include_implied_probability_fair_odds_edge_and_ev() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026020001", game_time=game_time, away_team="NY Rangers", home_team="Boston Bruins")
    projection = PlayerProjectionCandidate(
        game_id="2026020001",
        nhl_player_id="847123",
        player_name="Artemi Panarin",
        projected_team_name="NY Rangers",
        model_probability=0.22,
        historical_production=PlayerHistoricalProduction(season_first_goals=2, season_games_played=50),
        roster_eligibility=PlayerRosterEligibility(active_team_name="NY Rangers", is_active_roster=True),
    )
    odds_rows = [_raw_odds("Artemi Panarin", "NY Rangers", "Boston Bruins", game_time, team="NY Rangers")]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider([projection]),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    recs = service.fetch_daily(selected_date)

    assert len(recs) == 1
    rec = recs[0]
    assert rec.implied_probability == 0.2
    assert rec.decimal_odds == 5.0
    assert rec.fair_odds == 355
    assert rec.edge == 0.02
    assert rec.ev == 0.1
    assert rec.confidence_score is not None
    assert rec.recommendation_score is not None


def test_game_bucket_selection_uses_blended_play_score_for_top_plays_and_best_bet() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026020401", game_time=game_time, away_team="NY Rangers", home_team="Boston Bruins")
    projections = [
        _projection("2026020401", "p1", "Player One", "NY Rangers", "NY Rangers", model_probability=0.12),
        _projection("2026020401", "p2", "Player Two", "NY Rangers", "NY Rangers", model_probability=0.09),
        _projection("2026020401", "p3", "Player Three", "NY Rangers", "NY Rangers", model_probability=0.07),
        _projection("2026020401", "p4", "Player Four", "NY Rangers", "NY Rangers", model_probability=0.03),
    ]
    odds_rows = [
        NormalizedPlayerOdds(
            nhl_game_id="2026020401",
            nhl_player_id="p1",
            market_odds_american=1100,
            snapshot_at=game_time - timedelta(minutes=2),
            provider_name="test",
            provider_event_id="evt-p1",
            provider_player_name_raw="Player One",
            provider_team_raw="NY Rangers",
            away_team_raw="NY Rangers",
            home_team_raw="Boston Bruins",
            provider_start_time=game_time,
            freshness_status="fresh",
            is_fresh=True,
            event_mapping=None,
            player_mapping=None,
        ),
        NormalizedPlayerOdds(
            nhl_game_id="2026020401",
            nhl_player_id="p2",
            market_odds_american=1300,
            snapshot_at=game_time - timedelta(minutes=2),
            provider_name="test",
            provider_event_id="evt-p2",
            provider_player_name_raw="Player Two",
            provider_team_raw="NY Rangers",
            away_team_raw="NY Rangers",
            home_team_raw="Boston Bruins",
            provider_start_time=game_time,
            freshness_status="fresh",
            is_fresh=True,
            event_mapping=None,
            player_mapping=None,
        ),
        NormalizedPlayerOdds(
            nhl_game_id="2026020401",
            nhl_player_id="p3",
            market_odds_american=1900,
            snapshot_at=game_time - timedelta(minutes=2),
            provider_name="test",
            provider_event_id="evt-p3",
            provider_player_name_raw="Player Three",
            provider_team_raw="NY Rangers",
            away_team_raw="NY Rangers",
            home_team_raw="Boston Bruins",
            provider_start_time=game_time,
            freshness_status="fresh",
            is_fresh=True,
            event_mapping=None,
            player_mapping=None,
        ),
        NormalizedPlayerOdds(
            nhl_game_id="2026020401",
            nhl_player_id="p4",
            market_odds_american=2500,
            snapshot_at=game_time - timedelta(minutes=2),
            provider_name="test",
            provider_event_id="evt-p4",
            provider_player_name_raw="Player Four",
            provider_team_raw="NY Rangers",
            away_team_raw="NY Rangers",
            home_team_raw="Boston Bruins",
            provider_start_time=game_time,
            freshness_status="fresh",
            is_fresh=True,
            event_mapping=None,
            player_mapping=None,
        ),
    ]
    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    top_plays, best_bet, underdog = service.fetch_game_recommendation_buckets(selected_date, "2026020401")

    assert [recommendation.player_id for recommendation in top_plays] == ["p1", "p3", "p2"]
    assert top_plays[0].recommendation_score == 1.0
    assert best_bet is not None
    assert best_bet.player_id == "p1"
    assert underdog is not None
    assert underdog.player_id == "p3"


def test_underdog_bucket_returns_none_when_no_candidate_qualifies() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026020402", game_time=game_time, away_team="NY Rangers", home_team="Boston Bruins")
    projections = [_projection("2026020402", "p1", "Player One", "NY Rangers", "NY Rangers", model_probability=0.05)]
    odds_rows = [
        NormalizedPlayerOdds(
            nhl_game_id="2026020402",
            nhl_player_id="p1",
            market_odds_american=1400,
            snapshot_at=game_time - timedelta(minutes=2),
            provider_name="test",
            provider_event_id="evt-p1",
            provider_player_name_raw="Player One",
            provider_team_raw="NY Rangers",
            away_team_raw="NY Rangers",
            home_team_raw="Boston Bruins",
            provider_start_time=game_time,
            freshness_status="fresh",
            is_fresh=True,
            event_mapping=None,
            player_mapping=None,
        ),
    ]
    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    _, _, underdog = service.fetch_game_recommendation_buckets(selected_date, "2026020402")

    assert underdog is None


def test_recommendation_ranking_balances_probability_value_and_confidence() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026020101", game_time=game_time, away_team="NY Rangers", home_team="Boston Bruins")
    projections = [
        PlayerProjectionCandidate(
            game_id="2026020101",
            nhl_player_id="stable-topline",
            player_name="Stable Topline",
            projected_team_name="NY Rangers",
            model_probability=0.12,
            historical_production=PlayerHistoricalProduction(
                season_first_goals=6,
                season_games_played=72,
                season_total_shots=235,
                recent_5_first_goals=1,
                recent_10_first_goals=1,
            ),
            roster_eligibility=PlayerRosterEligibility(active_team_name="NY Rangers", is_active_roster=True),
        ),
        PlayerProjectionCandidate(
            game_id="2026020101",
            nhl_player_id="fringe-longshot",
            player_name="Fringe Longshot",
            projected_team_name="NY Rangers",
            model_probability=0.02,
            historical_production=PlayerHistoricalProduction(
                season_first_goals=1,
                season_games_played=12,
                season_total_shots=10,
                recent_5_first_goals=1,
                recent_10_first_goals=1,
            ),
            roster_eligibility=PlayerRosterEligibility(active_team_name="NY Rangers", is_active_roster=True),
        ),
    ]
    odds_rows = [
        NormalizedPlayerOdds(
            nhl_game_id="2026020101",
            nhl_player_id="stable-topline",
            market_odds_american=900,
            snapshot_at=game_time - timedelta(minutes=5),
            provider_name="test",
            provider_event_id="evt-1",
            provider_player_name_raw="Stable Topline",
            provider_team_raw="NY Rangers",
            away_team_raw="NY Rangers",
            home_team_raw="Boston Bruins",
            provider_start_time=game_time,
            freshness_status="fresh",
            is_fresh=True,
            event_mapping=None,
            player_mapping=None,
        ),
        NormalizedPlayerOdds(
            nhl_game_id="2026020101",
            nhl_player_id="fringe-longshot",
            market_odds_american=7000,
            snapshot_at=game_time - timedelta(minutes=5),
            provider_name="test",
            provider_event_id="evt-2",
            provider_player_name_raw="Fringe Longshot",
            provider_team_raw="NY Rangers",
            away_team_raw="NY Rangers",
            home_team_raw="Boston Bruins",
            provider_start_time=game_time,
            freshness_status="fresh",
            is_fresh=True,
            event_mapping=None,
            player_mapping=None,
        ),
    ]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    recs = service.fetch_daily(selected_date)

    assert len(recs) == 2
    assert recs[0].player_id == "stable-topline"
    assert (recs[0].recommendation_score or 0) >= (recs[1].recommendation_score or 0)


def test_event_mapping_matches_when_provider_start_time_has_non_utc_offset() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    provider_local_start = datetime.combine(selected_date, time(18, 0), tzinfo=timezone(timedelta(hours=-5)))
    game = GameSummary(game_id="2026020001", game_time=game_time, away_team="NY Rangers", home_team="Boston Bruins")
    projections = [_projection("2026020001", "847123", "Artemi Panarin", "NY Rangers", "NY Rangers")]
    odds_rows = [_raw_odds("Artemi Panarin", "NY Rangers", "Boston Bruins", provider_local_start, team="NY Rangers")]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )

    assert service.odds_available(selected_date) is True


def test_debug_transparency_fields_are_populated_and_stable_component_dominates() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026020201", game_time=game_time, away_team="NY Rangers", home_team="Boston Bruins")
    projection = PlayerProjectionCandidate(
        game_id="2026020201",
        nhl_player_id="847123",
        player_name="Artemi Panarin",
        projected_team_name="NY Rangers",
        model_probability=0.22,
        historical_production=PlayerHistoricalProduction(
            season_first_goals=7,
            season_games_played=70,
            season_total_goals=35,
            season_total_shots=220,
            recent_5_total_shots=20,
            recent_10_total_shots=35,
            recent_5_first_goals=1,
            recent_10_first_goals=1,
        ),
        roster_eligibility=PlayerRosterEligibility(active_team_name="NY Rangers", is_active_roster=True),
    )
    odds_rows = [_raw_odds("Artemi Panarin", "NY Rangers", "Boston Bruins", game_time, team="NY Rangers")]
    previous = os.environ.get("RECOMMENDATION_DEBUG_FIELDS")
    os.environ["RECOMMENDATION_DEBUG_FIELDS"] = "1"
    try:
        service = ValueRecommendationService(
            schedule_provider=StaticScheduleProvider([game]),
            projection_provider=StaticProjectionProvider([projection]),
            odds_provider=StaticOddsProvider(odds_rows),
        )
        recs = service.fetch_daily(selected_date)
    finally:
        if previous is None:
            os.environ.pop("RECOMMENDATION_DEBUG_FIELDS", None)
        else:
            os.environ["RECOMMENDATION_DEBUG_FIELDS"] = previous

    assert len(recs) == 1
    debug = recs[0].model_debug
    assert debug is not None
    assert debug.stable_baseline > 0
    assert debug.stable_component > 0
    assert debug.recent_process_adjustment >= 0
    assert debug.recent_outcome_adjustment >= 0
    assert debug.stable_component > (debug.recent_process_adjustment + debug.recent_outcome_adjustment)


def test_recommendation_score_does_not_flatten_top_plays_into_ties() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026020301", game_time=game_time, away_team="NY Rangers", home_team="Boston Bruins")
    projections = [
        PlayerProjectionCandidate(
            game_id="2026020301",
            nhl_player_id="elite-star",
            player_name="Elite Star",
            projected_team_name="NY Rangers",
            model_probability=0.34,
            historical_production=PlayerHistoricalProduction(season_first_goals=10, season_games_played=75, season_total_shots=260),
            roster_eligibility=PlayerRosterEligibility(active_team_name="NY Rangers", is_active_roster=True),
        ),
        PlayerProjectionCandidate(
            game_id="2026020301",
            nhl_player_id="value-winger",
            player_name="Value Winger",
            projected_team_name="NY Rangers",
            model_probability=0.23,
            historical_production=PlayerHistoricalProduction(season_first_goals=6, season_games_played=75, season_total_shots=200),
            roster_eligibility=PlayerRosterEligibility(active_team_name="NY Rangers", is_active_roster=True),
        ),
    ]
    odds_rows = [
        NormalizedPlayerOdds(
            nhl_game_id="2026020301",
            nhl_player_id="elite-star",
            market_odds_american=900,
            snapshot_at=game_time - timedelta(minutes=3),
            provider_name="test",
            provider_event_id="evt-elite",
            provider_player_name_raw="Elite Star",
            provider_team_raw="NY Rangers",
            away_team_raw="NY Rangers",
            home_team_raw="Boston Bruins",
            provider_start_time=game_time,
            freshness_status="fresh",
            is_fresh=True,
            event_mapping=None,
            player_mapping=None,
        ),
        NormalizedPlayerOdds(
            nhl_game_id="2026020301",
            nhl_player_id="value-winger",
            market_odds_american=1700,
            snapshot_at=game_time - timedelta(minutes=3),
            provider_name="test",
            provider_event_id="evt-value",
            provider_player_name_raw="Value Winger",
            provider_team_raw="NY Rangers",
            away_team_raw="NY Rangers",
            home_team_raw="Boston Bruins",
            provider_start_time=game_time,
            freshness_status="fresh",
            is_fresh=True,
            event_mapping=None,
            player_mapping=None,
        ),
    ]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )
    recs = service.fetch_daily(selected_date)

    assert len(recs) == 2
    assert recs[0].recommendation_score != recs[1].recommendation_score


def test_long_odds_value_is_mildly_dampened_when_probability_is_weaker() -> None:
    selected_date = date.today()
    game_time = datetime.combine(selected_date, time(23, 0), tzinfo=timezone.utc)
    game = GameSummary(game_id="2026020302", game_time=game_time, away_team="NY Rangers", home_team="Boston Bruins")
    projections = [
        PlayerProjectionCandidate(
            game_id="2026020302",
            nhl_player_id="high-prob",
            player_name="High Prob Star",
            projected_team_name="NY Rangers",
            model_probability=0.29,
            historical_production=PlayerHistoricalProduction(season_first_goals=9, season_games_played=75, season_total_shots=240),
            roster_eligibility=PlayerRosterEligibility(active_team_name="NY Rangers", is_active_roster=True),
        ),
        PlayerProjectionCandidate(
            game_id="2026020302",
            nhl_player_id="long-odds",
            player_name="Long Odds Winger",
            projected_team_name="NY Rangers",
            model_probability=0.17,
            historical_production=PlayerHistoricalProduction(season_first_goals=5, season_games_played=75, season_total_shots=170),
            roster_eligibility=PlayerRosterEligibility(active_team_name="NY Rangers", is_active_roster=True),
        ),
    ]
    odds_rows = [
        NormalizedPlayerOdds(
            nhl_game_id="2026020302",
            nhl_player_id="high-prob",
            market_odds_american=900,
            snapshot_at=game_time - timedelta(minutes=2),
            provider_name="test",
            provider_event_id="evt-high-prob",
            provider_player_name_raw="High Prob Star",
            provider_team_raw="NY Rangers",
            away_team_raw="NY Rangers",
            home_team_raw="Boston Bruins",
            provider_start_time=game_time,
            freshness_status="fresh",
            is_fresh=True,
            event_mapping=None,
            player_mapping=None,
        ),
        NormalizedPlayerOdds(
            nhl_game_id="2026020302",
            nhl_player_id="long-odds",
            market_odds_american=2200,
            snapshot_at=game_time - timedelta(minutes=2),
            provider_name="test",
            provider_event_id="evt-long-odds",
            provider_player_name_raw="Long Odds Winger",
            provider_team_raw="NY Rangers",
            away_team_raw="NY Rangers",
            home_team_raw="Boston Bruins",
            provider_start_time=game_time,
            freshness_status="fresh",
            is_fresh=True,
            event_mapping=None,
            player_mapping=None,
        ),
    ]

    service = ValueRecommendationService(
        schedule_provider=StaticScheduleProvider([game]),
        projection_provider=StaticProjectionProvider(projections),
        odds_provider=StaticOddsProvider(odds_rows),
    )
    recs = service.fetch_daily(selected_date)
    by_id = {r.player_id: r for r in recs}

    assert by_id["high-prob"].recommendation_score is not None
    assert by_id["long-odds"].recommendation_score is not None
    assert by_id["long-odds"].recommendation_score > by_id["high-prob"].recommendation_score
