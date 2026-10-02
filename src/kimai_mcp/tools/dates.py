"""Date parsing helpers shared by the consolidated tools.

Kimai's absence and calendar filters work on calendar dates without a time
zone, so the values parsed here are deliberately naive. Centralizing the
parsing keeps the strict ``YYYY-MM-DD`` contract (and the single
``DTZ007`` suppression that goes with it) in one place.
"""

from datetime import date, datetime, timezone

from .errors import ToolError

DATE_FORMAT = "%Y-%m-%d"


def parse_iso_date(value: str) -> date:
    """Parse a strict ``YYYY-MM-DD`` date string.

    Raises:
        ValueError: if the value is not exactly a ``YYYY-MM-DD`` date.
    """
    return datetime.strptime(value, DATE_FORMAT).date()  # noqa: DTZ007


def day_start(value: str | date) -> str:
    """The ISO timestamp of the day's first second (accepts a date or string)."""
    return f"{_as_date(value).isoformat()}T00:00:00"


def day_end(value: str | date) -> str:
    """The ISO timestamp of the day's last second (accepts a date or string)."""
    return f"{_as_date(value).isoformat()}T23:59:59"


def _as_date(value: str | date) -> date:
    return value if isinstance(value, date) else parse_iso_date(value)


def parse_local_datetime(value: str, field: str) -> datetime:
    r"""Parse a ``/timesheets`` ``begin``/``end`` bound as Kimai's local time.

    Kimai's listing only accepts ``Y-m-d\TH:i:s`` (``TimesheetController``,
    ``Constraints\DateTime(format: 'Y-m-d\TH:i:s')``) and interprets it in the
    user's timezone, so an offset or ``Z`` would be sent along and answered
    with a bare 400. A date alone means midnight. Every tool that reads
    ``/timesheets`` parses its bounds here.

    Raises:
        ToolError: for anything else, saying what to send.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None or parsed.tzinfo is not None or str(value).endswith(("Z", "z")):
        raise ToolError(
            f"Error: Invalid date time for field {field} '{value}'. Use local time without "
            "an offset or 'Z' (YYYY-MM-DDTHH:MM:SS or YYYY-MM-DD); Kimai interprets it in "
            "the user's timezone."
        )
    return parsed


def today() -> date:
    """Today's date in the server's local time zone."""
    return datetime.now(timezone.utc).astimezone().date()
