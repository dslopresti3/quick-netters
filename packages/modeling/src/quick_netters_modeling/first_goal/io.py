from __future__ import annotations

import csv
import json
from pathlib import Path

from .schemas import PlayerFirstGoalPrediction


def write_predictions_csv(path: str | Path, predictions: list[PlayerFirstGoalPrediction]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = [prediction.to_row() for prediction in predictions]
    if not rows:
        destination.write_text("", encoding="utf-8")
        return

    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_predictions_json(path: str | Path, predictions: list[PlayerFirstGoalPrediction]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = [prediction.to_row() for prediction in predictions]
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
