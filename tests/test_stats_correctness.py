"""Timesheet and absence statistics must match what Kimai counts.

Found reviewing the issue #30 fix: each test states the wrong number the tool
used to report, mostly silently.
"""

# Filter bounds are naive on purpose: Kimai interprets them in the user's local time.

import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from kimai_mcp.client import KimaiAPIError, KimaiClient
from kimai_mcp.models import Absence, TimesheetEntity, TimesheetFilter, User
from kimai_mcp.tools import timesheet_consolidated as ts
from kimai_mcp.tools.absence_analytics import AbsenceAnalytics
from kimai_mcp.tools.errors import ToolError
from kimai_mcp.tools.project_analysis import handle_analyze_project_team
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


def _client(pages: dict[int, list | Exception], total_pages: int | None = None) -> KimaiClient:
    """Answers per page; ``total_pages`` sends X-Total-Pages (None: no header)."""
    client = KimaiClient(base_url="https://kimai.example.com", api_token="token")
    headers = httpx.Headers({"X-Total-Pages": str(total_pages)} if total_pages is not None else {})

    async def request(method, endpoint, params=None, **kwargs):
        result = pages.get(params.get("page", 1), [])
        if isinstance(result, Exception):
            raise result
        return result, headers

    client._request_with_headers = AsyncMock(side_effect=request)
    return client


# --- paging ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exact_multiple_of_the_page_size_is_not_a_404_failure():
    # Kimai answers the page after a full last page with 404, not an empty list.
    client = _client({1: [_row(i) for i in range(50)], 2: KimaiAPIError("Not Found", 404)})

    rows, fetched_all = await client.get_timesheets(TimesheetFilter(user="1", size=50))

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

    rows, fetched_all = await client.get_timesheets(TimesheetFilter(user="1", size=1000))

    # A full page of 500 is not the end: the next page is asked for.
    assert [c.kwargs["params"]["page"] for c in client._request_with_headers.await_args_list] == [1, 2]
    assert client._request_with_headers.await_args.kwargs["params"]["size"] == 500
    assert (len(rows), fetched_all) == (500, True)


@pytest.mark.asyncio
async def test_records_of_every_page_are_collected():
    """Statistics, the meta filter and the analysis rely on this loop; a loop that
    stopped after page 1 reported 500 of 1200 records as complete."""
    client = _client({1: [_row(i) for i in range(50)], 2: [_row(50 + i) for i in range(50)],
                      3: [_row(100 + i) for i in range(7)]})

    rows, fetched_all = await client.get_timesheets(TimesheetFilter(user="1"))

    assert (len(rows), fetched_all) == (107, True)
    assert [r.id for r in rows] == list(range(107))


@pytest.mark.asyncio
async def test_max_results_stops_the_loop_and_says_so():
    client = _client({page: [_row(page * 100 + i) for i in range(50)] for page in (1, 2, 3)})

    rows, fetched_all = await client.get_timesheets(TimesheetFilter(user="1"), max_results=100)

    assert (len(rows), fetched_all) == (100, False)


@pytest.mark.asyncio
async def test_a_fetch_ending_exactly_at_the_limit_is_complete():
    """10000 records in 20 full pages used to read as 'Not all records were used'."""
    client = _client({1: [_row(i) for i in range(50)], 2: [_row(50 + i) for i in range(50)]}, total_pages=2)

    rows, fetched_all = await client.get_timesheets(TimesheetFilter(user="1"), max_results=100)

    assert (len(rows), fetched_all) == (100, True)
    # Kimai's page count ends the loop: no 404 probe after the last full page.
    assert client._request_with_headers.await_count == 2


@pytest.mark.asyncio
async def test_a_record_repeated_on_a_later_page_is_counted_once():
    """Kimai's 'name:~' search counts and pages a record once per meta row."""
    client = _client({1: [_row(1), _row(2)], 2: [_row(2), _row(3)]}, total_pages=2)

    rows, _ = await client.get_timesheets(TimesheetFilter(user="1", size=2))

    assert [r.id for r in rows] == [1, 2, 3]


@pytest.mark.asyncio
async def test_full_is_never_sent_by_the_every_page_reader():
    """Its rows are parsed as TimesheetEntity; Expanded rows would not parse."""
    client = _client({1: [_row(1)]})

    await client.get_timesheets(TimesheetFilter(user="1", full="true"))

    assert "full" not in client._request_with_headers.await_args.kwargs["params"]


def _stats_client(rows: list) -> AsyncMock:
    client = AsyncMock(spec=KimaiClient)
    client.get_current_user.return_value = User(id=1, username="alice", enabled=True)
    client.get_projects.return_value = []
    client.get_activities.return_value = []
    client.get_users.return_value = []
    client.get_timesheets.return_value = (rows, True)
    return client


_FIVE = [_entity(datetime(2026, 9, d, 8, tzinfo=UTC), id=d) for d in range(1, 6)]


