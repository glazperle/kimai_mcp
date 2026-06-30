"""Dispatch smoke tests for every action of every consolidated tool handler.

Each test dispatches one (tool, action) combination against an
``AsyncMock(spec=KimaiClient)``. Because of ``spec=``, any call to a client
method that does not exist on the real ``KimaiClient`` raises an
``AttributeError`` immediately - exactly the class of bugs these tests are
meant to prevent.

The mock returns minimal but valid Pydantic model instances from
``kimai_mcp.models`` so the handlers run all the way through their
formatting code. Every test asserts that the handler returns a non-empty
``List[TextContent]`` and that no "Unknown action/type" dispatch gap or
swallowed mock ``AttributeError`` leaked into the output.
"""

from collections import defaultdict
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import json

import pytest
from mcp.types import TextContent, Tool

from kimai_mcp import models as m
from kimai_mcp.client import KimaiClient
from kimai_mcp.tools.errors import ToolError
from kimai_mcp.tools import (
    absence_manager,
    calendar_meta,
    comment_tool,
    config_info,
    entity_manager,
    project_analysis,
    rate_manager,
    team_access_manager,
    timesheet_consolidated,
)

NOW = datetime(2026, 1, 15, 9, 0, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 1, 15, 17, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Mock client factory
# ---------------------------------------------------------------------------

def make_mock_client() -> AsyncMock:
    """Create an AsyncMock specced against KimaiClient.

    All client methods used by the tool handlers are configured to return
    minimal valid model instances, so the handlers can run end-to-end.
    Calls to non-existent client methods raise AttributeError thanks to
    ``spec=KimaiClient``.
    """
    client = AsyncMock(spec=KimaiClient)

    user = m.User(id=1, username="alice", alias="Alice", enabled=True)
    user2 = m.User(id=2, username="bob", enabled=True)
    user_ext = m.UserEntity(
        id=1,
        username="alice",
        alias="Alice",
        enabled=True,
        roles=["ROLE_USER"],
        preferences=[{"name": "holidays", "value": "30"}],
    )
    project = m.Project(id=1, name="Test Project", customer=1)
    project_ext = m.ProjectExtended(id=1, name="Test Project", customer=1)
    activity = m.Activity(id=1, name="Development")
    activity_ext = m.ActivityExtended(id=1, name="Development")
    customer = m.Customer(id=1, name="ACME")
    customer_ext = m.CustomerExtended(id=1, name="ACME")
    team = m.Team(
        id=1,
        name="Team A",
        members=[
            m.TeamMember(user=user, teamlead=True),
            m.TeamMember(user=user2),
        ],
    )
    tag = m.TagEntity(id=1, name="urgent")
    invoice = m.Invoice(
        id=1,
        invoiceNumber="INV-001",
        customer=customer,
        user=user,
        createdAt=NOW,
        currency="EUR",
        total=100.0,
        tax=19.0,
    )
    holiday = m.PublicHoliday(id=1, date=NOW, name="New Year")
    absence = m.Absence(
        id=1,
        user=user,
        date=NOW,
        duration=28800,
        type="holiday",
        status="new",
        comment="vacation",
    )
    completed_ts = m.TimesheetEntity(
        id=10,
        activity=1,
        project=1,
        user=1,
        begin=NOW,
        end=LATER,
        duration=28800,
        description="work",
        tags=["dev"],
    )
    running_ts = m.TimesheetEntity(
        id=11,
        activity=1,
        project=1,
        user=1,
        begin=NOW,
        end=None,
    )
    rate = m.Rate(id=5, user=user, rate=50.0, internalRate=40.0, isFixed=False)
    comment = m.Comment(
        id=1, message="hello", createdBy=user, createdAt=NOW, pinned=True
    )
    event = m.CalendarEvent(
        title="Vacation", start=NOW, end=LATER, allDay=True, color="#ff0000"
    )

    # User / current user
    client.get_current_user.return_value = user
    client.get_users.return_value = [user, user2]
    client.get_users_extended.return_value = [user_ext]
    client.get_user_extended.return_value = user_ext
    client.create_user.return_value = user_ext
    client.update_user.return_value = user_ext
    client.update_user_preferences.return_value = user_ext
    client.lock_work_contract_month.return_value = None
    client.unlock_work_contract_month.return_value = None

    # Timesheets / timer
    client.get_timesheets.return_value = ([completed_ts], True, 1)
    client.get_timesheet.return_value = completed_ts
    client.get_active_timesheets.return_value = [running_ts]
    client.get_recent_timesheets.return_value = [completed_ts]
    client.create_timesheet.return_value = running_ts
    client.update_timesheet.return_value = completed_ts
    client.delete_timesheet.return_value = None
    client.stop_timesheet.return_value = completed_ts
    client.restart_timesheet.return_value = running_ts
    client.duplicate_timesheet.return_value = completed_ts
    client.toggle_timesheet_export.return_value = completed_ts
    client.update_timesheet_meta.return_value = completed_ts

    # Projects
    client.get_projects.return_value = [project]
    client.get_project.return_value = project
    client.create_project.return_value = project_ext
    client.update_project.return_value = project_ext
    client.delete_project.return_value = None
    client.update_project_meta.return_value = project_ext
    client.get_project_rates.return_value = [rate]
    client.add_project_rate.return_value = rate
    client.delete_project_rate.return_value = None

    # Activities
    client.get_activities.return_value = [activity]
    client.get_activity.return_value = activity
    client.create_activity.return_value = activity_ext
    client.update_activity.return_value = activity_ext
    client.delete_activity.return_value = None
    client.update_activity_meta.return_value = activity_ext
    client.get_activity_rates.return_value = [rate]
    client.add_activity_rate.return_value = rate
    client.delete_activity_rate.return_value = None

    # Customers
    client.get_customers.return_value = [customer]
    client.get_customer.return_value = customer
    client.create_customer.return_value = customer_ext
    client.update_customer.return_value = customer_ext
    client.delete_customer.return_value = None
    client.update_customer_meta.return_value = customer_ext
    client.get_customer_rates.return_value = [rate]
    client.add_customer_rate.return_value = rate
    client.delete_customer_rate.return_value = None

    # Teams
    client.get_teams.return_value = [team]
    client.get_team.return_value = team
    client.create_team.return_value = team
    client.update_team.return_value = team
    client.delete_team.return_value = None
    client.add_team_member.return_value = team
    client.remove_team_member.return_value = team
    client.grant_team_customer_access.return_value = team
    client.revoke_team_customer_access.return_value = team
    client.grant_team_project_access.return_value = team
    client.revoke_team_project_access.return_value = team
    client.grant_team_activity_access.return_value = team
    client.revoke_team_activity_access.return_value = team

    # Tags
    client.get_tags.return_value = ["urgent"]
    client.get_tags_full.return_value = [tag]
    client.create_tag.return_value = tag
    client.delete_tag.return_value = None

    # Invoices
    client.get_invoices.return_value = [invoice]
    client.get_invoice.return_value = invoice
    client.update_invoice_meta.return_value = invoice

    # Holidays
    client.get_public_holidays.return_value = [holiday]
    client.delete_public_holiday.return_value = None
    client.get_public_holidays_calendar.return_value = [event]

    # Absences
    client.get_absences.return_value = [absence]
    client.create_absence.return_value = [absence]
    client.delete_absence.return_value = None
    client.request_absence_approval.return_value = absence
    client.confirm_absence_approval.return_value = absence
    client.reject_absence_approval.return_value = absence
    client.get_absence_types.return_value = {
        "holiday": "Urlaub",
        "sickness": "Krankheit",
    }
    client.get_absences_calendar.return_value = [event]

    # Comments
    client.get_comments.return_value = [comment]
    client.create_comment.return_value = comment
    client.delete_comment.return_value = None
    client.pin_comment.return_value = comment

    # Config / system
    client.get_version.return_value = m.Version(
        **{"version": "2.36.0", "versionId": 23600, "copyright": "Kimai (c)"}
    )
    client.get_timesheet_config.return_value = m.TimesheetConfig()
    client.get_color_config.return_value = {"Red": "#ff0000"}
    client.get_plugins.return_value = [m.Plugin(name="WorkContract", version="1.0")]

    return client


# ---------------------------------------------------------------------------
# Dispatch case collection
# ---------------------------------------------------------------------------

# Tracks which enum values (action/type/entity/target) the smoke tests
# exercise per tool, so the schema consistency test can verify that every
# enum value declared in a tool schema is actually dispatched here.
EXERCISED = defaultdict(set)

CASES = []

_TRACKED_KEYS = ("action", "type", "entity", "target")


def _case(tool_name, handler, params, case_id, expect_error=False):
    for key in _TRACKED_KEYS:
        if key in params:
            EXERCISED[(tool_name, key)].add(params[key])
    CASES.append(pytest.param(handler, params, expect_error, id=case_id))


# (entity_type, action) combinations whose handler now raises ToolError instead
# of returning an "Error: ..." TextContent (unsupported operations / hard API
# limitations). The central _call_tool converts these to isError=True results.
ENTITY_ERROR_CASES = {
    ("user", "delete"),
    ("tag", "get"),
    ("tag", "update"),
    ("invoice", "create"),
    ("invoice", "update"),
    ("invoice", "delete"),
    ("holiday", "get"),
    ("holiday", "create"),
    ("holiday", "update"),
}


# --- entity tool -----------------------------------------------------------

ENTITY_CREATE_DATA = {
    "project": {"name": "New Project", "customer": 1},
    "activity": {"name": "New Activity"},
    "customer": {
        "name": "New Customer",
        "country": "DE",
        "currency": "EUR",
        "timezone": "Europe/Berlin",
    },
    "user": {
        "username": "newuser",
        "email": "new@example.com",
        "language": "de",
        "locale": "de",
        "timezone": "Europe/Berlin",
        "plainPassword": "secret-password-123",
    },
    "team": {"name": "New Team", "members": [{"user": 1, "teamlead": True}]},
    "tag": {"name": "new-tag"},
    # invoice/holiday creation is rejected by the handler with an
    # informative error; data is only needed to pass the generic guard.
    "invoice": {"name": "irrelevant"},
    "holiday": {"name": "irrelevant"},
}

ENTITY_UPDATE_DATA = {
    "project": {"name": "Updated Project"},
    "activity": {"name": "Updated Activity"},
    "customer": {"name": "Updated Customer"},
    "user": {
        "email": "alice@example.com",
        "language": "de",
        "locale": "de",
        "timezone": "Europe/Berlin",
    },
    "team": {"name": "Updated Team", "members": [{"user": 1, "teamlead": True}]},
    "tag": {"name": "irrelevant"},
    "invoice": {"name": "irrelevant"},
    "holiday": {"name": "irrelevant"},
}

ENTITY_TYPES = [
    "project", "activity", "customer", "user",
    "team", "tag", "invoice", "holiday",
]

for entity_type in ENTITY_TYPES:
    _case(
        "entity", entity_manager.handle_entity,
        {"type": entity_type, "action": "list"},
        f"entity-{entity_type}-list",
        expect_error=(entity_type, "list") in ENTITY_ERROR_CASES,
    )
    _case(
        "entity", entity_manager.handle_entity,
        {"type": entity_type, "action": "get", "id": 1},
        f"entity-{entity_type}-get",
        expect_error=(entity_type, "get") in ENTITY_ERROR_CASES,
    )
    _case(
        "entity", entity_manager.handle_entity,
        {"type": entity_type, "action": "create",
         "data": ENTITY_CREATE_DATA[entity_type]},
        f"entity-{entity_type}-create",
        expect_error=(entity_type, "create") in ENTITY_ERROR_CASES,
    )
    _case(
        "entity", entity_manager.handle_entity,
        {"type": entity_type, "action": "update", "id": 1,
         "data": ENTITY_UPDATE_DATA[entity_type]},
        f"entity-{entity_type}-update",
        expect_error=(entity_type, "update") in ENTITY_ERROR_CASES,
    )
    _case(
        "entity", entity_manager.handle_entity,
        {"type": entity_type, "action": "delete", "id": 1},
        f"entity-{entity_type}-delete",
        expect_error=(entity_type, "delete") in ENTITY_ERROR_CASES,
    )

# user-only actions
_case(
    "entity", entity_manager.handle_entity,
    {"type": "user", "action": "lock_month", "id": 1, "month": "2026-01-01"},
    "entity-user-lock_month",
)
_case(
    "entity", entity_manager.handle_entity,
    {"type": "user", "action": "lock_month", "ids": [1, 2], "month": "2026-01-01"},
    "entity-user-lock_month-bulk",
)
_case(
    "entity", entity_manager.handle_entity,
    {"type": "user", "action": "unlock_month", "id": 1, "month": "2026-01-01"},
    "entity-user-unlock_month",
)
_case(
    "entity", entity_manager.handle_entity,
    {"type": "user", "action": "unlock_month", "user_scope": "all",
     "month": "2026-01-01"},
    "entity-user-unlock_month-all",
)
_case(
    "entity", entity_manager.handle_entity,
    {"type": "user", "action": "set_preferences", "id": 1,
     "preferences": [{"name": "vacation_days", "value": "30"}]},
    "entity-user-set_preferences",
)
# batch_delete: real path for a deletable type, guarded path for users
_case(
    "entity", entity_manager.handle_entity,
    {"type": "project", "action": "batch_delete", "ids": [1, 2]},
    "entity-project-batch_delete",
)
_case(
    "entity", entity_manager.handle_entity,
    {"type": "user", "action": "batch_delete", "ids": [1, 2]},
    "entity-user-batch_delete",
    expect_error=True,
)

# --- timesheet tool --------------------------------------------------------

_case("timesheet", timesheet_consolidated.handle_timesheet,
      {"action": "list"}, "timesheet-list")
_case(
    "timesheet", timesheet_consolidated.handle_timesheet,
    {"action": "list", "filters": {
        "user_scope": "all",
        "begin": "2026-01-01T00:00:00",
        "end": "2026-01-31T23:59:59",
        "calculate_stats": True,
        "include_user_list": True,
    }},
    "timesheet-list-all-stats",
)
_case("timesheet", timesheet_consolidated.handle_timesheet,
      {"action": "get", "id": 10}, "timesheet-get")
_case(
    "timesheet", timesheet_consolidated.handle_timesheet,
    {"action": "create", "data": {
        "project": 1, "activity": 1,
        "begin": "2026-01-15T09:00:00", "end": "2026-01-15T17:00:00",
        "description": "smoke", "tags": "dev",
    }},
    "timesheet-create",
)
_case("timesheet", timesheet_consolidated.handle_timesheet,
      {"action": "update", "id": 10, "data": {"description": "updated"}},
      "timesheet-update")
_case("timesheet", timesheet_consolidated.handle_timesheet,
      {"action": "delete", "id": 10}, "timesheet-delete")
_case("timesheet", timesheet_consolidated.handle_timesheet,
      {"action": "duplicate", "id": 10}, "timesheet-duplicate")
_case("timesheet", timesheet_consolidated.handle_timesheet,
      {"action": "export_toggle", "id": 10}, "timesheet-export_toggle")
_case("timesheet", timesheet_consolidated.handle_timesheet,
      {"action": "meta_update", "id": 10,
       "meta": [{"name": "field", "value": "v"}]},
      "timesheet-meta_update")
_case("timesheet", timesheet_consolidated.handle_timesheet,
      {"action": "user_guide"}, "timesheet-user_guide")
_case("timesheet", timesheet_consolidated.handle_timesheet,
      {"action": "batch_delete", "ids": [1, 2]}, "timesheet-batch_delete")
_case("timesheet", timesheet_consolidated.handle_timesheet,
      {"action": "batch_export", "ids": [1, 2]}, "timesheet-batch_export")

# --- timer tool ------------------------------------------------------------

_case("timer", timesheet_consolidated.handle_timer,
      {"action": "start", "data": {"project": 1, "activity": 1}},
      "timer-start")
_case("timer", timesheet_consolidated.handle_timer,
      {"action": "stop", "id": 10}, "timer-stop")
_case("timer", timesheet_consolidated.handle_timer,
      {"action": "restart", "id": 10}, "timer-restart")
_case("timer", timesheet_consolidated.handle_timer,
      {"action": "active"}, "timer-active")
_case("timer", timesheet_consolidated.handle_timer,
      {"action": "recent"}, "timer-recent")

# --- rate tool -------------------------------------------------------------

for rate_entity in ("customer", "project", "activity"):
    _case("rate", rate_manager.handle_rate,
          {"entity": rate_entity, "entity_id": 1, "action": "list"},
          f"rate-{rate_entity}-list")
    _case("rate", rate_manager.handle_rate,
          {"entity": rate_entity, "entity_id": 1, "action": "add",
           "data": {"rate": 50, "user": 1, "internal_rate": 40,
                    "is_fixed": False}},
          f"rate-{rate_entity}-add")
    _case("rate", rate_manager.handle_rate,
          {"entity": rate_entity, "entity_id": 1, "action": "delete",
           "rate_id": 5},
          f"rate-{rate_entity}-delete")

# --- team_access tool ------------------------------------------------------

_case("team_access", team_access_manager.handle_team_access,
      {"team_id": 1, "action": "add_member", "user_id": 2},
      "team_access-add_member")
_case("team_access", team_access_manager.handle_team_access,
      {"team_id": 1, "action": "remove_member", "user_id": 2},
      "team_access-remove_member")
for target in ("customer", "project", "activity"):
    _case("team_access", team_access_manager.handle_team_access,
          {"team_id": 1, "action": "grant", "target": target, "target_id": 1},
          f"team_access-grant-{target}")
    _case("team_access", team_access_manager.handle_team_access,
          {"team_id": 1, "action": "revoke", "target": target, "target_id": 1},
          f"team_access-revoke-{target}")

# --- absence tool ----------------------------------------------------------

_case("absence", absence_manager.handle_absence,
      {"action": "list"}, "absence-list-self")
_case("absence", absence_manager.handle_absence,
      {"action": "list", "filters": {
          "user_scope": "all", "begin": "2026-01-01", "end": "2026-01-31"}},
      "absence-list-all")
_case("absence", absence_manager.handle_absence,
      {"action": "statistics"}, "absence-statistics")
_case("absence", absence_manager.handle_absence,
      {"action": "types"}, "absence-types")
_case("absence", absence_manager.handle_absence,
      {"action": "create", "data": {
          "comment": "vacation", "date": "2026-01-10", "type": "holiday"}},
      "absence-create")
_case("absence", absence_manager.handle_absence,
      {"action": "create", "data": {
          "comment": "long vacation", "date": "2026-12-20",
          "end": "2027-01-05", "type": "holiday"}},
      "absence-create-split")
_case("absence", absence_manager.handle_absence,
      {"action": "delete", "id": 1}, "absence-delete")
_case("absence", absence_manager.handle_absence,
      {"action": "approve", "id": 1}, "absence-approve")
_case("absence", absence_manager.handle_absence,
      {"action": "reject", "id": 1}, "absence-reject")
_case("absence", absence_manager.handle_absence,
      {"action": "request", "id": 1}, "absence-request")
_case("absence", absence_manager.handle_absence,
      {"action": "attendance", "date": "2026-01-15"}, "absence-attendance")
_case("absence", absence_manager.handle_absence,
      {"action": "batch_delete", "ids": [1, 2]}, "absence-batch_delete")
_case("absence", absence_manager.handle_absence,
      {"action": "batch_approve", "ids": [1, 2]}, "absence-batch_approve")
_case("absence", absence_manager.handle_absence,
      {"action": "batch_reject", "ids": [1, 2]}, "absence-batch_reject")

# --- calendar tool ---------------------------------------------------------

_case("calendar", calendar_meta.handle_calendar,
      {"type": "absences"}, "calendar-absences")
_case("calendar", calendar_meta.handle_calendar,
      {"type": "absences", "filters": {
          "user": 1, "begin": "2026-01-01", "end": "2026-01-31"}},
      "calendar-absences-filtered")
_case("calendar", calendar_meta.handle_calendar,
      {"type": "holidays"}, "calendar-holidays")

# --- meta tool -------------------------------------------------------------

for meta_entity in ("customer", "project", "activity", "timesheet", "invoice"):
    _case("meta", calendar_meta.handle_meta,
          {"entity": meta_entity, "entity_id": 1, "action": "update",
           "data": [{"name": "field", "value": "v"}]},
          f"meta-{meta_entity}-update")

# --- user_current tool -----------------------------------------------------

_case("user_current", calendar_meta.handle_user_current,
      {}, "user_current")

# --- comment tool ----------------------------------------------------------

for comment_entity in ("project", "customer"):
    _case("comment", comment_tool.handle_comment,
          {"entity": comment_entity, "entity_id": 1, "action": "list"},
          f"comment-{comment_entity}-list")
    _case("comment", comment_tool.handle_comment,
          {"entity": comment_entity, "entity_id": 1, "action": "create",
           "data": {"message": "hello", "pinned": True}},
          f"comment-{comment_entity}-create")
    _case("comment", comment_tool.handle_comment,
          {"entity": comment_entity, "entity_id": 1, "action": "delete",
           "comment_id": 1},
          f"comment-{comment_entity}-delete")
    _case("comment", comment_tool.handle_comment,
          {"entity": comment_entity, "entity_id": 1, "action": "pin",
           "comment_id": 1},
          f"comment-{comment_entity}-pin")

# --- config tool -----------------------------------------------------------

for config_type in ("timesheet", "colors", "plugins", "version", "all"):
    _case("config", config_info.handle_config,
          {"type": config_type}, f"config-{config_type}")

# --- analyze_project_team tool ---------------------------------------------

_case("analyze_project_team", project_analysis.handle_analyze_project_team,
      {"project_name": "Test Project",
       "begin": "2026-01-01", "end": "2026-06-30"},
      "analyze_project_team")


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

# Markers that indicate a dispatch gap or a swallowed mock error.
# Tools may legitimately return other "Error: ..." texts (e.g. "Invoices
# cannot be deleted"), but never these:
FORBIDDEN_MARKERS = (
    "Error: Unknown action",
    "Error: Unknown entity type",
    "Error: Unknown calendar type",
    "Error: Unknown config type",
    "Error: Unknown target type",
    # project_analysis catches all exceptions; these markers reveal
    # AttributeError/TypeError raised by a wrong client call:
    "object has no attribute",
    "Error during analysis",
    "AttributeError",
    "TypeError",
)


def assert_valid_result(result):
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert len(result) >= 1, "Handler returned an empty result list"
    for item in result:
        assert isinstance(item, TextContent), (
            f"Expected TextContent, got {type(item)}"
        )
        assert item.type == "text"
        assert isinstance(item.text, str)
    combined = "\n".join(item.text for item in result)
    for marker in FORBIDDEN_MARKERS:
        assert marker not in combined, (
            f"Handler output contains forbidden marker '{marker}':\n{combined}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("handler,params,expect_error", CASES)
async def test_dispatch_smoke(handler, params, expect_error):
    """Dispatch every action of every tool handler against a specced mock.

    A call to a non-existent KimaiClient method raises AttributeError and
    fails the test (this exact bug class occurred 5 times in the past).

    Cases marked ``expect_error`` exercise unsupported operations / hard API
    limitations, which now raise ``ToolError`` (the central _call_tool turns
    these into ``isError=True`` results).
    """
    client = make_mock_client()

    is_positional = handler is project_analysis.handle_analyze_project_team

    if expect_error:
        with pytest.raises(ToolError):
            if is_positional:
                # This handler takes the arguments dict positionally (see server.py)
                await handler(client, params)
            else:
                await handler(client, **params)
        return

    if is_positional:
        result = await handler(client, params)
    else:
        result = await handler(client, **params)

    assert_valid_result(result)


# ---------------------------------------------------------------------------
# Schema consistency tests
# ---------------------------------------------------------------------------

ALL_TOOL_FACTORIES = [
    entity_manager.entity_tool,
    timesheet_consolidated.timesheet_tool,
    timesheet_consolidated.timer_tool,
    rate_manager.rate_tool,
    team_access_manager.team_access_tool,
    absence_manager.absence_tool,
    calendar_meta.calendar_tool,
    calendar_meta.meta_tool,
    calendar_meta.user_current_tool,
    comment_tool.comment_tool,
    config_info.config_tool,
    project_analysis.analyze_project_team_tool,
]


@pytest.mark.parametrize(
    "tool_factory", ALL_TOOL_FACTORIES, ids=lambda f: f.__name__
)
def test_tool_schema_is_valid(tool_factory):
    """Every tool exposes a JSON-serializable object schema."""
    tool = tool_factory()
    assert isinstance(tool, Tool)
    assert tool.name, "Tool must have a non-empty name"
    assert tool.description, "Tool must have a non-empty description"

    schema = tool.inputSchema
    assert isinstance(schema, dict)
    assert schema.get("type") == "object"
    # Must be valid JSON (no sets, datetimes, etc. embedded)
    json.dumps(schema)

    # All declared required keys must exist in properties
    properties = schema.get("properties", {})
    for required_key in schema.get("required", []):
        assert required_key in properties, (
            f"Required key '{required_key}' missing from properties "
            f"of tool '{tool.name}'"
        )


# (tool_factory, enum property name) pairs whose enum values must all be
# exercised by the dispatch smoke tests above - and vice versa.
SCHEMA_ENUM_CHECKS = [
    ("entity", entity_manager.entity_tool, "type"),
    ("entity", entity_manager.entity_tool, "action"),
    ("timesheet", timesheet_consolidated.timesheet_tool, "action"),
    ("timer", timesheet_consolidated.timer_tool, "action"),
    ("rate", rate_manager.rate_tool, "entity"),
    ("rate", rate_manager.rate_tool, "action"),
    ("team_access", team_access_manager.team_access_tool, "action"),
    ("team_access", team_access_manager.team_access_tool, "target"),
    ("absence", absence_manager.absence_tool, "action"),
    ("calendar", calendar_meta.calendar_tool, "type"),
    ("meta", calendar_meta.meta_tool, "entity"),
    ("meta", calendar_meta.meta_tool, "action"),
    ("comment", comment_tool.comment_tool, "entity"),
    ("comment", comment_tool.comment_tool, "action"),
    ("config", config_info.config_tool, "type"),
]


@pytest.mark.parametrize(
    "tool_name,tool_factory,prop",
    SCHEMA_ENUM_CHECKS,
    ids=[f"{name}-{prop}" for name, _, prop in SCHEMA_ENUM_CHECKS],
)
def test_schema_enums_match_dispatch_coverage(tool_name, tool_factory, prop):
    """Every enum value in the tool schema is dispatched by a smoke test.

    If this fails after adding a new action to a schema, add a matching
    smoke case above. If it fails the other way around, the smoke tests
    exercise a value that the schema does not declare.
    """
    tool = tool_factory()
    schema_values = set(tool.inputSchema["properties"][prop]["enum"])
    exercised = EXERCISED[(tool_name, prop)]

    missing = schema_values - exercised
    assert not missing, (
        f"Schema enum values of '{tool.name}.{prop}' not covered by "
        f"dispatch smoke tests: {sorted(missing)}"
    )
    extra = exercised - schema_values
    assert not extra, (
        f"Dispatch smoke tests use '{tool.name}.{prop}' values that are "
        f"not declared in the schema: {sorted(extra)}"
    )


# ---------------------------------------------------------------------------
# Shared tool registry (single source of truth for both servers)
# ---------------------------------------------------------------------------

from kimai_mcp.tools import registry  # noqa: E402


def test_registry_exposes_every_tested_tool():
    """all_tools() must cover exactly the tools validated above - so a tool can't
    be added to one server's registry without being schema-checked, and vice versa."""
    registry_names = {t.name for t in registry.all_tools()}
    factory_names = {f().name for f in ALL_TOOL_FACTORIES}
    assert registry_names == factory_names
    # all_tools() order matches the declared name order, names are unique
    assert [t.name for t in registry.all_tools()] == registry.tool_names()
    assert len(registry.tool_names()) == len(set(registry.tool_names()))


@pytest.mark.asyncio
async def test_registry_dispatch_routes_known_and_unknown():
    client = make_mock_client()
    # A known tool routes to its handler and returns TextContent.
    result = await registry.dispatch_tool(client, "user_current", {})
    assert_valid_result(result)
    # An unknown tool raises ToolError, which the servers convert to an
    # isError=True result.
    with pytest.raises(ToolError, match="Unknown tool"):
        await registry.dispatch_tool(client, "does_not_exist", {})
