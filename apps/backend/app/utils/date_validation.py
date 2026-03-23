from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta

from fastapi import HTTPException, status


@dataclass(frozen=True)
class DateRuleWindow:
    min_allowed_date: date
    max_allowed_date: date


def _product_rule_lock_enabled() -> bool:
    """Whether to enforce the default today/tomorrow-only product date window."""
    raw = os.getenv("STRICT_TODAY_TOMORROW_DATE_WINDOW", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def get_product_rule_window(reference_date: date | None = None) -> DateRuleWindow:
    """Return the date window allowed by product rule.

    By default, only UTC today and UTC tomorrow are allowed. This can be
    expanded only when STRICT_TODAY_TOMORROW_DATE_WINDOW is explicitly disabled.
    """
    utc_today = reference_date or date.today()

    if _product_rule_lock_enabled():
        return DateRuleWindow(min_allowed_date=utc_today, max_allowed_date=utc_today + timedelta(days=1))

    return DateRuleWindow(min_allowed_date=date.min, max_allowed_date=utc_today + timedelta(days=1))


def is_valid_by_product_rule(selected_date: date, reference_date: date | None = None) -> bool:
    window = get_product_rule_window(reference_date)
    return window.min_allowed_date <= selected_date <= window.max_allowed_date


def ensure_date_not_more_than_one_day_ahead(selected_date: date) -> None:
    """Raise a 422 if selected_date violates the product-rule date window."""
    window = get_product_rule_window()
    if selected_date < window.min_allowed_date or selected_date > window.max_allowed_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "date must be between "
                f"{window.min_allowed_date.isoformat()} and {window.max_allowed_date.isoformat()}"
            ),
        )
