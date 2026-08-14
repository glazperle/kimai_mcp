"""Regression tests for expanded timesheet responses (issue #24).

``GET /timesheets/active`` and ``GET /timesheets/recent`` are declared as
``TimesheetCollectionExpanded`` in Kimai's ``src/API/TimesheetController.php``.
That schema carries the ``Expanded`` serializer group, so ``project``,
``activity`` and ``user`` arrive as objects rather than ids -- and the
expansion is recursive: the project carries its customer, and the activity
carries a project which in turn carries that customer.

The payload below mirrors the shape of a real 2.57 response (values replaced).
"""

from unittest.mock import AsyncMock

import pytest

from kimai_mcp.models import TimesheetEntity, TimesheetExpanded
from kimai_mcp.tools.timesheet_consolidated import _handle_timer_active

_CUSTOMER = {
    "id": 16,
    "name": "Acme GmbH",
    "number": None,
    "comment": None,
    "visible": True,
    "billable": True,
    "company": None,
    "country": "DE",
    "currency": "EUR",
    "phone": None,
    "fax": None,
    "mobile": None,
    "homepage": None,
    "timezone": "Europe/Berlin",
    "metaFields": [],
    "color": None,
    "color-safe": "#39CCCC",
}

_PROJECT = {
    "id": 25,
    "name": "Website Relaunch",
    "customer": _CUSTOMER,
    "orderNumber": None,
    "orderDate": None,
    "start": None,
    "end": None,
    "comment": None,
    "visible": True,
    "billable": True,
    "metaFields": [],
    "globalActivities": False,
    "number": None,
    "color": None,
    "color-safe": "#DDDDDD",
}

_ACTIVITY = {
    "id": 11,
    "name": "Development",
    "project": _PROJECT,
    "comment": None,
    "visible": True,
    "billable": True,
    "metaFields": [],
    "number": None,
    "color": None,
    "color-safe": "#b60205",
}

_USER = {
    "id": 1,
    "username": "tester",
    "alias": None,
    "title": None,
    "enabled": True,
    "color": None,
    "email": "tester@example.com",
    "accountNumber": None,
    "avatar": None,
    "systemAccount": False,
    "initials": "T",
    "language": "en",
    "locale": "en",
    "timezone": "Europe/Berlin",
    "apiToken": False,
    "color-safe": "#111111",
}

ACTIVE_PAYLOAD = {
    "id": 1288,
    "begin": "2026-08-13T18:56:00-0500",
    "end": None,
    "duration": 0,
    "break": 0,
    "description": "Sorting columns",
    "rate": 0.0,
    "internalRate": 0.0,
    "exported": False,
    "billable": True,
    "tags": [],
    "metaFields": [],
    "user": _USER,
    "activity": _ACTIVITY,
    "project": _PROJECT,
}

# What the plain collection endpoint (``Not_Expanded``) sends for the same row.
COLLECTION_PAYLOAD = {
    **ACTIVE_PAYLOAD,
    "user": 1,
    "activity": 11,
    "project": 25,
}


def test_expanded_payload_parses():
    """Regression for #24: the expanded response must deserialize."""
    ts = TimesheetExpanded(**ACTIVE_PAYLOAD)

    assert ts.id == 1288
    assert ts.project.id == 25
    assert ts.project.name == "Website Relaunch"
    assert ts.activity.id == 11
    assert ts.activity.name == "Development"
    assert ts.user.id == 1
    assert ts.user.username == "tester"


def test_expansion_is_recursive():
    """The nested customer and the activity's own project also arrive expanded."""
    ts = TimesheetExpanded(**ACTIVE_PAYLOAD)

    assert ts.project.customer.id == 16
    assert ts.project.customer.name == "Acme GmbH"
    assert ts.activity.project.id == 25
    assert ts.activity.project.customer.name == "Acme GmbH"


def test_collection_payload_still_parses_as_scalars():
    """The ``Not_Expanded`` endpoints are unchanged and keep their int relations."""
    ts = TimesheetEntity(**COLLECTION_PAYLOAD)

    assert ts.project == 25
    assert ts.activity == 11
    assert ts.user == 1


@pytest.mark.asyncio
async def test_active_handler_reports_names_not_ids():
    """The expanded model lets the timer output name the project and activity."""
    client = AsyncMock()
    client.get_active_timesheets.return_value = [TimesheetExpanded(**ACTIVE_PAYLOAD)]

    result = await _handle_timer_active(client)

    text = result[0].text
    assert "Website Relaunch" in text
    assert "Development" in text
    assert "Acme GmbH" in text


@pytest.mark.asyncio
async def test_active_handler_without_timers():
    """No active timer is not an error."""
    client = AsyncMock()
    client.get_active_timesheets.return_value = []

    result = await _handle_timer_active(client)

    assert "No active timers running" in result[0].text
