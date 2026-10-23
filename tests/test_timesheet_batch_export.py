"""timesheet action=batch_export must never un-export a record.

Kimai's PATCH /timesheets/{id}/export toggles the flag, so calling it for a
record that is exported already flips it back. batch_export ("mark as
exported") used to do exactly that for every exported record in the batch.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from kimai_mcp.client import KimaiAPIError, KimaiClient
from kimai_mcp.models import TimesheetEntity
from kimai_mcp.tools.registry import dispatch_tool


def _timesheet(id: int, exported: bool) -> TimesheetEntity:
    return TimesheetEntity(
        id=id, project=1, activity=1, user=1, exported=exported,
        begin=datetime(2026, 10, 20, 9, tzinfo=timezone.utc),
        end=datetime(2026, 10, 20, 10, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_batch_export_toggles_only_records_that_are_not_exported():
    client = AsyncMock(spec=KimaiClient)

    async def get_timesheet(id):
        if id == 3:
            raise KimaiAPIError("Not found", 404)
        return _timesheet(id, exported=(id == 1))

    client.get_timesheet.side_effect = get_timesheet

    content = await dispatch_tool(client, "timesheet", {"action": "batch_export", "ids": [1, 2, 3]})
    text = content[0].text

    toggled = [call.args[0] for call in client.toggle_timesheet_export.await_args_list]
    assert toggled == [2]
    assert "Exported: 1 timesheets" in text
    assert "Already exported, left unchanged: 1" in text
    assert "Failed: 1" in text


@pytest.mark.asyncio
async def test_batch_export_toggles_a_repeated_id_once():
    """The batch runs concurrently: both reads of a repeated id saw "not exported"
    and the second toggle undid the first, while the result said "Exported: 2"."""
    client = AsyncMock(spec=KimaiClient)
    client.get_timesheet.return_value = _timesheet(5, exported=False)

    content = await dispatch_tool(client, "timesheet", {"action": "batch_export", "ids": [5, 5]})

    assert client.toggle_timesheet_export.await_count == 1
    assert "Exported: 1 timesheets" in content[0].text



@pytest.mark.asyncio
async def test_a_float_twin_does_not_replace_the_real_id():
    """JSON Schema accepts 1.0 as an integer; deduplicating must keep the int."""
    client = AsyncMock(spec=KimaiClient)

    await dispatch_tool(client, "timesheet", {"action": "batch_delete", "ids": [1.0, 1]})

    sent = [call.args[0] for call in client.delete_timesheet.await_args_list]
    assert sent == [1]
    assert type(sent[0]) is int  # 1.0 == 1, so the equality alone cannot fail
