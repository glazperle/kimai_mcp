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


_PERIOD = {"begin": "2024-01-01T00:00:00", "end": "2024-12-31T23:59:59"}


@pytest.mark.asyncio
async def test_project_analysis_prefers_the_exact_name():
    """Searching finished projects too must not make a running 'Support' ambiguous
    next to a finished 'Support 2023'."""
    client = _client()
    client.get_projects.return_value = [Project(id=1, name="Support"), Project(id=2, name="Support 2023")]

    await dispatch_tool(client, "analyze_project_team", {"project_name": "support", **_PERIOD})

    assert client.get_timesheets.await_args.args[0].project == 1


@pytest.mark.asyncio
async def test_project_analysis_prefers_the_visible_one_of_two_equal_names():
    client = _client()
    client.get_projects.return_value = [
        Project(id=1, name="Website", visible=False), Project(id=2, name="Website"),
    ]

    await dispatch_tool(client, "analyze_project_team", {"project_name": "Website", **_PERIOD})

    assert client.get_timesheets.await_args.args[0].project == 2


@pytest.mark.asyncio
async def test_project_analysis_takes_a_project_id():
    client = _client()
    client.get_project.return_value = Project(id=9, name="Website")

    await dispatch_tool(client, "analyze_project_team", {"project_id": 9, **_PERIOD})

    client.get_projects.assert_not_called()
    assert client.get_timesheets.await_args.args[0].project == 9


@pytest.mark.asyncio
async def test_project_analysis_refuses_a_truncated_dataset():
    """get_timesheets stops at 100 pages of 50 with fetched_all=False; analysing
    those 5000 rows as if they were all used to report silently wrong totals."""
    from kimai_mcp.tools.errors import ToolError

    client = _client()
    rows, _, _ = client.get_timesheets.return_value
    client.get_timesheets.return_value = (rows, False, 100)

    with pytest.raises(ToolError, match="Dataset too large"):
        await dispatch_tool(client, "analyze_project_team", {"project_name": "Relaunch", **_PERIOD})


@pytest.mark.asyncio
async def test_project_analysis_team_falls_back_when_users_filter_is_refused():
    """users[] runs access_user per member: a disabled member makes it a 403
    for a teamlead. Fetch everyone's records then and keep the team's."""
    from kimai_mcp.client import KimaiAPIError

    client = _client()
    member = TeamMember(user=User(id=5, username="ana", enabled=False))
    client.get_team.return_value = Team(id=3, name="Web", members=[member])
    mine = TimesheetEntity(
        id=2, project=7, activity=2, user=5, duration=3600,
        begin=datetime(2024, 5, 1, 9, tzinfo=timezone.utc), end=datetime(2024, 5, 1, 10, tzinfo=timezone.utc),
    )
    other = mine.model_copy(update={"id": 3, "user": 8})
    client.get_timesheets.side_effect = [KimaiAPIError("Cannot access user: 5", 403), ([mine, other], True, 1)]

    text = (await dispatch_tool(client, "analyze_project_team", {
        "project_name": "Relaunch", "user_scope": "team", "team": 3, **_PERIOD,
    }))[0].text

    fallback = client.get_timesheets.await_args.args[0]
    assert (fallback.user, fallback.users) == ("all", None)
    assert "User ID 5" in text  # the member's record survives the post-filter
    assert "User ID 8" not in text
    assert "Kimai refused the team filter (Cannot access user: 5)" in text


@pytest.mark.asyncio
async def test_partial_matches_with_different_names_stay_ambiguous():
    """The visible-wins tie-break is for projects of the same name only."""
    from kimai_mcp.tools.errors import ToolError

    client = _client()
    client.get_projects.return_value = [
        Project(id=1, name="Support 2023", visible=False), Project(id=2, name="Support Hotline"),
    ]

    with pytest.raises(ToolError, match="Multiple projects found"):
        await dispatch_tool(client, "analyze_project_team", {"project_name": "Support", **_PERIOD})


