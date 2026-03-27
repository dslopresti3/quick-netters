from __future__ import annotations

from datetime import date, timedelta

from quick_netters_modeling.historical.features import build_player_probability_features


def _player_row(
    *,
    player_id: str,
    player_name: str,
    team: str,
    game_date: date,
    goals: int,
    shots: int,
    season: str = "20252026",
    game_type_code: int = 2,
    toi: str = "16:00",
    pp_toi: str = "02:00",
    pp_goals: int = 0,
    opponent: str = "Opp",
    opposing_goalie_id: str = "",
) -> dict[str, str]:
    return {
        "season": season,
        "game_date": game_date.isoformat(),
        "game_id": f"{player_id}-{game_date.isoformat()}",
        "game_type_code": str(game_type_code),
        "player_id": player_id,
        "player_name": player_name,
        "team": team,
        "opponent": opponent,
        "goals": str(goals),
        "shots": str(shots),
        "time_on_ice": toi,
        "power_play_time_on_ice": pp_toi,
        "power_play_goals": str(pp_goals),
        "opposing_goalie_id": opposing_goalie_id,
    }


def test_build_player_probability_features_creates_recent_and_season_features() -> None:
    as_of = date(2026, 2, 15)
    rows = []
    for idx in range(12):
        rows.append(
            _player_row(
                player_id="11",
                player_name="Skater One",
                team="Leafs",
                game_date=as_of - timedelta(days=idx + 1),
                goals=1 if idx % 4 == 0 else 0,
                shots=4,
                pp_goals=1 if idx % 6 == 0 else 0,
            )
        )
    rows.append(
        _player_row(
            player_id="11",
            player_name="Skater One",
            team="Leafs",
            game_date=as_of - timedelta(days=20),
            goals=2,
            shots=6,
            game_type_code=1,
        )
    )

    features = build_player_probability_features(rows, as_of_date=as_of, season="20252026")

    assert len(features) == 1
    row = features[0]
    assert row["games_last_5"] == 5
    assert row["games_last_10"] == 10
    assert row["games_last_20"] == 12
    assert row["games_played_season"] == 12
    assert row["goals_last_5"] >= 1
    assert row["shots_last_10"] == 40
    assert row["goals_per_game_last_10_stabilized"] <= row["goals_per_game_last_10"]
    assert row["projection_market_ready_anytime"] is True
    assert row["projection_market_ready_first_goal"] is True


def test_small_sample_hot_streak_is_shrunk_relative_to_sustained_player() -> None:
    as_of = date(2026, 3, 1)
    rows = []

    # Hot new player: tiny sample with extreme conversion.
    for idx in range(2):
        rows.append(
            _player_row(
                player_id="91",
                player_name="Hot Rookie",
                team="Wolves",
                game_date=as_of - timedelta(days=idx + 1),
                goals=2,
                shots=3,
                toi="12:00",
                pp_toi="00:30",
            )
        )

    # Sustained player: much larger body of work at a strong, but realistic, rate.
    for idx in range(24):
        rows.append(
            _player_row(
                player_id="19",
                player_name="Sustained Vet",
                team="Wolves",
                game_date=as_of - timedelta(days=idx + 1),
                goals=0 if idx % 4 == 0 else 1,
                shots=5,
                toi="18:00",
                pp_toi="03:30",
            )
        )

    features = build_player_probability_features(rows, as_of_date=as_of, season="20252026")
    by_player = {row["player_id"]: row for row in features}

    hot = by_player["91"]
    vet = by_player["19"]

    assert hot["goals_per_game_last_5"] > vet["goals_per_game_last_5"]
    assert hot["projected_goals_per_game"] < hot["goals_per_game_last_5"]
    assert hot["projected_goals_per_game"] < vet["projected_goals_per_game"]
    assert hot["recent_form_confidence"] < vet["recent_form_confidence"]


def test_player_vs_team_matchup_history_is_heavily_shrunk_for_small_samples() -> None:
    as_of = date(2026, 3, 10)
    rows = []
    for idx in range(20):
        rows.append(
            _player_row(
                player_id="77",
                player_name="Matchup Skater",
                team="Leafs",
                game_date=as_of - timedelta(days=idx + 1),
                goals=1 if idx % 3 == 0 else 0,
                shots=4,
                opponent="Bruins" if idx < 2 else "Sens",
            )
        )

    features = build_player_probability_features(
        rows,
        as_of_date=as_of,
        season="20252026",
        matchup_team_by_player={"77": "Bruins"},
    )
    row = features[0]

    assert row["vs_opponent_team_games"] == 2
    assert row["vs_opponent_team_goals_per_game"] == 0.5
    assert row["vs_opponent_team_goals_per_game_stabilized"] < 0.6
    assert row["vs_opponent_team_goals_rate_modifier"] <= 1.25
    assert row["vs_opponent_team_confidence"] < 0.1


def test_player_vs_goalie_matchup_history_is_moderate_even_with_larger_samples() -> None:
    as_of = date(2026, 3, 10)
    rows = []
    for idx in range(26):
        rows.append(
            _player_row(
                player_id="12",
                player_name="Shooter",
                team="Rangers",
                game_date=as_of - timedelta(days=idx + 1),
                goals=1 if idx % 4 == 0 else 0,
                shots=5,
                opponent="Devils",
                opposing_goalie_id="goalie-a" if idx < 12 else "goalie-b",
            )
        )

    features = build_player_probability_features(
        rows,
        as_of_date=as_of,
        season="20252026",
        matchup_goalie_by_player={"12": "goalie-a"},
    )
    row = features[0]

    assert row["vs_opposing_goalie_games"] == 12
    assert row["vs_opposing_goalie_available"] is True
    assert row["vs_opposing_goalie_confidence"] <= 0.14
    assert row["vs_opposing_goalie_goals_rate_modifier"] <= 1.25
    assert abs(row["vs_opposing_goalie_goals_per_game_stabilized"] - row["projected_goals_per_game"]) < 0.2


def test_goalie_matchup_features_fall_back_when_linkage_missing() -> None:
    as_of = date(2026, 3, 10)
    rows = [
        _player_row(
            player_id="88",
            player_name="No Link Skater",
            team="Kings",
            game_date=as_of - timedelta(days=idx + 1),
            goals=1 if idx % 5 == 0 else 0,
            shots=3,
            opponent="Ducks",
            opposing_goalie_id="",
        )
        for idx in range(10)
    ]
    features = build_player_probability_features(rows, as_of_date=as_of, season="20252026")
    row = features[0]

    assert row["vs_opposing_goalie_available"] is False
    assert row["vs_opposing_goalie_games"] == 0
    assert row["vs_opposing_goalie_goals_rate_modifier"] == 1.0
