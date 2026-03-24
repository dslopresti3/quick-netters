import json
from datetime import date, datetime, timezone

from app.api.routes import get_games
from app.api.schemas import GameSummary
from app.services.dev_projection_provider import ActiveRosterRepository, AutoGeneratingProjectionProvider
from app.services.interfaces import ScheduleProvider
from app.services.mock_services import ValueRecommendationService
from app.services.provider_wiring import ProviderRegistry
from app.services.real_services import EmptyOddsProvider


class _StaticScheduleProvider(ScheduleProvider):
    def __init__(self, games_by_date: dict[date, list[GameSummary]]) -> None:
        self._games_by_date = games_by_date

    def fetch(self, selected_date: date) -> list[GameSummary]:
        return [game.model_copy(deep=True) for game in self._games_by_date.get(selected_date, [])]


def _build_registry(artifact_path, schedule_provider: ScheduleProvider, roster_path) -> ProviderRegistry:
    projection_provider = AutoGeneratingProjectionProvider(
        schedule_provider=schedule_provider,
        artifact_path=artifact_path,
        roster_repository=ActiveRosterRepository(roster_path=roster_path),
    )
    odds_provider = EmptyOddsProvider()
    return ProviderRegistry(
        schedule_provider=schedule_provider,
        projection_provider=projection_provider,
        odds_provider=odds_provider,
        recommendation_service=ValueRecommendationService(
            schedule_provider=schedule_provider,
            projection_provider=projection_provider,
            odds_provider=odds_provider,
        ),
    )


def test_get_games_returns_generated_projections_for_2026_03_24_and_2026_03_25(tmp_path) -> None:
    artifact = tmp_path / "projections.json"
    artifact.write_text(json.dumps({"schema_version": 1, "projections": []}), encoding="utf-8")
    schedule_provider = _StaticScheduleProvider(
        {
            date(2026, 3, 24): [
                GameSummary(
                    game_id="2026032401",
                    game_time=datetime(2026, 3, 24, 23, 0, tzinfo=timezone.utc),
                    away_team="NY Rangers",
                    home_team="Boston Bruins",
                )
            ],
            date(2026, 3, 25): [
                GameSummary(
                    game_id="2026032501",
                    game_time=datetime(2026, 3, 25, 23, 0, tzinfo=timezone.utc),
                    away_team="Colorado Avalanche",
                    home_team="Dallas Stars",
                )
            ],
        }
    )
    roster_path = tmp_path / "rosters.json"
    roster_path.write_text(json.dumps({"players": [
        {"player_id": "8479323", "player_name": "Artemi Panarin", "active_team_name": "NY Rangers", "is_active_roster": True, "historical_season_first_goals": 8, "historical_season_games_played": 82},
        {"player_id": "8476459", "player_name": "Mika Zibanejad", "active_team_name": "NY Rangers", "is_active_roster": True, "historical_season_first_goals": 7, "historical_season_games_played": 81},
        {"player_id": "8475184", "player_name": "Chris Kreider", "active_team_name": "NY Rangers", "is_active_roster": True, "historical_season_first_goals": 6, "historical_season_games_played": 80},
        {"player_id": "8477956", "player_name": "David Pastrnak", "active_team_name": "Boston Bruins", "is_active_roster": True, "historical_season_first_goals": 9, "historical_season_games_played": 82},
        {"player_id": "8473419", "player_name": "Brad Marchand", "active_team_name": "Boston Bruins", "is_active_roster": True, "historical_season_first_goals": 6, "historical_season_games_played": 78},
        {"player_id": "8482089", "player_name": "Pavel Zacha", "active_team_name": "Boston Bruins", "is_active_roster": True, "historical_season_first_goals": 4, "historical_season_games_played": 80},
        {"player_id": "8477492", "player_name": "Nathan MacKinnon", "active_team_name": "Colorado Avalanche", "is_active_roster": True, "historical_season_first_goals": 8, "historical_season_games_played": 82},
        {"player_id": "8476455", "player_name": "Cale Makar", "active_team_name": "Colorado Avalanche", "is_active_roster": True, "historical_season_first_goals": 5, "historical_season_games_played": 79},
        {"player_id": "8478402", "player_name": "Jason Robertson", "active_team_name": "Dallas Stars", "is_active_roster": True, "historical_season_first_goals": 6, "historical_season_games_played": 81},
        {"player_id": "8476462", "player_name": "Roope Hintz", "active_team_name": "Dallas Stars", "is_active_roster": True, "historical_season_first_goals": 5, "historical_season_games_played": 80}
    ]}), encoding="utf-8")
    registry = _build_registry(artifact, schedule_provider, roster_path)

    payload_24 = get_games(date=date(2026, 3, 24), providers=registry)
    assert payload_24.projections_available is True
    assert len(payload_24.games) == 1
    assert payload_24.games[0].away_top_projected_scorer is not None
    assert payload_24.games[0].home_top_projected_scorer is not None
    assert payload_24.games[0].away_top_projected_scorer.player_name == "Artemi Panarin"
    assert payload_24.games[0].home_top_projected_scorer.player_name == "David Pastrnak"
    assert not payload_24.games[0].away_top_projected_scorer.player_id.startswith("dev-")
    assert not payload_24.games[0].home_top_projected_scorer.player_id.startswith("dev-")

    artifact_after_24 = json.loads(artifact.read_text(encoding="utf-8"))
    rows_24 = [row for row in artifact_after_24["projections"] if row.get("date") == "2026-03-24"]
    assert len(rows_24) == 6

    payload_25 = get_games(date=date(2026, 3, 25), providers=registry)
    assert payload_25.projections_available is True
    assert len(payload_25.games) == 1
    assert payload_25.games[0].away_top_projected_scorer is not None
    assert payload_25.games[0].home_top_projected_scorer is not None

    artifact_after_25 = json.loads(artifact.read_text(encoding="utf-8"))
    rows_25 = [row for row in artifact_after_25["projections"] if row.get("date") == "2026-03-25"]
    assert len(rows_25) == 4

    payload_24_second = get_games(date=date(2026, 3, 24), providers=registry)
    assert payload_24_second.projections_available is True
    artifact_after_24_second = json.loads(artifact.read_text(encoding="utf-8"))
    assert artifact_after_24_second == artifact_after_25
