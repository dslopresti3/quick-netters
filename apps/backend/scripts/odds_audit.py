from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone

from app.services.identity import name_aliases, team_alias_tokens
from app.services.recommendation_service import _match_event_to_game, _match_player_to_projection
from app.services.odds import STALE_ODDS_THRESHOLD, NormalizedPlayerOdds
from app.services.odds_provider import LiveOddsProvider, TheOddsApiClient, _parse_american_odds
from app.services.provider_wiring import build_provider_registry_from_env


@dataclass(frozen=True)
class OddsAuditReport:
    selected_date: str
    active_odds_provider_class: str
    upstream_odds_base_url: str | None
    upstream_query_params: dict[str, str] | None
    raw_event_count: int
    selected_event_id_count: int
    extracted_outcome_count: int
    matched_game_count: int
    matched_player_count: int
    valid_final_odds_row_count: int
    excluded_unmatched_game: int
    excluded_unmatched_player: int
    excluded_stale_odds: int
    excluded_malformed_odds: int
    excluded_inactive_roster_ineligible: int
    odds_available_logic: str
    odds_available: bool
    root_cause: str


def _query_params(client: TheOddsApiClient, selected_date: date) -> dict[str, str]:
    api_key_value = "<redacted>" if client._api_key else "<missing>"
    return {
        "apiKey": api_key_value,
        "dateFormat": "iso",
    }


