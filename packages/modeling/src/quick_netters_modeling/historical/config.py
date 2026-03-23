from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SeasonConfig:
    """Controls which seasons are loaded for historical modeling datasets."""

    current_season: int

    @property
    def previous_season(self) -> int:
        return self.current_season - 1

    @property
    def historical_seasons(self) -> tuple[int, int]:
        """Historical window = last completed season + current season."""
        return (self.previous_season, self.current_season)

    @classmethod
    def from_string(cls, season: str) -> "SeasonConfig":
        """Parse strings like '2025' into a season config."""
        return cls(current_season=int(season))
