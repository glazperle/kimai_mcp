"""Shared helper for discovering users accessible to the current API token."""


from ..client import KimaiClient
from .batch_utils import execute_batch
from .lookups import best_effort


async def resolve_accessible_users(client: KimaiClient) -> list:
    """Resolve all users the current user has access to (teams-first approach).

    Strategy:
    1. Try to get users from teams (works for team leads and admins):
       get_teams(), then fetch each team in parallel (concurrency-limited via
       execute_batch) and collect the members. Failures of individual teams are
       skipped.
    2. If no users were found via teams, fall back to get_users()
       (requires higher permissions). Errors from this fallback (e.g. 403)
       propagate to the caller.

    Returns:
        Deduplicated list of user objects (not just IDs).
    """
    accessible_users = []
    seen_user_ids = set()

    # Try to get users from teams (works for team leads and admins)
    try:
        teams = await client.get_teams()
    # Teams are only the first discovery path; on any failure (403 for plain
    # users, API error) we fall through to get_users below.
    except Exception:  # noqa: BLE001
        teams = []

    if teams:
        # Fetch team details in parallel; teams we cannot access are dropped.
        team_details, _failed = await execute_batch(
            [team.id for team in teams], client.get_team
        )
        for team_detail in team_details:
            if team_detail.members:
                for member in team_detail.members:
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
