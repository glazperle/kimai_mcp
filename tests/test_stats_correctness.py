"""Timesheet and absence statistics must match what Kimai counts.

Found reviewing the issue #30 fix: each test states the wrong number the tool
used to report, mostly silently.
"""

# Filter bounds are naive on purpose: Kimai interprets them in the user's local time.
# ruff: noqa: DTZ001

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from kimai_mcp.client import KimaiAPIError, KimaiClient
from kimai_mcp.models import Absence, TimesheetEntity, TimesheetFilter, User
from kimai_mcp.tools import timesheet_consolidated as ts
from kimai_mcp.tools.absence_analytics import AbsenceAnalytics
from kimai_mcp.tools.timesheet_analytics import TimesheetAnalytics

UTC = timezone.utc


def _row(i: int, begin: datetime | None = None, hours: int = 8, user: int = 1) -> dict:
    begin = begin or datetime(2026, 9, 1, 8, tzinfo=UTC)
    return {
        "id": i, "project": 1, "activity": 1, "user": user, "tags": [],
        "begin": begin.isoformat(), "end": (begin + timedelta(hours=hours)).isoformat(),
        "duration": hours * 3600,
    }


def _entity(begin: datetime, hours: int = 8, user: int = 1, **extra) -> TimesheetEntity:
    data = {**_row(0, begin, hours, user), **extra}
    return TimesheetEntity(**data)


def _client(pages: dict[int, list | Exception]) -> KimaiClient:
    client = KimaiClient(base_url="https://kimai.example.com", api_token="token")

    async def request(method, endpoint, params=None, **kwargs):
        result = pages.get(params.get("page", 1), [])
        if isinstance(result, Exception):
            raise result
        return result

    client._request = AsyncMock(side_effect=request)
    return client


# --- paging ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exact_multiple_of_the_page_size_is_not_a_404_failure():
    # Kimai answers the page after a full last page with 404, not an empty list.
    client = _client({1: [_row(i) for i in range(50)], 2: KimaiAPIError("Not Found", 404)})

    rows, fetched_all, _page = await client.get_timesheets(TimesheetFilter(user="1", size=50))

    assert len(rows) == 50
    assert fetched_all is True


@pytest.mark.asyncio
async def test_a_404_on_the_first_page_still_raises():
    client = _client({1: KimaiAPIError("Not Found", 404)})
    with pytest.raises(KimaiAPIError):
        await client.get_timesheets(TimesheetFilter(user="1"))


@pytest.mark.asyncio
async def test_size_above_kimais_cap_is_not_mistaken_for_the_last_page():
    # Kimai caps size at 500; 500 < 1000 used to mean "that was everything".
    client = _client({1: [_row(i) for i in range(500)]})

    _rows, fetched_all, _page = await client.get_timesheets(TimesheetFilter(user="1", size=1000))

    assert fetched_all is False
    assert client._request.await_args.kwargs["params"]["size"] == 500


@pytest.mark.asyncio
async def test_stats_with_an_explicit_page_cover_the_whole_filter():
    pages = {1: [_entity(datetime(2026, 9, d, 8, tzinfo=UTC)) for d in (1, 2)],
             2: [_entity(datetime(2026, 9, d, 8, tzinfo=UTC)) for d in (3, 4)],
             3: [_entity(datetime(2026, 9, 5, 8, tzinfo=UTC))]}
    client = AsyncMock(spec=KimaiClient)
    client.get_current_user.return_value = User(id=1, username="alice", enabled=True)
    client.get_projects.return_value = []

    async def get_timesheets(f):
        page = f.page or 1
        return pages.get(page, []), len(pages.get(page, [])) < 2, page

    client.get_timesheets.side_effect = get_timesheets

    text = (await ts.handle_timesheet(client, action="list", filters={
        "page": 3, "size": 2, "calculate_stats": True, "stats_format": "json"}))[0].text

    assert '"total_entries": 5' in text


# --- what counts as worked time ------------------------------------------------

def test_hours_come_from_kimais_duration_not_the_wall_clock_span():
    # 08:00-17:00 with a 1h break: Kimai's duration is 8h, the span is 9h.
    record = _entity(datetime(2026, 9, 1, 8, tzinfo=UTC), hours=9, duration=28800, **{"break": 3600})

    stats = TimesheetAnalytics.calculate_statistics([record])

    assert stats["total_hours"] == 8.0


def test_several_users_on_one_day_are_person_days():
    day = datetime(2026, 9, 1, 8, tzinfo=UTC)
    stats = TimesheetAnalytics.calculate_statistics([_entity(day, user=u) for u in (1, 2, 3)])

    assert stats["working_days_count"] == 3
    assert stats["avg_hours_per_day"] == 8.0
    assert "Person-Days" in TimesheetAnalytics.format_statistics_report(stats)


# --- year-over-year ----------------------------------------------------------

def _monthly(year: int, months: range) -> list[TimesheetEntity]:
    return [_entity(datetime(year, m, 1, 8, tzinfo=UTC), hours=10) for m in months]


def test_partial_years_are_not_compared():
    # Jul 2025 - Sep 2026 with the same workload used to read "+50%".
    records = _monthly(2025, range(7, 13)) + _monthly(2026, range(1, 10))
    stats = TimesheetAnalytics.calculate_statistics(
        records, breakdown_by_year=True,
        period=(datetime(2025, 7, 1), datetime(2026, 9, 30, 23, 59, 59)))

    report = TimesheetAnalytics.format_statistics_report(stats)

    assert stats["years"]["2025"]["partial"] == "2025-07-01 to 2025-12-31"
    assert stats["years"]["2026"]["partial"] == "2026-01-01 to 2026-09-30"
    assert "not compared" in report
    assert "%" not in report.split("Year-over-Year", 1)[1]


def test_fully_covered_years_are_compared():
    records = _monthly(2024, range(1, 13)) + _monthly(2025, range(1, 13))
    stats = TimesheetAnalytics.calculate_statistics(
        records, breakdown_by_year=True,
        period=(datetime(2024, 1, 1), datetime(2025, 12, 31, 23, 59, 59)))

    report = TimesheetAnalytics.format_statistics_report(stats)

    assert "partial" not in stats["years"]["2024"]
    assert "2024 → 2025**: +0h (+0.0%)" in report


# --- absences ----------------------------------------------------------------

def test_half_days_count_half_and_no_fixed_hours_per_day():
    user = User(id=1, username="alice", enabled=True)
    day = datetime(2026, 9, 1)
    absences = [
        Absence(user=user, date=day, type="holiday"),
        Absence(user=user, date=day + timedelta(days=1), type="holiday", halfDay=True),
        # A full day on a 6h contract used to come out as 0.75 days.
        Absence(user=user, date=day + timedelta(days=2), type="other", duration=21600),
    ]

    stats = AbsenceAnalytics.calculate_statistics(absences)

    assert stats["by_type"]["holiday"]["days"] == 1.5
    assert stats["by_type"]["other"]["days"] == 1
    assert stats["by_type"]["other"]["hours"] == 6.0
    assert stats["total_days"] == 2.5