@pytest.mark.asyncio
async def test_stats_with_an_explicit_page_cover_the_whole_filter():
    client = _stats_client(_FIVE)

    text = (await ts.handle_timesheet(client, action="list", filters={
        "page": 3, "size": 2, "calculate_stats": True, "stats_format": "json"}))[0].text

    assert '"total_entries": 5' in text
    # Every page from the first, in the largest pages Kimai serves.
    sent = client.get_timesheets.await_args.args[0]
    assert (sent.page, sent.size) == (None, 500)


@pytest.mark.asyncio
async def test_listing_after_the_stats_still_shows_only_the_requested_page():
    client = _stats_client(_FIVE)

    text = (await ts.handle_timesheet(client, action="list", filters={
        "page": 2, "size": 2, "calculate_stats": True, "stats_format": "detailed"}))[0].text

    listed = {line.split(" ")[0] for line in text.splitlines() if re.match(r"#\d+ ", line)}
    assert listed == {"#3", "#4"}


@pytest.mark.asyncio
async def test_a_404_on_an_explicit_page_is_an_error_not_an_empty_result():
    client = _client({7: KimaiAPIError("Not Found", 404)})
    with pytest.raises(KimaiAPIError):
        await client.get_timesheet_page(TimesheetFilter(user="1", page=7))


# --- what counts as worked time ------------------------------------------------

def test_a_record_without_duration_falls_back_to_the_span_minus_break():
    begin = datetime(2026, 9, 1, 8, tzinfo=UTC)
    record = TimesheetEntity(id=1, project=1, activity=1, begin=begin,
                             end=begin + timedelta(hours=9), **{"break": 3600})

    assert TimesheetAnalytics.calculate_statistics([record])["total_hours"] == 8.0


def test_hours_come_from_kimais_duration_not_the_wall_clock_span():
    # 08:00-17:00 with a 1h break: Kimai's duration is 8h, the span is 9h.
    record = _entity(datetime(2026, 9, 1, 8, tzinfo=UTC), hours=9, duration=28800, **{"break": 3600})

    stats = TimesheetAnalytics.calculate_statistics([record])

    assert stats["total_hours"] == 8.0


def test_several_users_on_one_day_are_person_days():
    day = datetime(2026, 9, 1, 8, tzinfo=UTC)
    stats = TimesheetAnalytics.calculate_statistics([_entity(day, user=u) for u in (1, 2, 3)])

    # The calendar-day keys keep their meaning in the JSON; person-days are new keys.
    assert stats["working_days_count"] == 1
    assert stats["avg_hours_per_day"] == 24.0
    assert stats["person_days_count"] == 3
    assert stats["avg_hours_per_person_day"] == 8.0
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


def test_an_end_at_midnight_of_dec_31_leaves_the_year_partial():
    records = _monthly(2024, range(1, 13)) + _monthly(2025, range(1, 13))
    stats = TimesheetAnalytics.calculate_statistics(
        records, breakdown_by_year=True,
        period=(datetime(2024, 1, 1), datetime(2025, 12, 31)))

    assert stats["years"]["2025"]["partial"] == "2025-01-01 to 2025-12-31"


def test_fully_covered_years_are_compared():
    records = _monthly(2024, range(1, 13)) + _monthly(2025, range(1, 13))
    stats = TimesheetAnalytics.calculate_statistics(
        records, breakdown_by_year=True,
        period=(datetime(2024, 1, 1), datetime(2025, 12, 31, 23, 59, 59)))

    report = TimesheetAnalytics.format_statistics_report(stats)

    assert "partial" not in stats["years"]["2024"]
    assert "2024 → 2025**: +0h (+0.0%)" in report


# --- offsets are rejected wherever /timesheets is read -----------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["2026-10-01T00:00:00Z", "2026-10-01T00:00:00+02:00"])
async def test_timer_recent_rejects_an_offset(value):
    client = AsyncMock(spec=KimaiClient)
    with pytest.raises(ToolError, match="without an offset"):
        await ts.handle_timer(client, action="recent", begin=value)
    client.get_recent_timesheets.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_project_team_rejects_an_offset():
    client = AsyncMock(spec=KimaiClient)
    with pytest.raises(ToolError, match="without an offset"):
        await handle_analyze_project_team(client, {
            "project_name": "X", "begin": "2026-01-01T00:00:00Z", "end": "2026-06-30"})
    client.get_timesheets.assert_not_awaited()


# --- absences ----------------------------------------------------------------

def test_half_days_count_half_and_no_fixed_hours_per_day():
    user = User(id=1, username="alice", enabled=True)
    day = datetime(2026, 9, 1)
    absences = [
        Absence(user=user, date=day, type="holiday"),
        Absence(user=user, date=day + timedelta(days=1), type="holiday", halfDay=True),
        # A 6h entry used to come out as 0.75 days; it is counted in hours only.
        Absence(user=user, date=day + timedelta(days=2), type="other", duration=21600),
    ]

    stats = AbsenceAnalytics.calculate_statistics(absences)

    assert stats["by_type"]["holiday"]["days"] == 1.5
    assert stats["by_type"]["other"]["days"] == 0
    assert stats["by_type"]["other"]["hours"] == 6.0
    assert stats["total_days"] == 1.5
    assert stats["total_hours"] == 6.0
