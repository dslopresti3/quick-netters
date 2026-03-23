from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DataPaths:
    """Folder conventions for raw and processed historical assets."""

    root: Path

    @property
    def raw_root(self) -> Path:
        return self.root / "raw"

    @property
    def processed_root(self) -> Path:
        return self.root / "processed"

    def raw_source_season_dir(self, source: str, season: int) -> Path:
        return self.raw_root / source / f"season={season}"

    def processed_table_season_path(self, table: str, season: int) -> Path:
        return self.processed_root / table / f"season={season}" / f"{table}.csv"

    def processed_features_path(self, season: int) -> Path:
        return self.processed_root / "features" / f"season={season}" / "model_features.csv"

    def ensure_layout(self, seasons: tuple[int, ...]) -> None:
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.processed_root.mkdir(parents=True, exist_ok=True)
        for season in seasons:
            for source in ("moneypuck", "nhl_schedule", "nhl_roster", "odds"):
                self.raw_source_season_dir(source, season).mkdir(parents=True, exist_ok=True)
