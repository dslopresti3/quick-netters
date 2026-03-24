from datetime import date
from unittest.mock import patch

from app.services.nhl_api_data import fetch_player_first_goal_history, fetch_team_roster_current


def test_fetch_team_roster_current_uses_nhl_roster_endpoint() -> None:
    seen: dict[str, str] = {}

    def _fake_fetch_json(*, url: str, headers=None, timeout_seconds=10, opener=None):  # noqa: ANN001
        seen["url"] = url
        return {
            "forwards": [
                {
                    "id": 8478402,
                    "firstName": {"default": "Mitch"},
                    "lastName": {"default": "Marner"},
                    "currentTeamAbbrev": "TOR",
                }
            ]
        }

    with patch("app.services.nhl_api_data.fetch_json", side_effect=_fake_fetch_json):
        rows = fetch_team_roster_current("TOR")

    assert seen["url"] == "https://api-web.nhle.com/v1/roster/TOR/current"
    assert rows[0].player_id == "8478402"


def test_fetch_player_first_goal_history_uses_nhl_player_game_log_endpoint() -> None:
    seen: dict[str, str] = {}

    def _fake_fetch_json(*, url: str, headers=None, timeout_seconds=10, opener=None):  # noqa: ANN001
        seen["url"] = url
        return {
            "gameLog": [
                {"firstGoals": 1},
                {"firstGoal": True},
                {"isFirstGoal": True},
                {},
            ]
        }

    with patch("app.services.nhl_api_data.fetch_json", side_effect=_fake_fetch_json):
        history = fetch_player_first_goal_history("8478402", date(2026, 3, 24))

    assert seen["url"] == "https://api-web.nhle.com/v1/player/8478402/game-log/20252026/2"
    assert history.season_first_goals == 3.0
    assert history.season_games_played == 4.0
