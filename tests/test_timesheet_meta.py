"""Timesheet meta fields in list/get output and the list meta filter.

Kimai serializes the stored, visible meta rows only: a record saved before a
field existed, or while it was hidden, arrives without the field.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from kimai_mcp.client import TimesheetPage
from kimai_mcp.models import TimesheetEntity, User
from kimai_mcp.tools.timesheet_consolidated import (
    _handle_timesheet_get,
    _handle_timesheet_list,
    _meta_search_term,
)


def _timesheet(id: int, issue: str | None) -> TimesheetEntity:
    # Kimai serializes every visible meta field definition, so an entry without
    # a value still carries the field with value null.
    return TimesheetEntity(
        id=id,
        project=1,
        activity=1,
        user=1,
        begin=datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc),
        metaFields=[{"name": "issue_tracker_id", "value": issue}],
    )


def _mock_client(timesheets: list[TimesheetEntity]) -> AsyncMock:
    """The listing reads one page; statistics and the meta filter read everything."""
    client = AsyncMock()
    client.get_current_user.return_value = User(id=1, username="tester", enabled=True)
    client.get_timesheets.return_value = (timesheets, True)
    client.get_timesheet_page.return_value = TimesheetPage(
        rows=timesheets, page=1, size=50, total=len(timesheets), total_pages=1
    )
    return client


@pytest.mark.asyncio
async def test_list_shows_non_empty_meta_fields():
    client = _mock_client([_timesheet(101, "CA-376"), _timesheet(102, None)])

    text = (await _handle_timesheet_list(client, {}))[0].text

    entry_1, entry_2 = text.split("#101 ")[1].split("#102 ")
    assert "  meta: issue_tracker_id=CA-376\n" in entry_1
    assert "meta:" not in entry_2


@pytest.mark.asyncio
async def test_list_without_meta_fields_has_no_meta_line():
    ts = _timesheet(101, None).model_copy(update={"meta_fields": None})
    client = _mock_client([ts])

    text = (await _handle_timesheet_list(client, {}))[0].text

    assert "meta" not in text.lower()


@pytest.mark.asyncio
async def test_get_shows_meta_fields():
    client = AsyncMock()
    client.get_timesheet.return_value = _timesheet(101, "CA-376")

    text = (await _handle_timesheet_get(client, 1))[0].text

    assert "Meta: issue_tracker_id=CA-376\n" in text


@pytest.mark.asyncio
async def test_get_without_meta_value_has_no_meta_line():
    client = AsyncMock()
    client.get_timesheet.return_value = _timesheet(101, None)

    text = (await _handle_timesheet_get(client, 1))[0].text

    assert "Meta" not in text


@pytest.mark.asyncio
async def test_meta_filter_is_sent_as_search_term_and_matched_exactly():
    """Kimai matches name:value with LIKE, so CA-3760 comes back for CA-376."""
    client = _mock_client([_timesheet(101, "CA-376"), _timesheet(102, "CA-3760"), _timesheet(104, "ca-376")])

    text = (await _handle_timesheet_list(
        client, {"meta": {"name": "issue_tracker_id", "value": "CA-376"}}
    ))[0].text

    assert client.get_timesheets.await_args.args[0].term == "issue_tracker_id:CA-376"
    assert text.startswith("Found 2 timesheets")
    assert "#101 " in text
    assert "#104 " in text
    assert "#102 " not in text


@pytest.mark.asyncio
async def test_meta_filter_is_combined_with_free_term():
    client = _mock_client([])

    await _handle_timesheet_list(
        client, {"term": "login", "meta": {"name": "issue_tracker_id", "value": "CA-376"}}
    )

    assert client.get_timesheets.await_args.args[0].term == "login issue_tracker_id:CA-376"


@pytest.mark.asyncio
async def test_meta_filter_without_value_matches_any_value():
    client = _mock_client([_timesheet(101, "CA-376"), _timesheet(102, None)])

    text = (await _handle_timesheet_list(client, {"meta": {"name": "issue_tracker_id"}}))[0].text

    assert client.get_timesheets.await_args.args[0].term == "issue_tracker_id:*"
    assert "#101 " in text
    assert "#102 " not in text


@pytest.mark.asyncio
async def test_meta_filter_with_empty_value_matches_entries_without_one():
    """Kimai's name:"" means "IS NULL or missing", which misses a value cleared to
    '' (all meta_update can store), so no server term is sent for it."""
    client = _mock_client([_timesheet(101, "CA-376"), _timesheet(102, None), _timesheet(103, "")])

    text = (await _handle_timesheet_list(
        client, {"meta": {"name": "issue_tracker_id", "value": ""}}
    ))[0].text

    assert client.get_timesheets.await_args.args[0].term is None
    assert "#101 " not in text
    assert "#102 " in text
    assert "#103 " in text


@pytest.mark.asyncio
async def test_meta_filter_requires_name():
    from kimai_mcp.tools.errors import ToolError

    with pytest.raises(ToolError):
        await _handle_timesheet_list(_mock_client([]), {"meta": {"value": "CA-376"}})


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("issue_tracker_id", "CA-376", "issue_tracker_id:CA-376"),
        ("issue_tracker_id", None, "issue_tracker_id:*"),
        ("issue_tracker_id", "", None),
        # A backslash is MySQL's LIKE escape character and Kimai does not escape it.
        ("issue_tracker_id", r"C:\temp", "issue_tracker_id:*"),
        # Not expressible in Kimai's term syntax: pre-filter on "has a value",
        # the exact match still happens client-side.
        ("issue_tracker_id", "two words", "issue_tracker_id:*"),
        ("issue_tracker_id", "!negated", "issue_tracker_id:*"),
        ("issue_tracker_id", "*", "issue_tracker_id:*"),
        ("bad name", "x", None),
        ("bad:name", "x", None),
    ],
)
def test_meta_search_term(name, value, expected):
    assert _meta_search_term(name, value) == expected


@pytest.mark.asyncio
async def test_meta_filter_matches_exactly_across_pages():
    """Kimai paginates its LIKE pre-filter; with an explicit page, a page full of
    near-misses used to hide the exact matches further on ("Found 0")."""
    near_misses = [_timesheet(200 + i, f"CA-1{i:02d}") for i in range(50)]
    exact = [_timesheet(301, "CA-1"), _timesheet(302, "CA-1")]
    client = _mock_client(near_misses + exact)

    text = (await _handle_timesheet_list(
        client, {"page": 1, "meta": {"name": "issue_tracker_id", "value": "CA-1"}}
    ))[0].text

    assert text.startswith("Found 2 timesheets")
    assert "#301 " in text
    assert "#302 " in text


def _without_row(id: int) -> TimesheetEntity:
    """A record Kimai sends without the field: saved before the field existed,
    or saved while it was hidden (Kimai serializes stored, visible rows only)."""
    return _timesheet(id, None).model_copy(update={"meta_fields": []})


@pytest.mark.asyncio
async def test_meta_filter_compares_names_case_insensitively():
    """With a case-sensitive name comparison every record would look like one
    without the field and be kept unchecked, CA-3760 included."""
    client = _mock_client([_timesheet(101, "CA-376"), _timesheet(102, "CA-3760")])

    text = (await _handle_timesheet_list(
        client, {"meta": {"name": "Issue_Tracker_Id", "value": "ca-376"}}
    ))[0].text

    assert "#101 " in text
    assert "#102 " not in text


@pytest.mark.asyncio
async def test_records_without_the_field_that_kimai_matched_are_kept_with_a_note():
    """Kimai's search also matches rows saved while the field was hidden; they
    are not sent back, so they are kept unchecked rather than silently dropped
    because another record does carry the field."""
    client = _mock_client([_timesheet(101, "CA-376"), _without_row(102)])

    text = (await _handle_timesheet_list(
        client, {"meta": {"name": "issue_tracker_id", "value": "CA-376"}}
    ))[0].text

    assert "#101 " in text
    assert "#102 " in text
    assert "1 of these matched Kimai's substring search on a hidden 'issue_tracker_id'" in text


@pytest.mark.asyncio
async def test_an_empty_search_includes_records_without_the_field():
    """Kimai's own name:"" is IS NULL OR NOT EXISTS: a record saved before the
    field existed has no value. It used to be dropped, or raised an error."""
    client = _mock_client([_timesheet(101, None), _without_row(102), _timesheet(103, "CA-1")])

    text = (await _handle_timesheet_list(
        client, {"meta": {"name": "issue_tracker_id", "value": ""}}
    ))[0].text

    assert text.startswith("Found 2 timesheets")
    assert "#103 " not in text


@pytest.mark.asyncio
async def test_records_without_the_field_are_dropped_when_kimai_did_not_match_the_value():
    """A value Kimai's term cannot express falls back to name:* (any value), so
    a record without a visible row says nothing about this value."""
    client = _mock_client([_timesheet(101, "two words"), _without_row(102)])

    text = (await _handle_timesheet_list(
        client, {"meta": {"name": "issue_tracker_id", "value": "two words"}}
    ))[0].text

    assert "#101 " in text
    assert "#102 " not in text


@pytest.mark.asyncio
async def test_a_meta_search_fetches_in_pages_of_500():
    """Matching needs the whole result; 50-record pages made that 10x slower."""
    client = _mock_client([_timesheet(101, "CA-1")])

    await _handle_timesheet_list(client, {"page": 3, "meta": {"name": "issue_tracker_id", "value": "CA-1"}})

    assert client.get_timesheets.await_args.args[0].size == 500


@pytest.mark.asyncio
async def test_records_of_other_users_than_requested_are_flagged():
    """Without view_other_timesheet Kimai ignores users[] and returns the caller's
    own records; the header must not present them as the requested users'."""
    client = _mock_client([_timesheet(101, None)])  # user 1, the caller

    text = (await _handle_timesheet_list(client, {"users": [7, 9]}))[0].text

    assert "Warning: Kimai returned records of user(s) 1" in text


