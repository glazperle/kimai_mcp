"""Kimai 2.66.0 API changes (kimai/kimai 2.65.0...2.66.0, read 2026-09-05).

Four things changed for API clients:

* Timesheet ``rate`` / ``internalRate`` (group ``Timesheet_Rate``) and
  ``fixedRate`` / ``hourlyRate`` (``Timesheet_Entity_Rate``) are now stripped
  **per record** by ``RateExclusionStrategy`` unless the token holds
  ``view_rate_own_timesheet`` resp. ``view_rate_other_timesheet``. The default
  ``ROLE_USER`` has neither, so a missing ``rate`` is the normal case, not an
  error - and it must not be reported as a zero rate (#6139).
* ``budget`` / ``timeBudget`` / ``budgetType`` left the ``*_Entity`` groups for
  ``Budget_Money`` / ``Budget_Time`` and are now part of the customer, project
  and activity **collection** responses too, again per record and gated by the
  ``budget`` resp. ``time`` permission (#6140).
* Project gained ``lockedUntil`` (``Y-m-d``, group ``Default``): timesheets
  beginning on or before that day are refused by ``TimesheetVoter`` (403) or
  ``TimesheetProjectLockedValidator`` (400, "The project is locked until
  %date%"). Writable through the same ``date_format``-bound form as
  ``start``/``end`` (#6103).
* New endpoints: ``DELETE /api/invoices/{id}`` (#6141) and the favorites
  ``GET|POST|DELETE /api/favorites/timesheets[/{id}]`` (#6143).
"""

from unittest.mock import AsyncMock

import pytest

from kimai_mcp.client import KimaiAPIError, KimaiClient
from kimai_mcp.models import (
    Project,
    ProjectEditForm,
    TimesheetEntity,
    TimesheetExpanded,
)
from kimai_mcp.server import format_api_error
from kimai_mcp.tools import timesheet_consolidated
from kimai_mcp.tools.entity_manager import (
    InvoiceEntityHandler,
    ProjectEntityHandler,
    entity_tool,
)
from kimai_mcp.tools.registry import validate_arguments
from tests.schema_helpers import entity_data_schema

# A timesheet as a plain ROLE_USER token receives it from 2.66 on: no rate keys.
RATELESS_TIMESHEET = {
    "id": 77,
    "activity": 1,
    "project": 2,
    "user": 3,
    "begin": "2026-09-01T09:00:00+0200",
    "end": "2026-09-01T10:00:00+0200",
    "duration": 3600,
    "description": "no rates for you",
    "tags": [],
    "exported": False,
    "billable": True,
    "metaFields": [],
}


def _client(return_value) -> KimaiClient:
    client = KimaiClient(base_url="https://kimai.example.com", api_token="token")
    client._request = AsyncMock(return_value=return_value)
    return client


# --- rates are optional per record -----------------------------------------

def test_rateless_timesheet_parses_with_rate_none_not_zero():
    ts = TimesheetEntity(**RATELESS_TIMESHEET)
    assert ts.rate is None
    assert ts.internal_rate is None
    assert ts.fixed_rate is None
    assert ts.hourly_rate is None


def test_rate_zero_is_still_a_zero():
    """A visible zero rate must stay distinguishable from a stripped one."""
    ts = TimesheetEntity(**RATELESS_TIMESHEET, rate=0.0, internalRate=0.0)
    assert ts.rate == 0.0
    assert ts.fixed_rate is None  # entity-only group, not sent on collections


@pytest.mark.asyncio
async def test_timesheet_get_explains_missing_rates():
    client = AsyncMock(spec=KimaiClient)
    client.get_timesheet.return_value = TimesheetEntity(**RATELESS_TIMESHEET)

    [content] = await timesheet_consolidated.handle_timesheet(client, action="get", id=77)

    assert "Rates: not visible to this token" in content.text
    assert "view_rate_own_timesheet" in content.text
    assert "Rate: " not in content.text.replace("Rates: ", "")


@pytest.mark.asyncio
async def test_timesheet_get_with_visible_rates_gets_no_hint():
    client = AsyncMock(spec=KimaiClient)
    client.get_timesheet.return_value = TimesheetEntity(
        **RATELESS_TIMESHEET, rate=80.0, hourlyRate=80.0
    )

    [content] = await timesheet_consolidated.handle_timesheet(client, action="get", id=77)

    assert "not visible" not in content.text
    assert "Rate: 80.0" in content.text
    assert "Hourly Rate: 80.0" in content.text


@pytest.mark.asyncio
async def test_timesheet_get_with_only_a_zero_rate_gets_no_hint():
    """``rate: 0.0`` present means the permission is there; the value is zero
    and has to be printed, otherwise a visible zero looks like a stripped field."""
    client = AsyncMock(spec=KimaiClient)
    client.get_timesheet.return_value = TimesheetEntity(
        **RATELESS_TIMESHEET, rate=0.0, internalRate=40.0
    )

    [content] = await timesheet_consolidated.handle_timesheet(client, action="get", id=77)

    assert "not visible" not in content.text
    assert "Rate: 0.0" in content.text
    assert "Internal Rate: 40.0" in content.text


