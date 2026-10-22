"""Project analysis tools for comprehensive timesheet analysis."""

import asyncio
from collections import defaultdict
from typing import Any

from mcp.types import TextContent, Tool

from ..client import KimaiAPIError, KimaiClient
from ..models import ActivityFilter, ProjectFilter, TimesheetFilter
from .dates import parse_local_datetime
from .errors import ToolError

# Safety limit: stop fetching timesheets once this many entries were collected
MAX_ANALYSIS_RESULTS = 10000


def analyze_project_team_tool() -> Tool:
    """Define the analyze project team tool."""
    return Tool(
        name="analyze_project_team",
        description="Comprehensive analysis of all team members working on a project. Automatically finds project by name, fetches ALL timesheets from ALL users, and provides detailed statistics.",
        input_schema={
            "type": "object",
            "required": ["begin", "end"],
            "anyOf": [{"required": ["project_name"]}, {"required": ["project_id"]}],
            "properties": {
                "project_name": {"type": "string", "description": "Project name (an exact name wins over partial matches)"},
                "project_id": {"type": "integer", "description": "Project ID, instead of project_name when names are ambiguous"},
                "begin": {"type": "string", "description": "Start date in local time, no offset or 'Z' (e.g., '2025-01-01' or '2025-01-01T08:00:00')"},
                "end": {"type": "string", "description": "End date in local time, no offset or 'Z' (e.g., '2025-06-30' or '2025-06-30T23:59:59')"},
                "user_scope": {
                    "type": "string", 
                    "enum": ["self", "all", "specific", "team"],
                    "description": "Analysis scope: 'self' (current user), 'all' (all users), 'specific' (particular user), 'team' (team members only). Default: 'all'"
                },
                "user": {"type": "string", "description": "Specific user ID (required if user_scope is 'specific')"},
                "team": {"type": "integer", "description": "Team ID (required if user_scope is 'team')"},
                "include_details": {"type": "boolean", "description": "Include detailed activity breakdown", "default": True}
            }
        }
    )


async def _find_project(client: KimaiClient, name: str):
    """The one project a name means: an exact name wins over partial matches,
    and among several with that name a visible one wins.

    Finished and hidden projects are searched too (the analysed period can be
    any), which is why the preferences are needed: a running 'Support' must
    still be found next to a finished 'Support 2023'.
    """
    projects = await client.get_projects(ProjectFilter.everything(term=name))
    wanted = name.casefold()
    matching = [p for p in projects if wanted in p.name.casefold()]
    if not matching:
        # Load all projects only to present available options
        all_projects = await client.get_projects(ProjectFilter.everything())
        raise ToolError(
            f"❌ No project found matching '{name}'. Available projects:\n" +
            "\n".join([f"• {p.name}" for p in all_projects[:10]])
        )

    candidates = [p for p in matching if p.name.casefold() == wanted] or matching
    if len(candidates) > 1:
        candidates = [p for p in candidates if p.visible] or candidates
    if len(candidates) > 1:
        project_list = "\n".join([f"• {p.name} (ID: {p.id})" for p in candidates])
        raise ToolError(
            f"⚠️ Multiple projects found matching '{name}':\n{project_list}\n\n"
            "Pass project_id, or a more specific name."
        )
    return candidates[0]