@pytest.mark.asyncio
async def test_foreign_records_are_flagged_before_the_meta_match_narrows_them():
    """Kimai returned the caller's own records for users=[7]; the meta match
    then drops them all, which must not read as "user 7 has none"."""
    client = _mock_client([_timesheet(101, "CA-10")])  # user 1

    text = (await _handle_timesheet_list(
        client, {"users": [7], "meta": {"name": "issue_tracker_id", "value": "CA-1"}}
    ))[0].text

    assert text.startswith("Found 0 timesheets")
    assert "Warning: Kimai returned records of user(s) 1" in text


@pytest.mark.asyncio
async def test_a_date_only_end_includes_that_day():
    """Kimai keeps records started at or before `end`; a date-only end parsed
    as midnight dropped the whole last day."""
    client = _mock_client([])

    await _handle_timesheet_list(client, {"begin": "2025-06-01", "end": "2025-06-30"})

    sent = client.get_timesheet_page.await_args.args[0]
    assert sent.end.isoformat() == "2025-06-30T23:59:59"


@pytest.mark.asyncio
async def test_an_empty_search_notes_the_records_without_the_field():
    """A record without the field may be empty (no row) or hold a hidden value."""
    client = _mock_client([_without_row(101), _without_row(102)])

    text = (await _handle_timesheet_list(client, {"meta": {"name": "internal_ref", "value": ""}}))[0].text

    assert text.startswith("Found 2 timesheets")
    assert "2 of these have no visible value for 'internal_ref'" in text


