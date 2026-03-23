from datetime import date, timedelta

from fastapi import HTTPException, status


def ensure_date_not_more_than_one_day_ahead(selected_date: date) -> None:
    """Raise a 422 if selected_date is more than one day ahead of UTC today."""
    utc_today = date.today()
    if selected_date > utc_today + timedelta(days=1):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="selected_date cannot be more than 1 day ahead of today",
        )
