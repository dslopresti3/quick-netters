from __future__ import annotations

from collections.abc import Iterable


class ValidationError(Exception):
    """Raised when historical data quality checks fail."""


def validate_required_columns(rows: list[dict], required_columns: Iterable[str], table_name: str) -> None:
    if not rows:
        raise ValidationError(f"{table_name}: table is empty")

    cols = set(rows[0].keys())
    missing = [col for col in required_columns if col not in cols]
    if missing:
        raise ValidationError(f"{table_name}: missing required columns {missing}")


def validate_no_missing_values(rows: list[dict], columns: Iterable[str], table_name: str) -> None:
    for i, row in enumerate(rows):
        for col in columns:
            if row.get(col) in (None, ""):
                raise ValidationError(f"{table_name}: missing value at row={i} column={col}")


def validate_no_duplicate_keys(rows: list[dict], key_columns: tuple[str, ...], table_name: str) -> None:
    seen: set[tuple] = set()
    for i, row in enumerate(rows):
        key = tuple(row[col] for col in key_columns)
        if key in seen:
            raise ValidationError(f"{table_name}: duplicate key {key} at row={i}")
        seen.add(key)
