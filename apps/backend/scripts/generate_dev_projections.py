from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.services.real_services import NhlScheduleProvider

DEFAULT_ARTIFACT_PATH = Path("apps/backend/app/data/projections/player_first_goal_projections.json")


@dataclass(frozen=True)
class ProjectionTemplate:
    suffix: str
    probability: float


AWAY_TEMPLATES = (
    ProjectionTemplate(suffix="Skater A", probability=0.16),
    ProjectionTemplate(suffix="Skater B", probability=0.12),
    ProjectionTemplate(suffix="Skater C", probability=0.09),
)

HOME_TEMPLATES = (
    ProjectionTemplate(suffix="Skater A", probability=0.15),
    ProjectionTemplate(suffix="Skater B", probability=0.11),
    ProjectionTemplate(suffix="Skater C", probability=0.08),
)


def _iter_dates(start: date, end: date) -> list[date]:
    cursor = start
    dates: list[date] = []
    while cursor <= end:
        dates.append(cursor)
        cursor += timedelta(days=1)
    return dates


def _slug(value: str) -> str:
    lowered = value.lower().strip()
    chars = [ch if ch.isalnum() else "-" for ch in lowered]
    squashed = "".join(chars)
    while "--" in squashed:
        squashed = squashed.replace("--", "-")
    return squashed.strip("-") or "unknown"


def _build_rows_for_date(selected_date: date, schedule_provider: NhlScheduleProvider) -> list[dict[str, Any]]:
    games = schedule_provider.fetch(selected_date)
    rows: list[dict[str, Any]] = []
    for game in games:
        for team_name, side, templates in (
            (game.away_team, "away", AWAY_TEMPLATES),
            (game.home_team, "home", HOME_TEMPLATES),
        ):
            team_slug = _slug(team_name)
            for idx, template in enumerate(templates, start=1):
                player_name = f"{team_name} {template.suffix}"
                rows.append(
                    {
                        "date": selected_date.isoformat(),
                        "game_id": game.game_id,
                        "nhl_player_id": f"dev-{game.game_id}-{side}-{team_slug}-{idx}",
                        "player_name": player_name,
                        "team_name": team_name,
                        "active_team_name": team_name,
                        "is_active_roster": True,
                        "historical_season_first_goals": 2 + idx,
                        "historical_season_games_played": 60 + idx,
                        "model_probability": template.probability,
                    }
                )
    return rows


def _load_artifact(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"schema_version": 1, "projections": []}


def _write_artifact(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def generate_projection_artifact(start: date, end: date, artifact_path: Path) -> None:
    schedule_provider = NhlScheduleProvider()
    payload = _load_artifact(artifact_path)
    existing_rows = payload.get("projections")
    if not isinstance(existing_rows, list):
        raise ValueError("Projection artifact must contain a list field named 'projections'.")

    target_dates = {day.isoformat() for day in _iter_dates(start, end)}
    retained_rows = [row for row in existing_rows if isinstance(row, dict) and row.get("date") not in target_dates]

    generated_rows_by_date: dict[str, list[dict[str, Any]]] = {}
    for day in sorted(target_dates):
        rows_for_date = _build_rows_for_date(date.fromisoformat(day), schedule_provider)
        if rows_for_date:
            generated_rows_by_date[day] = rows_for_date

    retained_rows = [
        row
        for row in retained_rows
        if not isinstance(row, dict) or row.get("date") not in generated_rows_by_date
    ]
    generated_rows = [row for day in sorted(generated_rows_by_date) for row in generated_rows_by_date[day]]
    payload["schema_version"] = 1
    payload["projections"] = sorted(
        [*retained_rows, *generated_rows],
        key=lambda row: (str(row.get("date", "")), str(row.get("game_id", "")), str(row.get("nhl_player_id", ""))),
    )
    _write_artifact(artifact_path, payload)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate development projection rows for scheduled NHL games.")
    parser.add_argument("--start-date", required=True, help="Inclusive start date (YYYY-MM-DD).")
    parser.add_argument("--end-date", required=True, help="Inclusive end date (YYYY-MM-DD).")
    parser.add_argument(
        "--artifact-path",
        default=str(DEFAULT_ARTIFACT_PATH),
        help="Path to projection JSON artifact.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    if end < start:
        raise ValueError("end-date must be greater than or equal to start-date")

    generate_projection_artifact(start=start, end=end, artifact_path=Path(args.artifact_path))


if __name__ == "__main__":
    main()