def run_audit(selected_date: date) -> OddsAuditReport:
    providers = build_provider_registry_from_env()
    service = providers.recommendation_service
    scheduled_games = providers.schedule_provider.fetch(selected_date)

    all_projections = providers.projection_provider.fetch_player_first_goal_projections(selected_date)
    eligible_projections = service._eligible_projection_candidates(selected_date, scheduled_games)  # noqa: SLF001
    eligible_by_game: dict[str, list] = {}
    inactive_by_game: dict[str, list] = {}
    for projection in eligible_projections:
        eligible_by_game.setdefault(projection.game_id, []).append(projection)
    for projection in all_projections:
        if not projection.roster_eligibility.is_active_roster:
            inactive_by_game.setdefault(projection.game_id, []).append(projection)

    raw_events: list[dict] = []
    events_index: list[dict] = []
    selected_event_ids: list[str] = []
    base_url: str | None = None
    query_params: dict[str, str] | None = None

    if isinstance(providers.odds_provider, LiveOddsProvider):
        client = providers.odds_provider._client  # noqa: SLF001
        if isinstance(client, TheOddsApiClient):
            base_url = client.events_url
            query_params = _query_params(client, selected_date)
            events_index = client.fetch_events_index()
            selected_event_ids = client.fetch_event_ids_for_slate(selected_date)
            raw_events = client.fetch_raw_events(selected_date)
    elif hasattr(providers.odds_provider, "_provider"):
        live_provider = providers.odds_provider._provider  # noqa: SLF001
        if isinstance(live_provider, LiveOddsProvider):
            client = live_provider._client  # noqa: SLF001
            if isinstance(client, TheOddsApiClient):
                base_url = client.events_url
                query_params = _query_params(client, selected_date)
                events_index = client.fetch_events_index()
                selected_event_ids = client.fetch_event_ids_for_slate(selected_date)
                raw_events = client.fetch_raw_events(selected_date)

    extracted_outcome_count = 0
    matched_game_event_ids: set[str] = set()
    matched_player_count = 0
    valid_final_odds_row_count = 0

    excluded_unmatched_game = 0
    excluded_unmatched_player = 0
    excluded_stale_odds = 0
    excluded_malformed_odds = 0
    excluded_inactive_roster_ineligible = 0

    matched_at = datetime.now(timezone.utc)
    tolerance_seconds = 90 * 60

    for event in raw_events:
        away_team_raw = event.get("away_team")
        home_team_raw = event.get("home_team")
        provider_event_id = event.get("id")
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
            if not isinstance(bookmaker, dict):
                continue
            markets = bookmaker.get("markets")
            if not isinstance(markets, list):
                continue
            market_update = market_last_update = None
            for market in markets:
                if not isinstance(market, dict) or market.get("key") != TheOddsApiClient.first_goal_market_key:
                    continue

                raw_update = market.get("last_update") or bookmaker.get("last_update")
                if isinstance(raw_update, str):
                    try:
                        market_update = datetime.fromisoformat(raw_update.replace("Z", "+00:00")).astimezone(timezone.utc)
                        market_last_update = market_update
                    except ValueError:
                        market_last_update = datetime.now(timezone.utc)
                else:
                    market_last_update = datetime.now(timezone.utc)

                outcomes = market.get("outcomes")
                if not isinstance(outcomes, list):
                    continue

                for outcome in outcomes:
                    extracted_outcome_count += 1
                    if not isinstance(outcome, dict):
                        excluded_malformed_odds += 1
                        continue
                    player_name = outcome.get("name")
                    if not isinstance(player_name, str) or not player_name.strip():
                        excluded_malformed_odds += 1
                        continue
                    odds = _parse_american_odds(outcome.get("price"))
                    if odds is None:
                        excluded_malformed_odds += 1
                        continue

                    snapshot_at = market_last_update or datetime.now(timezone.utc)
                    if datetime.now(timezone.utc) - snapshot_at > STALE_ODDS_THRESHOLD:
                        excluded_stale_odds += 1
                        continue

                    row = NormalizedPlayerOdds(
                        nhl_game_id=None,
                        nhl_player_id=None,
                        market_odds_american=odds,
                        snapshot_at=snapshot_at,
                        provider_name="the-odds-api",
                        provider_event_id=str(provider_event_id) if provider_event_id is not None else None,
                        provider_player_name_raw=player_name,
                        provider_team_raw=outcome.get("description") if isinstance(outcome.get("description"), str) else None,
                        away_team_raw=away_team_raw if isinstance(away_team_raw, str) else None,
                        home_team_raw=home_team_raw if isinstance(home_team_raw, str) else None,
                        provider_start_time=provider_start,
                    )

                    event_mapping = _match_event_to_game(row, scheduled_games, tolerance_seconds=tolerance_seconds, matched_at=matched_at)
                    if event_mapping.match_status != "matched":
                        excluded_unmatched_game += 1
                        continue
                    if row.provider_event_id:
                        matched_game_event_ids.add(row.provider_event_id)

                    game_id = event_mapping.nhl_game_id or ""
                    player_mapping = _match_player_to_projection(
                        row,
                        event_mapping,
                        projections=eligible_by_game.get(game_id, []),
                        matched_at=matched_at,
                    )
                    if player_mapping.match_status == "matched":
                        matched_player_count += 1
                        valid_final_odds_row_count += 1
                        continue

                    inactive_candidates = inactive_by_game.get(game_id, [])
                    provider_aliases = name_aliases(player_name)
                    team_tokens = team_alias_tokens(row.provider_team_raw) if row.provider_team_raw else set()
                    inactive_name_match = False
                    for candidate in inactive_candidates:
                        if team_tokens and team_tokens.isdisjoint(team_alias_tokens(candidate.roster_eligibility.active_team_name)):
                            continue
                        if provider_aliases.isdisjoint(name_aliases(candidate.player_name)):
                            continue
                        inactive_name_match = True
                        break

                    if inactive_name_match:
                        excluded_inactive_roster_ineligible += 1
                    else:
                        excluded_unmatched_player += 1

    odds_available = service.odds_available(selected_date)
    if raw_events == [] and query_params is not None and query_params["apiKey"] == "<missing>":
        root_cause = "The active The Odds API client has no API key configured (ODDS_API_KEY/THE_ODDS_API_KEY), so upstream fetch returns zero events."
    elif valid_final_odds_row_count == 0 and excluded_stale_odds > 0:
        root_cause = "All candidate outcomes are stale under the current 30-minute freshness threshold."
    elif valid_final_odds_row_count == 0 and excluded_unmatched_game > 0:
        root_cause = "No fresh, well-formed odds outcomes can be mapped to scheduled NHL games within tolerance."
    elif valid_final_odds_row_count == 0 and excluded_unmatched_player > 0:
        root_cause = "No game-matched outcomes can be mapped to eligible NHL projection players."
    elif valid_final_odds_row_count == 0:
        root_cause = "No valid odds rows survive normalization and mapping filters."
    else:
        root_cause = "N/A (odds are available)."

    return OddsAuditReport(
        selected_date=selected_date.isoformat(),
        active_odds_provider_class=f"{providers.odds_provider.__class__.__module__}.{providers.odds_provider.__class__.__name__}",
        upstream_odds_base_url=base_url,
        upstream_query_params=query_params,
        raw_event_count=len(events_index),
        selected_event_id_count=len(selected_event_ids),
        extracted_outcome_count=extracted_outcome_count,
        matched_game_count=len(matched_game_event_ids),
        matched_player_count=matched_player_count,
        valid_final_odds_row_count=valid_final_odds_row_count,
        excluded_unmatched_game=excluded_unmatched_game,
        excluded_unmatched_player=excluded_unmatched_player,
        excluded_stale_odds=excluded_stale_odds,
        excluded_malformed_odds=excluded_malformed_odds,
        excluded_inactive_roster_ineligible=excluded_inactive_roster_ineligible,
        odds_available_logic=(
            "odds_available = any(mapped_row.market_odds_american != 0 and not is_stale(mapped_row.snapshot_at) "
            "for mapped_row in mapped_rows)"
        ),
        odds_available=odds_available,
        root_cause=root_cause,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit odds ingestion/matching pipeline for a date")
    parser.add_argument("--date", dest="selected_date", required=True, help="ISO date, e.g. 2026-03-23")
    args = parser.parse_args()

    selected_date = date.fromisoformat(args.selected_date)
    report = run_audit(selected_date)
    print(json.dumps(asdict(report), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
