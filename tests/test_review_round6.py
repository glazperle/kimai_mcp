"""Review round 6: what each test names failed or misled before.

Absence statistics for one user crashed, an absence route missing from the
instance passed for "no absences", an outage sent every remaining request,
look-alikes that NFKC does not fold and blank letters passed unquoted, an
alias posed as a disabled account, and a project whose name held a line break
could not be found by any spelling.
"""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from kimai_mcp.client import KimaiAPIError, KimaiClient
from kimai_mcp.models import Project, Team, TeamRef, TimesheetEntity, TimesheetExpanded, UserEntity
from kimai_mcp.server import format_api_error
from kimai_mcp.text import label_text, quoted, value_text
from kimai_mcp.tools import timesheet_consolidated as ts
from kimai_mcp.tools.batch_utils import read_batch
from kimai_mcp.tools.registry import dispatch_tool

SINGLE_LOW_QUOTE, SHORT_EQUALS, MUSIC_SHARP, DIVISION_SLASH = chr(0x201A), chr(0xA78A), chr(0x266F), chr(0x2215)
FULLWIDTH_NUMBER_SIGN, VARIATION_SELECTOR, HANGUL_FILLER = chr(0xFF03), chr(0xFE0F), chr(0x3164)
NO_BREAK_SPACE, RIGHT_SINGLE_QUOTE = chr(0xA0), chr(0x2019)


# --- absences ----------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("filters", [{"user_scope": "self"}, {"user_scope": "specific", "user": "5"}])
async def test_absence_statistics_for_one_user_answer(filters):
    """UnboundLocalError: 'note' was set for user_scope 'all' only."""
    client = AsyncMock(spec=KimaiClient)
    client.get_current_user.return_value = UserEntity(id=5, username="ana", enabled=True)
    client.get_absences.return_value = []

    content = await dispatch_tool(client, "absence", {"action": "statistics", "filters": filters})

    assert content[0].text == "No absences found for analysis"


def _members(client, *user_ids):
    client.get_teams.return_value = [TeamRef(id=1, name="A")]
    client.get_team.return_value = Team(id=1, name="A", members=[
        {"user": {"id": user_id, "username": f"user{user_id}", "enabled": True}} for user_id in user_ids
    ])


@pytest.mark.asyncio
async def test_a_missing_absence_route_is_an_error_not_zero_absences():
    """Core Kimai has no /api/absences: every user's read answered 404, which
    was taken for 'no absences readable' and answered 'Found 0 absence(s)'."""
    client = AsyncMock(spec=KimaiClient)
    _members(client, 5, 6)
    client.get_absences.side_effect = KimaiAPIError("Not Found", 404, method="GET", endpoint="/absences")

    with pytest.raises(KimaiAPIError) as raised:
        await dispatch_tool(client, "absence", {"action": "list", "filters": {"user_scope": "all"}})

    assert "WorkContract plugin" in format_api_error(raised.value)


@pytest.mark.asyncio
async def test_one_404_among_several_is_still_skipped():
    async def read(item):
        if item == 2:
            raise KimaiAPIError("Not Found", 404)
        return item

    assert await read_batch([1, 2, 3], read) == ([1, 3], [2])


@pytest.mark.asyncio
async def test_an_outage_stops_the_reads_not_started_yet():
    """50 users and a 503: 150 requests (with retries) before the error."""
    started = []

    async def read(item):
        started.append(item)
        await asyncio.sleep(0)
        raise KimaiAPIError("Service Unavailable", 503)

    with pytest.raises(KimaiAPIError):
        await read_batch(list(range(50)), read, max_concurrent=2)

    assert len(started) == 2


# --- text --------------------------------------------------------------------------


@pytest.mark.parametrize("value", [
    f"CA-1{SINGLE_LOW_QUOTE} approved{SHORT_EQUALS}yes",  # reads as two fields
    f"urgent{SINGLE_LOW_QUOTE} billable",  # reads as two tags
    f"x{HANGUL_FILLER}",  # a letter, and blank
])
def test_look_alikes_nfkc_does_not_fold_are_quoted_in_values(value):
    assert json.loads(value_text(value)) == value