# --- budget fields now appear in collections -------------------------------

def test_project_listing_row_with_budget_parses_and_renders():
    """2.66 sends the budget on ``GET /projects`` for permitted records."""
    row = Project(
        id=1, name="P", customer=2, parentTitle="Acme",
        budget=1000.0, timeBudget=7200, budgetType=None,
    )
    text = ProjectEntityHandler(client=None).serialize_project(row)
    assert "Time Budget: 2.00 hours (7200 seconds)" in text


def test_project_listing_row_without_budget_stays_silent():
    """Absent budget = no permission; the serializer must not invent zeros."""
    text = ProjectEntityHandler(client=None).serialize_project(
        Project(id=1, name="P", customer=2)
    )
    assert "Budget" not in text


# --- project lockedUntil ---------------------------------------------------

def test_project_parses_locked_until_as_a_calendar_day():
    project = Project(id=1, name="P", customer=2, lockedUntil="2026-08-31")
    assert project.locked_until.isoformat() == "2026-08-31"


def test_project_without_lock_has_none():
    assert Project(id=1, name="P", customer=2).locked_until is None


def test_serialize_project_renders_locked_until():
    text = ProjectEntityHandler(client=None).serialize_project(
        Project(id=1, name="P", customer=2, lockedUntil="2026-08-31")
    )
    assert "Locked Until: 2026-08-31" in text


def test_serialize_project_omits_locked_until_when_unset():
    text = ProjectEntityHandler(client=None).serialize_project(
        Project(id=1, name="P", customer=2)
    )
    assert "Locked Until" not in text


@pytest.mark.asyncio
async def test_locked_until_is_passed_through_verbatim_on_create_and_update():
    """Same per-action format split as start/end: the form binds it with the
    controller's ``date_format`` option, so the value is a string we do not
    touch (see test_project_dates.py for the ``.isoformat()`` regression)."""
    client = _client({"id": 27, "name": "P"})

    await client.create_project(ProjectEditForm(name="P", customer=4, lockedUntil="2026-08-31"))
    assert client._request.await_args.kwargs["json"]["lockedUntil"] == "2026-08-31"

    await client.update_project(27, ProjectEditForm(lockedUntil="2026-08-31T00:00:00"))
    assert client._request.await_args.kwargs["json"]["lockedUntil"] == "2026-08-31T00:00:00"


@pytest.mark.asyncio
async def test_locked_until_is_omitted_when_not_given():
    client = _client({"id": 27, "name": "P"})
    await client.update_project(27, ProjectEditForm(name="Renamed"))
    assert "lockedUntil" not in client._request.await_args.kwargs["json"]


def test_locked_until_is_reachable_through_the_entity_schema():
    """The project data schema is additionalProperties:false: without this
    entry the field would be rejected before the handler runs."""
    props = entity_data_schema("project")["properties"]
    assert "lockedUntil" in props
    assert props["lockedUntil"]["type"] == "string"
    assert "2.66" in props["lockedUntil"]["description"]


def test_validate_arguments_accepts_locked_until():
    validate_arguments(entity_tool(), {
        "type": "project",
        "action": "update",
        "id": 1,
        "data": {"lockedUntil": "2026-08-31T00:00:00"},
    })


# --- error hints for a locked project period -------------------------------

def test_validation_error_for_locked_project_gets_a_hint():
    text = format_api_error(KimaiAPIError(
        "Validation Failed", status_code=400,
        details={"errors": {"children": {"begin_date": {"errors": [
            "The project is locked until 08/31/2026, please choose a later date."
        ]}}}},
    ))
    assert "lockedUntil" in text
    assert "entity type=project action=update" in text
    assert "Break time" not in text  # the extra-fields hint must not fire


def test_forbidden_on_a_timesheet_write_mentions_the_lock_date():
    text = format_api_error(KimaiAPIError(
        "Forbidden", status_code=403, method="PATCH", endpoint="/timesheets/5",
    ))
    assert "lacks permission" in text
    assert "lockedUntil" in text
    assert "earlier day" in text  # not "raise": a later date locks more


@pytest.mark.parametrize(("method", "endpoint"), [
    ("GET", "/timesheets/5"),           # reads are never lock-related
    ("DELETE", "/teams/3/projects/9"),  # 2.65 revoke permission tightening
    ("PATCH", "/users/4/preferences"),  # work-contract guard
    (None, None),                       # error raised without request context
])
def test_forbidden_elsewhere_gets_no_lock_date_hint(method, endpoint):
    text = format_api_error(KimaiAPIError(
        "Forbidden", status_code=403, method=method, endpoint=endpoint,
    ))
    assert "lacks permission" in text
    assert "lockedUntil" not in text


@pytest.mark.parametrize(("status", "message"), [
    (405, 'No route found for "DELETE https://kimai.example.com/api/invoices/12": Method Not Allowed (Allow: GET)'),
    (404, 'No route found for "GET https://kimai.example.com/api/favorites/timesheets"'),
])
def test_missing_route_points_to_the_kimai_version(status, message):
    """Kimai < 2.66 has neither route; Symfony's router text is the only signal."""
    text = format_api_error(KimaiAPIError(message, status_code=status))
    assert "does not exist on this Kimai version" in text
    assert "2.66+" in text


