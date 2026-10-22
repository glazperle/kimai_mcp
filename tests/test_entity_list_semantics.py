"""Entity list filters mean what their names say."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from kimai_mcp.client import KimaiClient
from kimai_mcp.models import Invoice, Project
from kimai_mcp.tools.errors import ToolError
from kimai_mcp.tools.registry import dispatch_tool

_TZ = timezone.utc


def _project(id: int, start: tuple | None, end: tuple | None) -> Project:
    return Project(
        id=id, name=f"P{id}",
        start=datetime(*start, tzinfo=_TZ) if start else None,
        end=datetime(*end, tzinfo=_TZ) if end else None,
    )


@pytest.mark.asyncio
async def test_project_period_returns_every_project_running_in_it():
    """Kimai ANDs start/end as "running on the first day AND on the last day",
    which dropped every project that started or ended inside the period."""
    client = AsyncMock(spec=KimaiClient)
    client.get_projects.return_value = [
        _project(1, (2026, 3, 1), (2026, 6, 30)),   # inside
        _project(2, (2025, 1, 1), None),             # open-ended, spans it
        _project(3, (2025, 1, 1), (2025, 12, 31)),   # ended before
        _project(4, (2027, 1, 1), None),             # starts after
        _project(5, None, None),                     # no dates
    ]

    text = (await dispatch_tool(client, "entity", {
        "type": "project", "action": "list",
        "filters": {"begin": "2026-01-01T00:00:00", "end": "2026-12-31T00:00:00"},
    }))[0].text

    sent = client.get_projects.await_args.args[0]
    assert (sent.ignore_dates, sent.start, sent.end) == ("1", None, None)
    assert "Found 3 projects" in text
    for shown in ("(ID: 1)", "(ID: 2)", "(ID: 5)"):
        assert shown in text
    for hidden in ("(ID: 3)", "(ID: 4)"):
        assert hidden not in text


@pytest.mark.asyncio
async def test_tag_list_refuses_two_different_names():
    client = AsyncMock(spec=KimaiClient)
    with pytest.raises(ToolError, match="either 'name' or 'term'"):
        await dispatch_tool(client, "entity", {
            "type": "tag", "action": "list", "filters": {"name": "a", "term": "b"},
        })


@pytest.mark.asyncio
async def test_empty_meta_values_are_not_printed_as_none():
    client = AsyncMock(spec=KimaiClient)
    client.get_invoice.return_value = Invoice(
        id=1, invoiceNumber="R-1", customer={"id": 1, "name": "Acme"}, user={"id": 1, "username": "u"},
        createdAt="2026-10-01T10:00:00+0200", currency="EUR", metaFields=[{"name": "po", "value": None}],
    )

    text = (await dispatch_tool(client, "entity", {"type": "invoice", "action": "get", "id": 1}))[0].text

    assert "- po: (empty)" in text
    assert "None" not in text


@pytest.mark.asyncio
async def test_set_preferences_prints_empty_values_as_empty():
    from kimai_mcp.models import UserEntity

    client = AsyncMock(spec=KimaiClient)
    client.update_user_preferences.return_value = UserEntity(
        id=5, username="john", enabled=True,
        preferences=[{"name": "work_start_day", "value": None}, {"name": "holidays", "value": ""}],
    )

    text = (await dispatch_tool(client, "entity", {
        "type": "user", "action": "set_preferences", "id": 5, "preferences": [{"name": "holidays", "value": ""}],
    }))[0].text

    assert "None" not in text
    assert "- work_start_day: (empty)" in text
    assert "- holidays: (empty)" in text
