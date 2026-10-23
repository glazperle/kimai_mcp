"""Best-effort lookups that only decorate a result (names, notes)."""

import asyncio
from collections.abc import Awaitable, Collection
from dataclasses import dataclass, field
from typing import TypeVar

from ..client import KimaiAPIError, KimaiClient
from ..models import Activity, ActivityFilter, Project, ProjectFilter, User, UserFilter

T = TypeVar("T")

# Up to this many projects the activity lookup asks for theirs only (Kimai adds
# the global activities); beyond, the query string would grow too long.
_ACTIVITY_PROJECTS_LIMIT = 100


async def best_effort(fetch: Awaitable[T]) -> T | None:
    """Await ``fetch``; None on any failure except a 401.

    For lookups that only decorate a result: ``GET /users`` needs view_user
    (super admins by default) and a proxy may answer with HTML, so a failure
    drops the decoration instead of the result. A 401 means the token is gone
    and propagates, as everywhere: the answer is then an error, not a result
    missing its names. (The server notices the 401 through the client's
    ``unauthorized`` flag either way.)
    """
    try:
        return await fetch
    except KimaiAPIError as e:
        if e.status_code == 401:
            raise
        return None
    except Exception:  # noqa: BLE001 - decoration only; IDs are shown instead
        return None


@dataclass
class RecordNames:
    """Names for the IDs of ``TimesheetEntity`` rows; an unknown ID stays an ID."""

    projects: dict[int, Project] = field(default_factory=dict)
    activities: dict[int, str] = field(default_factory=dict)
    users: dict[int, str] = field(default_factory=dict)


async def _nothing() -> list:
    return []


async def _users(client: KimaiClient) -> list[User]:
    """Every user, or the caller alone where the token lacks view_user.

    That 403 is role-wide (view_user is a super-admin permission by default),
    so the client remembers it instead of asking again on every listing.
    """
    if not getattr(client, "users_list_denied", False):
        try:
            return await client.get_users(UserFilter(visible=3))
        except Exception as e:  # names only; the caller is named instead
            if isinstance(e, KimaiAPIError) and e.status_code == 401:
                raise
            if isinstance(e, KimaiAPIError) and e.status_code == 403:
                client.users_list_denied = True
    me = await best_effort(client.get_current_user())
    return [me] if me is not None else []


async def record_names(
    client: KimaiClient, activities_of: Collection[int] | None = None, users: bool = False
) -> RecordNames:
    """Project names, and the activity and user names that will be printed.

    Hidden and finished projects and activities too (a record keeps its
    project after that one is hidden). ``activities_of`` names the projects
    whose activities are wanted (Kimai adds the global ones); None skips the
    activities. Users need view_user; without it only the caller is named.
    """
    if activities_of is None:
        activity_fetch: Awaitable[list[Activity] | None] = _nothing()
    else:
        projects = sorted(activities_of)
        wanted = ActivityFilter(visible=3, projects=projects if len(projects) <= _ACTIVITY_PROJECTS_LIMIT else None)
        activity_fetch = best_effort(client.get_activities(wanted))
    project_list, activity_list, user_list = await asyncio.gather(
        # By default Kimai lists only visible projects running today.
        best_effort(client.get_projects(ProjectFilter.everything())),
        activity_fetch,
        _users(client) if users else _nothing(),
    )
    return RecordNames(
        projects={p.id: p for p in project_list or []},
        activities={a.id: a.name for a in activity_list or []},
        users={u.id: u.alias or u.username for u in user_list},
    )
