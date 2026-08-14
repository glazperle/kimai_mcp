"""Regression tests for project date handling.

``ProjectEditForm`` and ``ProjectFilter`` declare ``start``/``end`` as ``str``
("Format: YYYY-MM-DD"), but the client called ``.isoformat()`` on them, which
raises ``AttributeError: 'str' object has no attribute 'isoformat'``. That made
every project create/update carrying a date, and every project listing filtered
by date, fail outright.

``model_dump()`` already places those strings in the payload, so the isoformat
blocks were both wrong and redundant.
"""

from unittest.mock import AsyncMock

import pytest

from kimai_mcp.client import KimaiClient
from kimai_mcp.models import ProjectEditForm, ProjectFilter


def _client(return_value) -> KimaiClient:
    client = KimaiClient(base_url="https://kimai.example.com", api_token="token")
    client._request = AsyncMock(return_value=return_value)
    return client


@pytest.mark.asyncio
async def test_create_project_with_dates():
    """A project created with start/end must not raise, and must send them as-is."""
    client = _client({"id": 27, "name": "Website Relaunch"})

    await client.create_project(
        ProjectEditForm(name="Website Relaunch", customer=4, start="2026-08-17")
    )

    payload = client._request.await_args.kwargs["json"]
    assert payload["start"] == "2026-08-17"
    assert payload["name"] == "Website Relaunch"
    assert payload["customer"] == 4


@pytest.mark.asyncio
async def test_update_project_with_end_date():
    """Closing a project sets end + visible; this is the call that first failed."""
    client = _client({"id": 17, "name": "Website Relaunch"})

    await client.update_project(
        17, ProjectEditForm(end="2026-08-16T23:59:59", visible=False)
    )

    payload = client._request.await_args.kwargs["json"]
    assert payload["end"] == "2026-08-16T23:59:59"
    assert payload["visible"] is False


@pytest.mark.asyncio
async def test_get_projects_with_date_filter():
    """Listing projects filtered by date hit the same defect."""
    client = _client([{"id": 27, "name": "Website Relaunch"}])

    await client.get_projects(ProjectFilter(start="2026-08-01", end="2026-08-31"))

    params = client._request.await_args.kwargs["params"]
    assert params["start"] == "2026-08-01"
    assert params["end"] == "2026-08-31"


@pytest.mark.asyncio
async def test_project_dates_are_optional():
    """Omitting the dates keeps them out of the payload entirely."""
    client = _client({"id": 28, "name": "No Dates"})

    await client.create_project(ProjectEditForm(name="No Dates", customer=4))

    payload = client._request.await_args.kwargs["json"]
    assert "start" not in payload
    assert "end" not in payload
