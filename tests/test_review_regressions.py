"""Regressions for defects found reviewing the v2.16.0 diff.

Each test states the observable failure it prevents, because most of these are
silent: the tool reported success while the API never received the field, or a
guard logged that it was doing its job while the next line undid it.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from mcp.client import Client
from mcp.types import CallToolRequestParams

from kimai_mcp.client import KimaiAPIError, KimaiClient
from kimai_mcp.models import (
    AbsenceForm,
    ActivityFilter,
    CustomerFilter,
    ProjectFilter,
    RateForm,
    TimesheetEditForm,
)
from kimai_mcp.oauth import KimaiOAuthProvider
from kimai_mcp.server import KimaiMCPServer
from kimai_mcp.tools.errors import ToolError
from kimai_mcp.tools.registry import dispatch_tool
from kimai_mcp.user_config import UserConfig, UsersConfig

# ---------------------------------------------------------------------------
# Aliased fields must survive being passed by their Python name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "kwargs", "expected_key", "expected_value"),
    [
        (AbsenceForm, {"comment": "c", "date": "2026-09-01", "half_day": True}, "halfDay", True),
        (RateForm, {"rate": 50.0, "is_fixed": True}, "isFixed", True),
        (RateForm, {"rate": 50.0, "internal_rate": 20.0}, "internalRate", 20.0),
        (TimesheetEditForm, {"project": 1, "break_duration": 1800}, "break", 1800),
        (CustomerFilter, {"order_by": "name"}, "orderBy", "name"),
        (ProjectFilter, {"order_by": "name"}, "orderBy", "name"),
        (ActivityFilter, {"order_by": "name"}, "orderBy", "name"),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_field_name_reaches_the_wire(model, kwargs, expected_key, expected_value):
    """Passing the Python name must not silently drop the field.

    Without populate_by_name pydantic ignored the field name, so e.g.
    AbsenceForm(half_day=True) serialized without halfDay: Kimai booked a full
    day off the user's quota and the tool still answered "Created absence".
    """
    payload = model(**kwargs).model_dump(exclude_none=True, by_alias=True)
    assert payload.get(expected_key) == expected_value


def test_alias_spelling_still_accepted():
    """API responses use the aliases; both spellings have to keep working."""
    form = AbsenceForm(comment="c", date="2026-09-01", halfDay=True)
    assert form.half_day is True


# ---------------------------------------------------------------------------
# Tool arguments are validated against the schema (SDK 2.x dropped this)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"type": "customer", "action": "update", "id": 1, "data": {"langauge": "de"}},
         "Additional properties are not allowed"),
        ({"type": "customer", "action": "frobnicate"}, "is not one of"),
    ],
    ids=["typo_in_nested_data", "invalid_enum"],
)
async def test_invalid_arguments_are_rejected(arguments, expected):
    """A typo must not turn into an empty PATCH reported as success.

    The entity data schemas are additionalProperties:false while the pydantic
    forms ignore extras, so an unvalidated {"langauge": "de"} produced an empty
    request body and the answer "Updated Customer: ...".
    """
    client = AsyncMock(spec=KimaiClient)
    with pytest.raises(ToolError, match=f"Input validation error.*{expected}"):
        await dispatch_tool(client, "entity", arguments)
    client.update_customer.assert_not_called()


@pytest.mark.asyncio
async def test_valid_arguments_pass_validation():
    client = AsyncMock(spec=KimaiClient)
    client.get_customers.return_value = []
    result = await dispatch_tool(client, "entity", {"type": "customer", "action": "list"})
    assert result


# ---------------------------------------------------------------------------
# Nothing may escape _call_tool as a protocol error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_construction_failure_is_an_is_error_result():
    """A broken CA path must not leave the handler as a JSON-RPC error.

    SDK 1.x wrapped the whole handler; SDK 2.x does not, so _ensure_client()
    running outside the try turned a FileNotFoundError into a protocol error
    that clients cannot attribute to the tool call.
    """
    server = KimaiMCPServer(
        base_url="http://example.invalid", api_token="t", ssl_verify="/nonexistent/ca.pem"
    )
    result = await server._call_tool(
        None, CallToolRequestParams(name="entity", arguments={"type": "project", "action": "list"})
    )
    assert result.is_error is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"project_name": "X", "end": "2026-01-01T00:00:00"}, "begin"),
        ({"project_name": "X", "begin": "01/2026", "end": "2026-01-01T00:00:00"}, "Invalid date format"),
    ],
    ids=["missing_begin", "malformed_begin"],
)
async def test_analyze_project_team_reports_bad_input_readably(arguments, expected):
    """No bare KeyError repr ("Error: 'begin'") or raw fromisoformat message.

    Required arguments were subscripted above the try block, so with the SDK's
    own validation gone the client saw the interpreter's error text.
    """
    async with Client(_server_with_stub_client()) as mcp:
        result = await mcp.call_tool("analyze_project_team", arguments)

    assert result.is_error is True
    text = "\n".join(c.text for c in result.content)
    assert expected in text
    assert text != "Error: 'begin'"


def _server_with_stub_client():
    server = KimaiMCPServer(base_url="http://example.invalid", api_token="t")
    server.client = AsyncMock(spec=KimaiClient)
    return server.server


# ---------------------------------------------------------------------------
# Statistics must not fail the whole listing on mixed naive/aware bounds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_offset_date_filters_do_not_fail_the_listing():
    """One bound with an offset and one without raises TypeError, not ValueError.

    The year-breakdown heuristic is best-effort; suppressing only ValueError
    turned a legal filter combination into a failed timesheet listing.
    """
    from kimai_mcp.tools import timesheet_consolidated as ts

    client = AsyncMock(spec=KimaiClient)
    client.get_timesheets.return_value = ([], True, 1)
    client.get_projects.return_value = []
    result = await ts.handle_timesheet(
        client,
        action="list",
        filters={
            "user_scope": "self",
            "begin": "2025-01-01",
            "end": "2026-06-01T00:00:00+00:00",
            "calculate_stats": True,
        },
    )
    assert result
    assert result[0].text


# ---------------------------------------------------------------------------
# Refresh rotation must not orphan the old access token
# ---------------------------------------------------------------------------


def _provider() -> KimaiOAuthProvider:
    cfg = UsersConfig(users={"alice-abcdefghijkl": UserConfig(
        kimai_url="http://x", kimai_token="t", auth_secret="s")})
    return KimaiOAuthProvider(users_config=cfg, public_url="https://mcp.example.com")


def test_rotated_access_token_is_revoked_with_its_refresh_token():
    """A rotated-away access token must not outlive revocation.

    It used to stay in _access_tokens while both mappings dropped it, so
    revoke_token could no longer reach it and it kept authenticating for the
    rest of its TTL - one unrevocable token per refresh.
    """
    provider = _provider()
    first = provider._issue_token_pair(
        client_id="c1", scopes=["mcp"], subject="alice-abcdefghijkl", resource=None
    )
    provider._remove_refresh_token(first.refresh_token)

    assert asyncio.run(provider.load_access_token(first.access_token)) is None


# ---------------------------------------------------------------------------
# Conditional Kimai fields need an actionable error, not a bare 400
# ---------------------------------------------------------------------------


def test_extra_field_rejection_explains_itself():
    """Kimai builds its API forms from the enabled features.

    `break` exists on the timesheet form only when 'Break time' is enabled, so
    the same request succeeds on one instance and fails on another with a
    message that names no field. Verified against a real instance that has the
    setting off.
    """
    from kimai_mcp.server import format_api_error

    text = format_api_error(KimaiAPIError(
        "Validation Failed", status_code=400,
        details={"errors": ["This form should not contain extra fields."]},
    ))
    assert "Break time" in text
    assert "Settings > Timesheet" in text
    assert "should not contain extra fields" in text  # raw details still shown


def test_ordinary_validation_error_gets_no_break_hint():
    from kimai_mcp.server import format_api_error

    text = format_api_error(KimaiAPIError(
        "Validation Failed", status_code=400,
        details={"errors": {"begin": ["This value is not valid."]}},
    ))
    assert "Break time" not in text