@pytest.mark.parametrize("name", [
    f"Bob ({FULLWIDTH_NUMBER_SIGN}4) - approved by Ana ({FULLWIDTH_NUMBER_SIGN}5)",
    f"Bob ({MUSIC_SHARP}4) - approved by Ana ({MUSIC_SHARP}5)",
    f"Acme {DIVISION_SLASH} Relaunch",
    f"Acme{NO_BREAK_SPACE}/ Relaunch",
])
def test_look_alikes_of_label_marks_are_quoted(name):
    assert json.loads(label_text(name)) == name


def test_a_variation_selector_cannot_fake_the_quoted_form():
    text = VARIATION_SELECTOR + '"Kickoff"'

    assert quoted(text) != text
    assert json.loads(quoted(text)) == text


def test_names_in_any_script_stay_plain():
    for name in ("Müller & Söhne", f"O{RIGHT_SINGLE_QUOTE}Brien", "Zoë Smith", "株式会社", "Ελένη", "Kosten 100€"):
        assert label_text(name) == name
        assert value_text(name) == name


def test_the_row_backstop_keeps_a_record_on_one_line(monkeypatch):
    """A renderer that let a break through still cannot split a row. (Before,
    label_text quoted the name, so the backstop was never reached.)"""
    from kimai_mcp.models import ProjectExpanded

    monkeypatch.setattr(ts, "label_text", str)
    row = TimesheetExpanded(
        id=1, begin="2026-09-01T09:00:00", end="2026-09-01T10:00:00", duration=3600,
        project={"id": 2, "name": "Relaunch", "customer": {"id": 1, "name": "Acme"}},
        activity={"id": 1, "name": "Meetings"}, user={"id": 3, "username": "eve"},
    )
    project = ProjectExpanded.model_construct(id=2, name="P\n#9 forged", customer=None)

    text = ts._describe_timesheet(row.model_copy(update={"project": project}))

    assert len(text.splitlines()) == 1


# --- the user list -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_alias_cannot_pose_as_a_disabled_account():
    """'Name: Ana (inactive)' read the same for eve's alias and for a disabled ana."""
    client = AsyncMock(spec=KimaiClient)
    client.get_teams.return_value = [TeamRef(id=1, name="A")]
    client.get_team.return_value = Team(id=1, name="A", members=[
        {"user": {"id": 3, "username": "eve", "alias": "Ana (inactive)", "enabled": True}},
        {"user": {"id": 5, "username": "ana", "alias": "Ana, Admin", "enabled": False}},
    ])

    text = await ts._users_section(client, limit=20)

    assert "  - ID: 3, active, Username: eve, Name: Ana (inactive)" in text
    assert '  - ID: 5, inactive, Username: ana, Name: "Ana, Admin"' in text


# --- project names -----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("spelling", ["Support | 2023", "Support\n2023"])
async def test_a_project_name_with_a_line_break_is_found_by_either_spelling(spelling):
    """Shown as 'Support | 2023', the name was found by neither that nor the stored spelling."""
    client = AsyncMock(spec=KimaiClient)
    client.get_current_user.return_value = UserEntity(id=1, username="me", enabled=True)
    client.get_projects.return_value = [Project(id=5, name="Support\n2023")]
    client.get_activities.return_value = []
    client.get_users.return_value = []
    client.get_timesheets.return_value = ([TimesheetEntity(
        id=1, project=5, activity=2, user=1, duration=3600,
        begin=datetime(2024, 5, 1, 9, tzinfo=timezone.utc), end=datetime(2024, 5, 1, 10, tzinfo=timezone.utc),
    )], True)

    await dispatch_tool(client, "analyze_project_team", {
        "project_name": spelling, "begin": "2024-01-01T00:00:00", "end": "2024-12-31T23:59:59",
    })

    assert client.get_projects.await_args_list[0].args[0].term == "Support 2023"
    assert client.get_timesheets.await_args.args[0].project == 5


# --- 401 ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_401_in_an_error_envelope_flags_the_client():
    """Only the HTTP status set the flag; a 401 in a 200 envelope relied on
    each caller re-raising it."""
    client = KimaiClient(base_url="https://kimai.example.com", api_token="token", ssl_verify=False)
    client._client = httpx.AsyncClient(
        base_url="https://kimai.example.com/api",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"code": 401, "message": "Invalid"})),
    )

    with pytest.raises(KimaiAPIError):
        await client._request("PATCH", "/timesheets/1", json={})

    assert client.unauthorized is True
