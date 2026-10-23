"""Best-effort lookups that only decorate a result (names, notes)."""

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import TypeVar

from ..client import KimaiAPIError, KimaiClient
from ..models import ActivityFilter, Project, ProjectFilter, UserFilter

T = TypeVar("T")


async def best_effort(fetch: Awaitable[T]) -> T | None:
    """Await ``fetch``; None on any failure except a 401.

    For lookups that only decorate a result: ``GET /users`` needs view_user
    (super admins by default) and a proxy may answer with HTML, so a failure
    drops the decoration instead of the result. A 401 means the token is gone
    and propagates, as everywhere: the server rebuilds the session on it.
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


async def record_names(client: KimaiClient, projects_only: bool = False) -> RecordNames:
    """Every project, activity and user name the token may list.

    Hidden and finished projects and activities too (a record keeps its
    project after that one is hidden). Users need view_user; without it only
    the caller is named. ``projects_only`` skips the activities and users.
    """
    # By default Kimai lists only visible projects running today.
    projects = best_effort(client.get_projects(ProjectFilter.everything()))
    if projects_only:
        return RecordNames(projects={p.id: p for p in await projects or []})
    projects, activities, users = await asyncio.gather(
        projects,
        best_effort(client.get_activities(ActivityFilter(visible=3))),
        best_effort(client.get_users(UserFilter(visible=3))),
    )
    if users is None:
        me = await best_effort(client.get_current_user())
        users = [me] if me is not None else []
    return RecordNames(
        projects={p.id: p for p in projects or []},
        activities={a.id: a.name for a in activities or []},
        users={u.id: u.alias or u.username for u in users},
    )
