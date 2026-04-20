"""Regression tests for timesheet list handler (issue #12)."""

from unittest.mock import AsyncMock

import pytest

from kimai_mcp.models import User
from kimai_mcp.tools.timesheet_consolidated import _handle_timesheet_list


def _mock_client() -> AsyncMock:
    client = AsyncMock()
    client.get_current_user.return_value = User(id=1, username="tester", enabled=True)
    client.get_timesheets.return_value = ([], True, None)
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filters",
    [
        {},
        {"user_scope": "self", "size": 5},
        {"project": 1},
    ],
)
async def test_list_without_date_filters_does_not_raise(filters):
    """Regression for #12: list must not crash when begin/end are absent."""
    client = _mock_client()

    result = await _handle_timesheet_list(client, filters)

    assert result and result[0].type == "text"
    timesheet_filter = client.get_timesheets.await_args.args[0]
    assert timesheet_filter.begin is None
    assert timesheet_filter.end is None


@pytest.mark.asyncio
async def test_list_expands_same_day_midnight_range():
    """When begin == end at midnight, end is bumped by one day (pre-existing behavior)."""
    client = _mock_client()

    await _handle_timesheet_list(
        client,
        {"begin": "2026-01-15T00:00:00", "end": "2026-01-15T00:00:00"},
    )

    timesheet_filter = client.get_timesheets.await_args.args[0]
    assert timesheet_filter.begin.isoformat() == "2026-01-15T00:00:00"
    assert timesheet_filter.end.isoformat() == "2026-01-16T00:00:00"
