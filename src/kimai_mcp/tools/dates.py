"""Date parsing helpers shared by the consolidated tools.

Kimai's absence and calendar filters work on calendar dates without a time
zone, so the values parsed here are deliberately naive. Centralizing the
parsing keeps the strict ``YYYY-MM-DD`` contract (and the single
``DTZ007`` suppression that goes with it) in one place.
"""

from datetime import date, datetime, time, timezone

from .errors import ToolError

DATE_FORMAT = "%Y-%m-%d"


def parse_iso_date(value: str) -> date:
    """Parse a strict ``YYYY-MM-DD`` date string.

    Raises:
        ValueError: if the value is not exactly a ``YYYY-MM-DD`` date.
    """
    return datetime.strptime(value, DATE_FORMAT).date()


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


def parse_local_end(value: str, field: str) -> datetime:
    """Like :func:`parse_local_datetime`, but a date alone means the end of that day.

    Kimai keeps records that *started* at or before ``end``, so a date-only
    end parsed as midnight silently dropped the whole last day of a period.
    """
    parsed = parse_local_datetime(value, field)
    try:
        # Whatever date.fromisoformat takes is a date without a time, on every
        # Python version: YYYY-MM-DD, and on 3.11+ also 20250630 or 2025-W27-1.
        date.fromisoformat(str(value).strip())
    except ValueError:
        return parsed
    return parsed.replace(hour=23, minute=59, second=59)


def whole_day(begin: datetime | None, end: datetime | None) -> datetime | None:
    """``end`` for a bound pair: the same midnight twice means that whole day.

    Kimai's ``end`` is inclusive (records started at or before it), so the
    day ends at 23:59:59; the next midnight would take that day's first
    records too.
    """
    if begin is not None and end is not None and begin == end and end.time() == time.min:
        return end.replace(hour=23, minute=59, second=59)
    return end


def parse_utc_datetime(value: str, field: str) -> datetime:
    r"""Parse ``modified_after`` of ``/timesheets``, which Kimai compares in UTC.

    Same wire format as ``begin``/``end`` (``Y-m-d\TH:i:s``, no offset), but
    the column is stored in UTC, so here an offset or ``Z`` is meaningful: it
    is converted to UTC. A value without one is taken as UTC already.

    Raises:
        ToolError: if the value is not an ISO date-time.
    """
    text = str(value)
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ToolError(
            f"Error: Invalid date time for field {field} '{value}'. Use UTC as "
            "YYYY-MM-DDTHH:MM:SS (an offset is converted to UTC)."
        )
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def today() -> date:
    """Today's date in the server's local time zone."""
    return datetime.now(timezone.utc).astimezone().date()
