from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date, datetime, timezone

from app.services.identity import name_aliases
from app.services.odds import NormalizedPlayerOdds
from app.services.odds_provider import LiveOddsProvider, TheOddsApiClient, _parse_american_odds
from app.services.provider_wiring import build_provider_registry_from_env
from app.services.recommendation_service import _match_event_to_game, _match_player_to_projection


def _build_row(event: dict, outcome: dict, event_id: str | None, provider_start: datetime | None, snapshot_at: datetime) -> NormalizedPlayerOdds | None:
    player_name = outcome.get("name")
    if not isinstance(player_name, str) or not player_name.strip():
        return None
    odds = _parse_american_odds(outcome.get("price"))
    if odds is None:
        return None

    return NormalizedPlayerOdds(
        nhl_game_id=None,
        nhl_player_id=None,
        market_odds_american=odds,
        snapshot_at=snapshot_at,
        provider_name="the-odds-api",
        provider_event_id=event_id,
        provider_player_name_raw=player_name,
        provider_team_raw=outcome.get("description") if isinstance(outcome.get("description"), str) else None,
        away_team_raw=event.get("away_team") if isinstance(event.get("away_team"), str) else None,
        home_team_raw=event.get("home_team") if isinstance(event.get("home_team"), str) else None,
        provider_start_time=provider_start,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump one matched game player-matching details.")
    parser.add_argument("--date", dest="selected_date", required=True, help="ISO date, e.g. 2026-03-24")
    args = parser.parse_args()
    selected_date = date.fromisoformat(args.selected_date)

    providers = build_provider_registry_from_env()
    service = providers.recommendation_service
    scheduled_games = providers.schedule_provider.fetch(selected_date)
    projections = service._eligible_projection_candidates(selected_date, scheduled_games)  # noqa: SLF001
    projections_by_game: dict[str, list] = {}
    for projection in projections:
        projections_by_game.setdefault(projection.game_id, []).append(projection)

    raw_events: list[dict] = []
    if isinstance(providers.odds_provider, LiveOddsProvider):
        client = providers.odds_provider._client  # noqa: SLF001
        if isinstance(client, TheOddsApiClient):
            raw_events = client.fetch_raw_events(selected_date)

    matched_rows_by_game: dict[str, list[NormalizedPlayerOdds]] = {}
    matched_rows_meta: dict[str, dict[str, str]] = {}
    now = datetime.now(timezone.utc)

    for event in raw_events:
        provider_event_id = event.get("id")
        provider_event_id_str = str(provider_event_id) if provider_event_id is not None else None
        provider_start = None
        commence_time = event.get("commence_time")
        if isinstance(commence_time, str):
            try:
                provider_start = datetime.fromisoformat(commence_time.replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                provider_start = None

        bookmakers = event.get("bookmakers")
        if not isinstance(bookmakers, list):
            continue
        for bookmaker in bookmakers:
            markets = bookmaker.get("markets") if isinstance(bookmaker, dict) else None
            if not isinstance(markets, list):
                continue
            for market in markets:
                if not isinstance(market, dict) or market.get("key") != TheOddsApiClient.first_goal_market_key:
                    continue
                raw_update = market.get("last_update") or bookmaker.get("last_update")
                snapshot_at = now
                if isinstance(raw_update, str):
                    try:
                        snapshot_at = datetime.fromisoformat(raw_update.replace("Z", "+00:00")).astimezone(timezone.utc)
                    except ValueError:
                        snapshot_at = now
                outcomes = market.get("outcomes")
                if not isinstance(outcomes, list):
                    continue
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    row = _build_row(event, outcome, provider_event_id_str, provider_start, snapshot_at)
                    if row is None:
                        continue
                    event_mapping = _match_event_to_game(row, scheduled_games, tolerance_seconds=90 * 60, matched_at=now)
                    if event_mapping.match_status != "matched" or event_mapping.nhl_game_id is None:
                        continue
                    matched_rows_by_game.setdefault(event_mapping.nhl_game_id, []).append(row)
                    matched_rows_meta[event_mapping.nhl_game_id] = {
                        "away_team": event_mapping.away_team_raw or "",
                        "home_team": event_mapping.home_team_raw or "",
                        "provider_event_id": provider_event_id_str or "",
                    }

    if not matched_rows_by_game:
        print(json.dumps({"selected_date": selected_date.isoformat(), "error": "no_matched_games_found"}))
        return

    game_id = sorted(matched_rows_by_game.keys())[0]
    game_rows = matched_rows_by_game[game_id]
    candidate_pool = projections_by_game.get(game_id, [])

    bookmaker_names = [row.provider_player_name_raw or "" for row in game_rows][:20]
    bookmaker_aliases = [{"name": name, "aliases": sorted(name_aliases(name))} for name in bookmaker_names[:5]]
    candidate_aliases = [
        {"name": candidate.player_name, "aliases": sorted(name_aliases(candidate.player_name))} for candidate in candidate_pool[:5]
    ]

    attempted_match_count = 0
    matched_count = 0
    for row in game_rows:
        mapping = _match_player_to_projection(
            row=row,
            event_mapping=_match_event_to_game(row, scheduled_games, tolerance_seconds=90 * 60, matched_at=now),
            projections=candidate_pool,
            matched_at=now,
        )
        attempted_match_count += 1
        if mapping.match_status == "matched":
            matched_count += 1

    payload = {
        "selected_date": selected_date.isoformat(),
        "matched_game": {
            "away_team": matched_rows_meta[game_id]["away_team"],
            "home_team": matched_rows_meta[game_id]["home_team"],
            "game_id": game_id,
        },
        "raw_bookmaker_player_names_20": bookmaker_names,
        "projected_candidate_pool": [asdict(candidate) for candidate in candidate_pool],
        "bookmaker_aliases_5": bookmaker_aliases,
        "candidate_aliases_5": candidate_aliases,
        "matching_attempt_summary": {
            "attempted_against_full_candidate_pool": True,
            "candidate_pool_size": len(candidate_pool),
            "attempted_match_count": attempted_match_count,
            "matched_count": matched_count,
        },
    }
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
