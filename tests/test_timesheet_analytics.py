"""Timesheet statistics must not invent a working-time balance (issue #30).

The former ``tracked_days * 8h`` figure ignored the work contract and could
never go negative. The stats now carry a note pointing to Kimai instead.
"""

import json
import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from kimai_mcp.client import KimaiClient
from kimai_mcp.models import TimesheetEntity
from kimai_mcp.tools import timesheet_consolidated as ts
from kimai_mcp.tools.timesheet_analytics import WORKING_TIME_NOTE, TimesheetAnalytics

_ESTIMATE = re.compile(r"overtime|balance|expected", re.IGNORECASE)


def _timesheets() -> list[TimesheetEntity]:
    # 10h on one day: the old code reported "2 hours overtime" for any contract.
    begin = datetime(2026, 9, 1, 8, tzinfo=timezone.utc)
    return [TimesheetEntity(
        id=1, project=1, activity=1, user=1,
        begin=begin, end=begin.replace(hour=18), duration=36000,
    )]


def test_stats_carry_no_balance_estimate():
    stats = TimesheetAnalytics.calculate_statistics(_timesheets())

    assert stats["working_time_balance"] is None
    assert stats["working_time_note"] == WORKING_TIME_NOTE
    assert not [k for k in stats if _ESTIMATE.search(k) and k != "working_time_balance"]

    report = TimesheetAnalytics.format_statistics_report(stats)
    assert WORKING_TIME_NOTE in report
    assert not _ESTIMATE.search(report.replace(WORKING_TIME_NOTE, ""))


@pytest.mark.asyncio
@pytest.mark.parametrize("stats_format", ["json", "summary", None])
async def test_every_stats_format_carries_the_note(stats_format):
    client = AsyncMock(spec=KimaiClient)
    client.get_timesheets.return_value = (_timesheets(), True, 1)
    client.get_projects.return_value = []
    filters = {"user_scope": "self", "calculate_stats": True}
    if stats_format:
        filters["stats_format"] = stats_format

    text = (await ts.handle_timesheet(client, action="list", filters=filters))[0].text

    if stats_format == "json":
        stats, _ = json.JSONDecoder().raw_decode(text.split("## Statistics (JSON):\n", 1)[1])
        assert stats["working_time_balance"] is None
        assert stats["working_time_note"] == WORKING_TIME_NOTE
    else:
        assert WORKING_TIME_NOTE in text
        # Summary is the default: no per-record listing after the report.
        assert "ID: 1" not in text
