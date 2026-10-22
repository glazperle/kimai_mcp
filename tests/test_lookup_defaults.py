"""Internal lookups must not inherit Kimai's narrow listing defaults.

GET /projects returns only visible projects running *today* unless the request
names a day or sets ignoreDates (ProjectController::cgetAction), and the
activity and user listings default to visible records. A lookup that resolves
names or finds a project for a past period has to ask for everything, or a
finished project "does not exist" and a disabled user shows up as a bare ID.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from kimai_mcp.client import KimaiClient
from kimai_mcp.models import Project, Team, TeamMember, TimesheetEntity, User, UserEntity
from kimai_mcp.tools.registry import dispatch_tool


def _client() -> AsyncMock:
    client = AsyncMock(spec=KimaiClient)
    client.get_current_user.return_value = UserEntity(id=1, username="me", enabled=True)
    client.get_projects.return_value = [Project(id=7, name="Relaunch 2024")]
    client.get_activities.return_value = []
    client.get_users.return_value = []
    record = TimesheetEntity(
        id=1, project=7, activity=2, user=1, duration=3600,
        begin=datetime(2024, 5, 1, 9, tzinfo=timezone.utc), end=datetime(2024, 5, 1, 10, tzinfo=timezone.utc),
    )
    client.get_timesheets.return_value = ([record], True, 1)
    return client


@pytest.mark.asyncio
async def test_project_analysis_finds_finished_and_hidden_projects():
    client = _client()
    await dispatch_tool(client, "analyze_project_team", {
        "project_name": "Relaunch", "begin": "2024-01-01T00:00:00", "end": "2024-12-31T23:59:59",
    })

    project_filter = client.get_projects.await_args.args[0]
    assert project_filter.visible == 3
    assert project_filter.ignore_dates == "1"
    assert client.get_users.await_args.kwargs["visible"] == 3
    assert client.get_activities.await_args.args[0].visible == 3


@pytest.mark.asyncio
async def test_project_analysis_filters_a_team_on_the_server():
    client = _client()
    member = TeamMember(user=User(id=5, username="ana", enabled=True))
    client.get_team.return_value = Team(id=3, name="Web", members=[member])

    await dispatch_tool(client, "analyze_project_team", {
        "project_name": "Relaunch", "begin": "2024-01-01T00:00:00", "end": "2024-12-31T23:59:59",
        "user_scope": "team", "team": 3,
    })

    timesheet_filter = client.get_timesheets.await_args.args[0]
    assert timesheet_filter.users == [5]
    assert timesheet_filter.user is None


@pytest.mark.asyncio
async def test_statistics_name_finished_projects():
    client = _client()
    text = (await dispatch_tool(client, "timesheet", {
        "action": "list", "filters": {"calculate_stats": True},
    }))[0].text

    project_filter = client.get_projects.await_args.args[0]
    assert (project_filter.visible, project_filter.ignore_dates) == (3, "1")
    assert "Relaunch 2024" in text
