"""Date parsing helpers shared by the consolidated tools.

Kimai's absence and calendar filters work on calendar dates without a time
zone, so the values parsed here are deliberately naive. Centralizing the
parsing keeps the strict ``YYYY-MM-DD`` contract (and the single
``DTZ007`` suppression that goes with it) in one place.
"""

from datetime import date, datetime, timezone

DATE_FORMAT = "%Y-%m-%d"


def parse_iso_date(value: str) -> date:
    """Parse a strict ``YYYY-MM-DD`` date string.

    Raises:
        ValueError: if the value is not exactly a ``YYYY-MM-DD`` date.
    """
    return datetime.strptime(value, DATE_FORMAT).date()  # noqa: DTZ007


def day_start(value: str) -> str:
    """Turn ``YYYY-MM-DD`` into the ISO timestamp of that day's first second."""
    return f"{parse_iso_date(value).isoformat()}T00:00:00"


def day_end(value: str) -> str:
    """Turn ``YYYY-MM-DD`` into the ISO timestamp of that day's last second."""
    return f"{parse_iso_date(value).isoformat()}T23:59:59"


def today() -> date:
    """Today's date in the server's local time zone."""
    return datetime.now(timezone.utc).astimezone().date()
