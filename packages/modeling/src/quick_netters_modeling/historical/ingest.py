from __future__ import annotations

import csv
import json
from pathlib import Path


def load_moneypuck_shots_csv(path: Path, season: int) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            row["season"] = season
            rows.append(row)
    return rows


def load_json_records(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list):
            return data["data"]
        return [data]
    raise ValueError(f"Unsupported JSON format in {path}")


def load_nhl_schedule(path: Path) -> list[dict]:
    return load_json_records(path)


def load_nhl_roster(path: Path) -> list[dict]:
    return load_json_records(path)


def load_odds_market(path: Path) -> list[dict]:
    return load_json_records(path)
