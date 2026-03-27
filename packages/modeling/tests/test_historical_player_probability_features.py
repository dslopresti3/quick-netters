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
) -> dict[str, str]:
    return {
        "season": season,
        "game_date": game_date.isoformat(),
        "game_id": f"{player_id}-{game_date.isoformat()}",
        "game_type_code": str(game_type_code),
        "player_id": player_id,
        "player_name": player_name,
        "team": team,
        "goals": str(goals),
        "shots": str(shots),
        "time_on_ice": toi,
        "power_play_time_on_ice": pp_toi,
        "power_play_goals": str(pp_goals),
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