async def handle_analyze_project_team(client: KimaiClient, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle comprehensive project team analysis."""
    missing = [f for f in ("begin", "end") if not arguments.get(f)]
    if not arguments.get("project_name") and not arguments.get("project_id"):
        missing.insert(0, "project_name or project_id")
    if missing:
        raise ToolError(f"Error: Missing required fields: {', '.join(missing)}")

    project_name = arguments.get('project_name') or ""
    begin = parse_local_datetime(arguments['begin'], "begin")
    end = parse_local_datetime(arguments['end'], "end")
    include_details = arguments.get('include_details', True)

    try:
        # 1. Find the project (server-side term search, any visibility and period)
        if arguments.get('project_id'):
            project = await client.get_project(arguments['project_id'])
        else:
            project = await _find_project(client, project_name)

        # 2. Handle user scope selection
        user_scope = arguments.get('user_scope', 'all')
        user_filter = 'all'  # Default to all users
        
        if user_scope == 'self':
            # Current user only - don't set user filter (uses current user by default)
            user_filter = None
        elif user_scope == 'specific':
            if 'user' not in arguments:
                raise ToolError(
                    "❌ Error: When user_scope is 'specific', you must provide a 'user' parameter."
                )
            user_filter = arguments['user']
        elif user_scope == 'team':
            if 'team' not in arguments:
                raise ToolError(
                    "❌ Error: When user_scope is 'team', you must provide a 'team' parameter. Use team_list to see available teams."
                )
            # For team scope, we'll need to get team members first
            try:
                team = await client.get_team(arguments['team'])
                team_user_ids = [member.user.id for member in team.members]
                if not team_user_ids:
                    raise ToolError(f"❌ Team ID {arguments['team']} has no members.")
                # Kimai filters by several users itself (users[]), so the cap
                # below applies to the team's records, not to everyone's.
                user_filter = None
            except ToolError:
                raise
            # Anything else is turned into a client-facing tool error naming the team.
            except Exception as e:  # noqa: BLE001
                raise ToolError(
                    f"❌ Error accessing team {arguments['team']}: {e!s}"
                )
        
        # 3. Get timesheets for this project with user filtering
        filters = TimesheetFilter(
            project=project.id,
            begin=begin.isoformat(),
            end=end.isoformat(),
            user=user_filter,
            users=team_user_ids if user_scope == 'team' else None,
        )
        
        async def fetch_timesheets():
            try:
                return await client.get_timesheets(filters, max_results=MAX_ANALYSIS_RESULTS)
            except KimaiAPIError as e:
                # users[] runs access_user for every member, which is a 403 for
                # a disabled member unless the token sees everyone. Fetch all
                # and keep the team's records below, as before users[].
                if user_scope != 'team' or e.status_code != 403:
                    raise
                everyone = filters.model_copy(update={"user": "all", "users": None})
                return await client.get_timesheets(everyone, max_results=MAX_ANALYSIS_RESULTS)

        try:
            # 4. Fetch data in parallel for better performance.
            # The fetch is capped at MAX_ANALYSIS_RESULTS so huge datasets
            # don't get downloaded completely before the safety check.
            timesheets, users, activities = await asyncio.gather(
                fetch_timesheets(),
                # Names for every record, also of disabled users and hidden activities.
                client.get_users(visible=3, full=False),
                client.get_activities(ActivityFilter(visible=3))
            )
            timesheets, fetched_all, _last_page = timesheets
            if user_scope == 'team':
                # Also when Kimai ignored users[] (no view_other_timesheet) and
                # returned the caller's own records instead.
                timesheets = [ts for ts in timesheets if ts.user in team_user_ids]
        except KimaiAPIError as e:
            if e.status_code in (401, 403):
                raise ToolError(
                    f"❌ Insufficient permissions to access project '{project.name}' data.\n\n**Required permissions:**\n• `view_other_timesheet` - to see all team members\n• `view_user` - to access user information\n\n**Tip:** Try asking your Kimai admin to grant these permissions or use `user_scope: 'self'` to see only your own data."
                )
            elif e.status_code == 404:
                raise ToolError(
                    f"❌ Project '{project.name}' was found but some related data is not accessible. This might indicate deleted/archived data."
                )
            else:
                # Surface unexpected API errors with more context
                raise ToolError(
                    f"❌ API Error while analyzing project '{project.name}': {e!s}\n\nPlease check your Kimai connection and try again."
                )

        if not timesheets:
            return [TextContent(
                type="text",
                text=f"📋 No timesheets found for project '{project.name}' in the specified period."
            )]

        # Safety check: the fetch stopped before the end (max_results, or the
        # client's page cap, which comes first: 100 pages of 50).
        if not fetched_all:
            raise ToolError(
                f"⚠️ Dataset too large: more than {len(timesheets)} entries found for project '{project.name}' (fetch stopped there).\n\nPlease narrow down the date range (currently {begin.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}) or filter by specific users to ensure optimal performance."
            )
        
        # Create lookup dictionaries
        user_lookup = {}
        for u in users:
            display_name = u.username
            if hasattr(u, 'alias') and u.alias:
                display_name = f"{u.alias} ({u.username})"
            elif hasattr(u, 'title') and u.title:
                display_name = f"{u.username} - {u.title}"
            user_lookup[u.id] = display_name
        activity_lookup = {a.id: a.name for a in activities}
        
        # 4. Analyze data
        user_stats = defaultdict(lambda: {
            'total_duration': 0,
            'total_entries': 0,
            'activities': defaultdict(lambda: {'duration': 0, 'entries': 0}),
            'user_info': ''
        })
        
        total_project_duration = 0
        unique_users: set[int] = set()
        unique_activities: set[int] = set()
        
        for ts in timesheets:
            user_id = ts.user
            activity_id = ts.activity
            duration = ts.duration or 0
            
            unique_users.add(user_id)
            unique_activities.add(activity_id)
            total_project_duration += duration
            
            # User stats
            user_stats[user_id]['total_duration'] += duration
            user_stats[user_id]['total_entries'] += 1
            user_stats[user_id]['user_info'] = user_lookup.get(user_id, f"User ID {user_id}")
            
            # Activity stats per user
            user_stats[user_id]['activities'][activity_id]['duration'] += duration
            user_stats[user_id]['activities'][activity_id]['entries'] += 1
        
        # 5. Format results
        result_parts = []
        
        # Header
        result_parts.append(f"""# 📊 Project Team Analysis: {project.name}

**Period:** {begin.strftime('%d.%m.%Y')} - {end.strftime('%d.%m.%Y')}
**Total Duration:** {total_project_duration // 3600}h {(total_project_duration % 3600) // 60}m
**Team Members:** {len(unique_users)}
**Activities:** {len(unique_activities)}
**Total Entries:** {len(timesheets)}

---""")
        
        # Sort users by total duration (descending)
        sorted_users = sorted(user_stats.items(), key=lambda x: x[1]['total_duration'], reverse=True)
        
        for user_id, stats in sorted_users:
            hours = stats['total_duration'] // 3600
            minutes = (stats['total_duration'] % 3600) // 60
            percentage = (stats['total_duration'] / total_project_duration * 100) if total_project_duration > 0 else 0
            
            result_parts.append(f"""## 👤 {stats['user_info']}
**Total Time:** {hours}h {minutes}m ({percentage:.1f}% of project)
**Entries:** {stats['total_entries']}""")
            
            if include_details and stats['activities']:
                result_parts.append("**Activities:**")
                # Sort activities by duration
                sorted_activities = sorted(stats['activities'].items(), key=lambda x: x[1]['duration'], reverse=True)
                
                for activity_id, activity_stats in sorted_activities:
                    activity_name = activity_lookup.get(activity_id, f"Activity {activity_id}")
                    act_hours = activity_stats['duration'] // 3600
                    act_minutes = (activity_stats['duration'] % 3600) // 60
                    act_percentage = (activity_stats['duration'] / stats['total_duration'] * 100) if stats['total_duration'] > 0 else 0
                    
                    result_parts.append(f"  • {activity_name}: {act_hours}h {act_minutes}m ({act_percentage:.1f}%) - {activity_stats['entries']} entries")
            
            result_parts.append("---")
        
        # Summary
        if len(sorted_users) > 1:
            top_contributor = sorted_users[0]
            top_hours = top_contributor[1]['total_duration'] // 3600
            top_percentage = (top_contributor[1]['total_duration'] / total_project_duration * 100) if total_project_duration > 0 else 0
            
            result_parts.append(f"""## 📈 Summary
**Top Contributor:** {top_contributor[1]['user_info']} ({top_hours}h, {top_percentage:.1f}%)
**Team Distribution:** Most work concentrated among top {min(3, len(sorted_users))} contributors
**Project Status:** Active with {len(timesheets)} logged entries""")
        
        return [TextContent(type="text", text="\n".join(result_parts))]

    except ToolError:
        # Already a clean, client-facing error; let the central handler mark is_error.
        raise
    except KimaiAPIError:
        # Let the central handler format it via format_api_error (with is_error).
        raise
    # Everything else becomes a tool error so the client sees is_error instead of
    # an opaque crash from the middle of the analysis.
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"❌ Error during analysis: {e!s}")