def test_ordinary_404_gets_no_version_hint():
    text = format_api_error(KimaiAPIError("Not Found", status_code=404))
    assert "Kimai version" not in text


def test_api_error_carries_the_failed_request():
    """The client attaches method and endpoint so hints can be endpoint-specific."""
    err = KimaiAPIError("x", status_code=403, method="POST", endpoint="/timesheets")
    assert (err.method, err.endpoint) == ("POST", "/timesheets")
    assert KimaiAPIError("x").endpoint is None


def test_ordinary_validation_error_gets_no_lock_hint():
    text = format_api_error(KimaiAPIError(
        "Validation Failed", status_code=400,
        details={"errors": {"begin": ["This value is not valid."]}},
    ))
    assert "lockedUntil" not in text


# --- favorites ---------------------------------------------------------------

def _expanded(ts_id: int) -> TimesheetExpanded:
    return TimesheetExpanded(
        id=ts_id,
        begin="2026-09-01T09:00:00+0200",
        end="2026-09-01T10:00:00+0200",
        description="Weekly sync",
        tags=["meeting"],
        user={"id": 3, "username": "alice"},
        project={"id": 2, "name": "Relaunch", "customer": {"id": 9, "name": "Acme",
                 "country": "DE", "currency": "EUR", "timezone": "Europe/Berlin"}},
        activity={"id": 1, "name": "Meetings"},
    )


@pytest.mark.asyncio
async def test_favorites_are_fetched_from_the_new_endpoint_as_expanded_rows():
    client = _client([{
        "id": 5,
        "begin": "2026-09-01T09:00:00+0200",
        "end": "2026-09-01T10:00:00+0200",
        "tags": [],
        "user": {"id": 3, "username": "alice"},
        "project": {"id": 2, "name": "Relaunch"},
        "activity": {"id": 1, "name": "Meetings"},
    }])

    [ts] = await client.get_favorite_timesheets()

    assert client._request.await_args.args == ("GET", "/favorites/timesheets")
    assert ts.project.name == "Relaunch"
    assert ts.rate is None  # stripped for a plain user, like everywhere else


@pytest.mark.asyncio
async def test_add_and_remove_favorite_hit_the_id_routes():
    client = _client({})  # Kimai answers 204, _request maps that to {}

    await client.add_favorite_timesheet(5)
    assert client._request.await_args.args == ("POST", "/favorites/timesheets/5")

    await client.remove_favorite_timesheet(5)
    assert client._request.await_args.args == ("DELETE", "/favorites/timesheets/5")


@pytest.mark.asyncio
async def test_timer_favorites_lists_names_and_points_to_restart():
    client = AsyncMock(spec=KimaiClient)
    client.get_favorite_timesheets.return_value = [_expanded(5)]

    [content] = await timesheet_consolidated.handle_timer(client, action="favorites")

    assert "ID: 5 - Project: Acme / Relaunch / Activity: Meetings" in content.text
    assert "Tags: meeting" in content.text
    assert "action=restart" in content.text


@pytest.mark.asyncio
async def test_timer_favorites_empty_explains_how_to_add_one():
    client = AsyncMock(spec=KimaiClient)
    client.get_favorite_timesheets.return_value = []

    [content] = await timesheet_consolidated.handle_timer(client, action="favorites")

    assert "No favorite timesheets" in content.text
    assert "action=favorite" in content.text


@pytest.mark.asyncio
@pytest.mark.parametrize(("action", "method"), [
    ("favorite", "add_favorite_timesheet"),
    ("unfavorite", "remove_favorite_timesheet"),
])
async def test_timer_favorite_toggles_call_the_client(action, method):
    client = AsyncMock(spec=KimaiClient)

    [content] = await timesheet_consolidated.handle_timer(client, action=action, id=5)

    getattr(client, method).assert_awaited_once_with(5)
    assert "Timesheet ID 5" in content.text


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["favorite", "unfavorite"])
async def test_timer_favorite_toggles_need_an_id(action):
    from kimai_mcp.tools.errors import ToolError

    client = AsyncMock(spec=KimaiClient)
    with pytest.raises(ToolError, match="'id' parameter is required"):
        await timesheet_consolidated.handle_timer(client, action=action)
    client.add_favorite_timesheet.assert_not_awaited()
    client.remove_favorite_timesheet.assert_not_awaited()


# --- invoice delete ----------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_invoice_hits_the_new_route():
    client = _client({})
    await client.delete_invoice(12)
    assert client._request.await_args.args == ("DELETE", "/invoices/12")


@pytest.mark.asyncio
async def test_entity_invoice_delete_is_supported_now():
    client = AsyncMock(spec=KimaiClient)

    [content] = await InvoiceEntityHandler(client).delete(12)

    client.delete_invoice.assert_awaited_once_with(12)
    assert "Deleted invoice ID 12" in content.text
    assert "delete_invoice" in content.text