@pytest.mark.asyncio
async def test_an_unexpressible_value_leaves_hidden_records_out_with_a_note():
    client = _mock_client([_without_row(101)])

    text = (await _handle_timesheet_list(client, {"meta": {"name": "internal_ref", "value": "two words"}}))[0].text

    assert text.startswith("Found 0 timesheets")
    assert "1 record(s) with a hidden 'internal_ref' were left out" in text


@pytest.mark.asyncio
async def test_an_any_value_search_says_a_hidden_value_may_be_empty():
    client = _mock_client([_without_row(101)])

    text = (await _handle_timesheet_list(client, {"meta": {"name": "internal_ref"}}))[0].text

    assert "#101 " in text
    assert "which may be empty" in text
    assert "substring" not in text


@pytest.mark.asyncio
async def test_all_scope_with_only_own_records_is_noted():
    """Without view_other_timesheet Kimai answers user=all with the caller's records."""
    client = _mock_client([_timesheet(101, None), _timesheet(102, None)])  # both user 1, the caller

    text = (await _handle_timesheet_list(client, {"user_scope": "all"}))[0].text

    assert "every record returned is your own" in text


@pytest.mark.asyncio
async def test_records_of_unrequested_projects_are_flagged():
    """Kimai drops unknown project IDs and then does not filter by project."""
    client = _mock_client([_timesheet(101, None)])  # project 1

    text = (await _handle_timesheet_list(client, {"project": 99999}))[0].text

    assert "Warning: Kimai returned records of project ID(s) 1" in text


