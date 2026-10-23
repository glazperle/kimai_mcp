"""Shared helper for discovering users accessible to the current API token."""


from ..client import KimaiAPIError, KimaiClient
from .batch_utils import read_batch
from .lookups import best_effort


async def resolve_accessible_users(client: KimaiClient) -> list:
    """Resolve all users the current user has access to (teams-first approach).

    Strategy:
    1. Try to get users from teams (works for team leads and admins):
       get_teams(), then fetch each team in parallel (concurrency-limited via
       read_batch) and collect the members. A team this token may not open
       (403, 404) is skipped; any other failure is raised, because a member
       list missing one team would silently shrink every "all users"
       operation, lock_month included.
    2. If the teams name nobody (403 on /teams, no teams, no members), fall
       back to get_users() (requires higher permissions). Errors from this
       fallback (e.g. 403) propagate to the caller.

    Returns:
        Deduplicated list of user objects (not just IDs).
    """
    accessible_users = []
    seen_user_ids = set()

    # Try to get users from teams (works for team leads and admins)
    try:
        teams = await client.get_teams()
    # Teams are only the first discovery path: a token that may not list teams
    # (403) falls through to get_users below. Anything else, a 401, a timeout or
    # a 5xx the client already retried, is the real error: asking /users as
    # well would double the wait and could hide it behind a 403.
    except KimaiAPIError as e:
        if e.status_code != 403:
            raise
        teams = []

    if teams:
        # Fetch team details in parallel; teams we cannot access are dropped.
        team_details, _skipped = await read_batch([team.id for team in teams], client.get_team)
        for team in team_details:
            for member in team.members or []:
                if member.user.id not in seen_user_ids:
                    seen_user_ids.add(member.user.id)
                    accessible_users.append(member.user)

    # If no users from teams, try get_users (requires higher permissions)
    if not accessible_users:
        accessible_users = list(await client.get_users())

    return accessible_users


async def own_records_note(client: KimaiClient, user_id: int | None) -> str | None:
    """A note for a result whose records all belong to the caller (``user_id``).

    Kimai returns only the records the token may see: its own without
    view_other_timesheet (any user filter is then ignored), its own and those
    of the teams it leads without view_all_data. When every record is the
    caller's, other users' records may be hidden rather than absent. The
    lookup only feeds this note, so any failure skips the note instead of
    failing the result; a 401 (token gone) propagates, as everywhere.
    """
    me = await best_effort(client.get_current_user())
    if me is None or user_id != me.id:
        return None
    return (
        "Note: every record returned is your own. Kimai returns only the records this token may see "
        "(its own without view_other_timesheet; its own and those of teams it leads without "
        "view_all_data), so other users' records may be hidden rather than absent."
    )
