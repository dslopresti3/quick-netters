from __future__ import annotations


def build_feature_rows(team_games: list[dict], odds_rows: list[dict]) -> list[dict]:
    odds_by_game: dict[str, dict] = {}
    for row in odds_rows:
        game_id = str(row.get("game_id", row.get("gameId", "")))
        if game_id:
            odds_by_game[game_id] = row

    out: list[dict] = []
    for row in team_games:
        game_id = row["game_id"]
        odds = odds_by_game.get(game_id, {})
        out.append(
            {
                "season": row["season"],
                "game_id": game_id,
                "team_id": row["team_id"],
                "opponent_team_id": row["opponent_team_id"],
                "shots_for": row["shots_for"],
                "shots_against": row["shots_against"],
                "goals_for": row["goals_for"],
                "goals_against": row["goals_against"],
                "xg_for": row["xg_for"],
                "xg_against": row["xg_against"],
                "market_moneyline": odds.get("moneyline"),
                "market_total": odds.get("total"),
            }
        )
    return out
