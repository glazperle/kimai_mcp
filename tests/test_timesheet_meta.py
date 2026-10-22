"""Timesheet meta fields in list/get output and the list meta filter."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

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
    client = AsyncMock()
    client.get_current_user.return_value = User(id=1, username="tester", enabled=True)
    client.get_timesheets.return_value = (timesheets, True, 1)
    return client


@pytest.mark.asyncio
async def test_list_shows_non_empty_meta_fields():
    client = _mock_client([_timesheet(101, "CA-376"), _timesheet(102, None)])

    text = (await _handle_timesheet_list(client, {}))[0].text

    entry_1, entry_2 = text.split("ID: 101 - ")[1].split("ID: 102 - ")
    assert "  Meta: issue_tracker_id=CA-376\n" in entry_1
    assert "Meta:" not in entry_2


@pytest.mark.asyncio
async def test_list_without_meta_fields_has_no_meta_line():
    ts = _timesheet(101, None).model_copy(update={"meta_fields": None})
    client = _mock_client([ts])

    text = (await _handle_timesheet_list(client, {}))[0].text

    assert "Meta" not in text


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
    assert "ID: 101 - " in text
    assert "ID: 104 - " in text
    assert "ID: 102 - " not in text


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
    assert "ID: 101 - " in text
    assert "ID: 102 - " not in text


@pytest.mark.asyncio
async def test_meta_filter_with_empty_value_matches_entries_without_one():
    client = _mock_client([_timesheet(101, "CA-376"), _timesheet(102, None)])

    text = (await _handle_timesheet_list(
        client, {"meta": {"name": "issue_tracker_id", "value": ""}}
    ))[0].text

    assert client.get_timesheets.await_args.args[0].term == 'issue_tracker_id:""'
    assert "ID: 101 - " not in text
    assert "ID: 102 - " in text


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
        ("issue_tracker_id", "", 'issue_tracker_id:""'),
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