@pytest.mark.asyncio
async def test_a_truncated_team_fallback_is_refused_not_reported_empty():
    """The size guard must run before the team filter: 5000 fetched rows with no
    team record among them used to read 'No timesheets found'."""
    from kimai_mcp.client import KimaiAPIError
    from kimai_mcp.tools.errors import ToolError

    client = _client()
    client.get_team.return_value = Team(id=3, name="Web", members=[TeamMember(user=User(id=5, username="a", enabled=True))])
    rows, _, _ = client.get_timesheets.return_value  # user 1 only, not in the team
    client.get_timesheets.side_effect = [KimaiAPIError("Cannot access user: 5", 403), (rows * 3, False, 100)]

    with pytest.raises(ToolError, match="at least 3 entries"):
        await dispatch_tool(client, "analyze_project_team", {
            "project_name": "Relaunch", "user_scope": "team", "team": 3, **_PERIOD,
        })


@pytest.mark.asyncio
async def test_missing_project_is_named_in_the_error():
    """A schema anyOf reported neither field; the handler's message names both."""
    from kimai_mcp.tools.errors import ToolError

    with pytest.raises(ToolError, match="project_name or project_id"):
        await dispatch_tool(_client(), "analyze_project_team", dict(_PERIOD))


@pytest.mark.asyncio
async def test_a_project_name_with_a_colon_is_matched_without_a_search_term():
    """Kimai reads 'ACME:Relaunch' as a search in meta field ACME."""
    client = _client()
    client.get_projects.return_value = [Project(id=4, name="ACME:Relaunch")]

    await dispatch_tool(client, "analyze_project_team", {"project_name": "ACME:Relaunch", **_PERIOD})

    assert client.get_projects.await_args.args[0].term is None
    assert client.get_timesheets.await_args.args[0].project == 4


@pytest.mark.asyncio
async def test_a_date_only_end_includes_that_day():
    client = _client()

    await dispatch_tool(client, "analyze_project_team", {
        "project_name": "Relaunch", "begin": "2025-01-01", "end": "2025-06-30",
    })

    assert client.get_timesheets.await_args.args[0].end.isoformat() == "2025-06-30T23:59:59"


@pytest.mark.asyncio
async def test_the_analysis_runs_without_permission_to_list_users():
    """GET /users needs view_user, a super-admin permission by default; names
    are cosmetic, so a 403 there must not stop the analysis."""
    from kimai_mcp.client import KimaiAPIError

    client = _client()
    client.get_users.side_effect = KimaiAPIError("Access denied", 403)

    text = (await dispatch_tool(client, "analyze_project_team", {"project_id": 7, **_PERIOD}))[0].text

    assert "User ID 1" in text
    assert "User names are not shown" in text


@pytest.mark.asyncio
async def test_the_analysis_fetches_in_pages_of_500():
    client = _client()
    client.get_project.return_value = Project(id=7, name="Relaunch 2024")

    await dispatch_tool(client, "analyze_project_team", {"project_id": 7, **_PERIOD})

    call = client.get_timesheets.await_args
    assert call.args[0].size == 500
    assert call.kwargs["fetch_all"] is True


@pytest.mark.asyncio
async def test_a_project_name_with_an_excluding_word_is_matched_without_a_term():
    """Kimai turns every word starting with '!' into an exclusion."""
    client = _client()
    client.get_projects.return_value = [Project(id=4, name="Website !Relaunch")]

    await dispatch_tool(client, "analyze_project_team", {"project_name": "Website !Relaunch", **_PERIOD})

    assert client.get_projects.await_args.args[0].term is None


@pytest.mark.asyncio
async def test_the_same_midnight_twice_is_that_whole_day():
    client = _client()

    await dispatch_tool(client, "analyze_project_team", {
        "project_id": 7, "begin": "2025-06-30T00:00:00", "end": "2025-06-30T00:00:00",
    })

    assert client.get_timesheets.await_args.args[0].end.isoformat() == "2025-06-30T23:59:59"
