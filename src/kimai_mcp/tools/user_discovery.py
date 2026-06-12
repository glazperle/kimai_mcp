"""Shared helper for discovering users accessible to the current API token."""

import asyncio
from typing import List

from ..client import KimaiClient

# Rate limiting: max parallel team detail requests
MAX_CONCURRENT = 10


async def resolve_accessible_users(client: KimaiClient) -> List:
    """Resolve all users the current user has access to (teams-first approach).

    Strategy:
    1. Try to get users from teams (works for team leads and admins):
       get_teams(), then fetch each team in parallel (max 10 concurrent)
       and collect the members. Failures of individual teams are skipped.
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
    except Exception:
        teams = []

    if teams:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)

        async def fetch_team(team_id: int):
            async with semaphore:
                return await client.get_team(team_id)

        team_details = await asyncio.gather(
            *[fetch_team(team.id) for team in teams],
            return_exceptions=True
        )

        for team_detail in team_details:
            if isinstance(team_detail, Exception):
                # Skip teams we cannot access
                continue
            if team_detail.members:
                for member in team_detail.members:
                    if member.user.id not in seen_user_ids:
                        seen_user_ids.add(member.user.id)
                        accessible_users.append(member.user)

    # If no users from teams, try get_users (requires higher permissions)
    if not accessible_users:
        accessible_users = list(await client.get_users())

    return accessible_users
