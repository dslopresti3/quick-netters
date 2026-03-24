from datetime import date, datetime, time, timedelta, timezone

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
    assert rec.fair_odds == 355
    assert rec.edge == 0.02
    assert rec.ev == 0.1


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
