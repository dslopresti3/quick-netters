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
from app.services.mock_services import ValueRecommendationService
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


def _projection(game_id: str, player_id: str, name: str, projected_team: str, active_team: str, active: bool = True) -> PlayerProjectionCandidate:
    return PlayerProjectionCandidate(
        game_id=game_id,
        nhl_player_id=player_id,
        player_name=name,
        projected_team_name=projected_team,
        model_probability=0.22,
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