def test_negative_pages_are_rejected_by_the_schema():
    from kimai_mcp.tools.errors import ToolError
    from kimai_mcp.tools.registry import all_tools, validate_arguments

    tool = next(t for t in all_tools() if t.name == "timesheet")
    with pytest.raises(ToolError, match="minimum"):
        validate_arguments(tool, {"action": "list", "filters": {"page": -1}})


@pytest.mark.asyncio
async def test_records_of_unrequested_activities_are_flagged():
    client = _mock_client([_timesheet(101, None)])  # activity 1

    text = (await _handle_timesheet_list(client, {"activity": 0}))[0].text

    assert "Warning: Kimai returned records of activity ID(s) 1" in text


@pytest.mark.asyncio
async def test_a_meta_name_kimai_cannot_search_is_said_so():
    """'Issue Ref' (a UI label) cannot be a search term, so Kimai was not asked
    at all; counting every record without the field as 'hidden' would claim
    thousands of hidden values instead of naming the actual problem."""
    client = _mock_client([_without_row(101), _without_row(102)])

    text = (await _handle_timesheet_list(client, {"meta": {"name": "Issue Ref", "value": "X"}}))[0].text

    assert text.startswith("Found 0 timesheets")
    assert "cannot address a meta field named 'Issue Ref'" in text
    assert "hidden" not in text


@pytest.mark.asyncio
async def test_an_integral_float_page_does_not_break_the_slice():
    client = _mock_client([_timesheet(101, "CA-1")])

    text = (await _handle_timesheet_list(client, {"page": 1.0, "meta": {"name": "issue_tracker_id", "value": "CA-1"}}))[0].text

    assert "#101 " in text


@pytest.mark.asyncio
async def test_the_listing_reads_one_page_of_the_requested_size():
    """Without 'page' the listing used to fetch every page and ignore 'size'."""
    client = _mock_client([])
    client.get_timesheet_page.return_value = TimesheetPage(
        rows=[_timesheet(101 + i, None) for i in range(5)], page=3, size=5, total=23, total_pages=5
    )

    text = (await _handle_timesheet_list(client, {"page": 3, "size": 5}))[0].text

    sent = client.get_timesheet_page.await_args.args[0]
    assert (sent.page, sent.size, sent.full) == (3, 5, "true")
    client.get_timesheets.assert_not_awaited()
    assert text.startswith("Found 23 timesheets for current user, showing 11-15")
    assert "use 'page' 4" in text


@pytest.mark.asyncio
async def test_the_last_page_has_no_next_page_hint():
    client = _mock_client([_timesheet(101, None)])

    text = (await _handle_timesheet_list(client, {}))[0].text

    assert text.startswith("Found 1 timesheets for current user\n")
    assert "use 'page'" not in text


@pytest.mark.asyncio
async def test_without_pagination_headers_a_full_page_offers_the_next():
    client = _mock_client([])
    client.get_timesheet_page.return_value = TimesheetPage(rows=[_timesheet(101, None)], page=1, size=1)

    text = (await _handle_timesheet_list(client, {"size": 1}))[0].text

    assert text.startswith("Found 1 timesheets for current user on page 1")
    assert "use 'page' 2" in text


@pytest.mark.asyncio
async def test_a_page_past_the_end_is_said_so():
    from kimai_mcp.client import KimaiAPIError

    client = _mock_client([])
    client.get_timesheet_page.side_effect = KimaiAPIError("Not Found", 404)

    text = (await _handle_timesheet_list(client, {"page": 9}))[0].text

    assert "Page 9 is past the last page" in text


@pytest.mark.asyncio
async def test_meta_matches_are_paged_by_size():
    client = _mock_client([_timesheet(101 + i, "CA-1") for i in range(3)])

    text = (await _handle_timesheet_list(
        client, {"size": 2, "page": 2, "meta": {"name": "issue_tracker_id", "value": "CA-1"}}
    ))[0].text

    assert text.startswith("Found 3 timesheets for current user, showing 3-3")
    assert "#103 " in text
    assert "#101 " not in text
    assert "use 'page'" not in text


@pytest.mark.asyncio
async def test_several_requested_users_returning_only_the_callers_records_are_noted():
    """users=[5, 1] for caller 1 without view_other_timesheet: Kimai returns the
    caller's records only, and nothing in them is 'foreign'."""
    client = _mock_client([_timesheet(101, None)])  # user 1, the caller

    text = (await _handle_timesheet_list(client, {"users": [5, 1]}))[0].text

    assert "every record returned is your own" in text
