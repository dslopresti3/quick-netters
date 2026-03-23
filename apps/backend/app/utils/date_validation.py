from datetime import date, timedelta

from fastapi import HTTPException, status


def ensure_date_not_more_than_one_day_ahead(selected_date: date) -> None:
    """Raise a 422 if selected_date is later than tomorrow in UTC."""
    utc_today = date.today()
    tomorrow = utc_today + timedelta(days=1)
    if selected_date > tomorrow:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"date must be on or before {tomorrow.isoformat()}",
        )
