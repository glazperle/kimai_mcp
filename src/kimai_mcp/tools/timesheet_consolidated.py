"""Consolidated Timesheet tools for all timesheet operations."""

import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from mcp.types import Tool, TextContent
from ..client import KimaiClient
from ..models import TimesheetEditForm, TimesheetFilter, MetaFieldForm
from .timesheet_analytics import TimesheetAnalytics
from .batch_utils import execute_batch, format_batch_result


def timesheet_tool() -> Tool:
    """Define the consolidated timesheet management tool."""
    return Tool(
        name="timesheet",
        description="Consolidated timesheet management tool for list, get, create, update, delete, duplicate, and export operations.",
        inputSchema={
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "update", "delete", "duplicate", "export_toggle", "meta_update", "user_guide", "batch_delete", "batch_export"],
                    "description": """The action to perform:
                    - list: List timesheets
                    - create: Create a new timesheet
                    - get: Get a timesheet by ID
                    - update: Update a timesheet by ID
                    - delete: Delete a timesheet by ID
                    - duplicate: Duplicate a timesheet by ID
                    - export_toggle: Toggle export status (bool) for a timesheet by ID
                    - meta_update: Update meta fields for a timesheet by ID
                    - user_guide: Gives information about how to limit users when listing timesheets and lists available users.
                    - batch_delete: Delete multiple timesheets by IDs
                    - batch_export: Mark multiple timesheets as exported by IDs
                    """
                },
                "id": {
                    "type": "integer",
                    "description": "Timesheet ID (required for get, update, delete, duplicate, export_toggle, meta_update)"
                },
                "ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of timesheet IDs for batch operations (batch_delete, batch_export)"
                },
                "filters": {
                    "type": "object",
                    "description": "Filters for list action",
                    "properties": {
                        "user_scope": {
                            "type": "string",
                            "enum": ["self", "all", "specific"],
                            "description": "User scope: 'self' (current user), 'all' (all users), 'specific' (particular user)"
                        },
                        "user": {
                            "type": "string",
                            "description": "User ID when user_scope is 'specific'"
                        },
                        "project": {"type": "integer"},
                        "activity": {"type": "integer"},
                        "customer": {"type": "integer"},
                        "begin": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Start date and time filter (format: YYYY-MM-DDThh:mm:ss, e.g., 2023-10-27T09:30:00)."
                        },
                        "end": {
                            "type": "string",
                            "format": "date-time",
                            "description": "End date and time filter (format: YYYY-MM-DDThh:mm:ss, e.g., 2023-10-27T17:00:00)."
                        },
                        "exported": {"type": "integer", "enum": [0, 1]},
                        "active": {"type": "integer", "enum": [0, 1]},
                        "billable": {"type": "integer", "enum": [0, 1]},
                        "page": {"type": "integer", "default": 1, "description": "Page number for pagination. Default is 1."},
                        "size": {"type": "integer", "default": 50, "description": "Number of records per page. Default is 50."},
                        "term": {"type": "string"},
                        "include_user_list": {"type": "boolean", "default": False},
                        "calculate_stats": {"type": "boolean", "default": False, "description": "Calculate statistics from the results"},
                        "stats_format": {"type": "string", "enum": ["summary", "detailed", "json"], "default": "summary"},
                        "breakdown_by_year": {"type": "boolean", "default": False, "description": "Break down statistics by year (auto-enabled if time span > 1 year)"}
                    }
                },
                "data": {
                    "type": "object",
                    "description": "Data for create/update actions",
                    "properties": {
                        "project": {"type": "integer"},
                        "activity": {"type": "integer"},
                        "begin": {"type": "string", "format": "date-time"},
                        "end": {"type": "string", "format": "date-time"},
                        "description": {"type": "string"},
                        "tags": {"type": "string"},
                        "user": {"type": "integer"},
                        "billable": {"type": "boolean"},
                        "fixedRate": {"type": "number"},
                        "hourlyRate": {"type": "number"},
                        "break": {"type": "integer", "description": "Break duration in seconds"}
                    }
                },
                "meta": {
                    "type": "array",
                    "description": "Meta fields for meta_update action",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "value": {}
                        }
                    }
                },
                "show_users": {
                    "type": "boolean",
                    "description": "Show available users (for user_guide action)",
                    "default": True
                }
            }
        }
    )


def timer_tool() -> Tool:
    """Define the timer management tool."""
    return Tool(
        name="timer",
        description="Timer management tool for start, stop, restart, and active timer operations.",
        inputSchema={
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "restart", "active", "recent"],
                    "description": "The timer action to perform"
                },
                "id": {
                    "type": "integer",
                    "description": "Timesheet ID (required for stop and restart actions)"
                },
                "data": {
                    "type": "object",
                    "description": "Data for start action",
                    "properties": {
                        "project": {"type": "integer", "description": "Project ID"},
                        "activity": {"type": "integer", "description": "Activity ID"},
                        "description": {"type": "string", "description": "Timer description"},
                        "tags": {"type": "string", "description": "Comma-separated tags"}
                    }
                },
                "size": {
                    "type": "integer",
                    "description": "Number of recent entries to return (for recent action)",
                    "default": 10
                },
                "begin": {
                    "type": "string",
                    "format": "date-time",
                    "description": "Only entries after this date (for recent action)"
                }
            }
        }
    )


async def handle_timesheet(client: KimaiClient, **params) -> List[TextContent]:
    """Handle consolidated timesheet operations."""
    action = params.get("action")
    
    if action == "list":
        return await _handle_timesheet_list(client, params.get("filters", {}))
    elif action == "get":
        return await _handle_timesheet_get(client, params.get("id"))
    elif action == "create":
        return await _handle_timesheet_create(client, params.get("data", {}))
    elif action == "update":
        return await _handle_timesheet_update(client, params.get("id"), params.get("data", {}))
    elif action == "delete":
        return await _handle_timesheet_delete(client, params.get("id"))
    elif action == "duplicate":
        return await _handle_timesheet_duplicate(client, params.get("id"))
    elif action == "export_toggle":
        return await _handle_timesheet_export_toggle(client, params.get("id"))
    elif action == "meta_update":
        return await _handle_timesheet_meta_update(client, params.get("id"), params.get("meta", []))
    elif action == "user_guide":
        return await _handle_timesheet_user_guide(client, params.get("show_users", True))
    elif action == "batch_delete":
        return await _handle_batch_delete(client, params.get("ids", []))
    elif action == "batch_export":
        return await _handle_batch_export(client, params.get("ids", []))
    else:
        return [TextContent(
            type="text",
            text=f"Error: Unknown action '{action}'. Valid actions: list, get, create, update, delete, duplicate, export_toggle, meta_update, user_guide, batch_delete, batch_export"
        )]


async def handle_timer(client: KimaiClient, **params) -> List[TextContent]:
    """Handle timer operations."""
    action = params.get("action")
    
    if action == "start":
        return await _handle_timer_start(client, params.get("data", {}))
    elif action == "stop":
        return await _handle_timer_stop(client, params.get("id"))
    elif action == "restart":
        return await _handle_timer_restart(client, params.get("id"))
    elif action == "active":
        return await _handle_timer_active(client)
    elif action == "recent":
        return await _handle_timer_recent(client, params.get("size", 10), params.get("begin"))
    else:
        return [TextContent(
            type="text",
            text=f"Error: Unknown action '{action}'. Valid actions: start, stop, restart, active, recent"
        )]


# Timesheet action handlers
async def _handle_timesheet_list(client: KimaiClient, filters: Dict) -> List[TextContent]:
    """Handle timesheet list action."""
    from datetime import datetime

    # Handle user scope
    user_scope = filters.get("user_scope", "self")
    user_filter = None
    
    if user_scope == "self":
        current_user = await client.get_current_user()
        user_filter = str(current_user.id)
    elif user_scope == "specific":
        user_filter = filters.get("user")
        if not user_filter:
            return [TextContent(type="text", text="Error: 'user' parameter required when user_scope is 'specific'")]
    elif user_scope == "all":
        user_filter = "all"  # API requires explicit "all" to return all users' timesheets

    begin_datetime = None
    if "begin" in filters:
        try:
            begin_datetime = datetime.fromisoformat(filters["begin"])
        except ValueError:
            return [TextContent(type="text",
                                text=f"Error: Invalid date time format for field begin '{filters['begin']}'. Use ISO format (YYYY-MM-DDTHH:MM:SS)")]

    end_datetime = None
    if "end" in filters:
        try:
            end_datetime = datetime.fromisoformat(filters["end"])
        except ValueError:
            return [TextContent(type="text",
                                text=f"Error: Invalid date time format for field end '{filters['end']}'. Use ISO format (YYYY-MM-DDTHH:MM:SS)")]


    if begin_datetime == end_datetime and begin_datetime.time() == datetime.min.time():
        end_datetime = begin_datetime + timedelta(days=1)
    
    # Build filter
    timesheet_filter = TimesheetFilter(
        user=user_filter,
        project=filters.get("project"),
        activity=filters.get("activity"),
        customer=filters.get("customer"),
        begin=begin_datetime,
        end=end_datetime,
        exported=filters.get("exported"),
        active=filters.get("active"),
        billable=filters.get("billable"),
        page=filters.get("page", 1),
        size=filters.get("size", 50),
        term=filters.get("term")
    )
    
    # Fetch timesheets - with pagination if needed
    timesheets, fetched_all, last_page = await client.get_timesheets(timesheet_filter)
    
    # Auto-fetch all pages if calculate_stats is enabled
    if filters.get("calculate_stats") and len(timesheets) == timesheet_filter.size:
        # Might have more pages, fetch all
        all_timesheets = list(timesheets)
        page = 2
        while True:
            timesheet_filter.page = page
            batch, fetched_all, last_page = await client.get_timesheets(timesheet_filter)
            if not batch:
                break
            all_timesheets.extend(batch)
            if len(batch) < timesheet_filter.size:
                break
            page += 1
        timesheets = all_timesheets
    
    # Build response
    if user_scope == "all":
        result = f"Found {len(timesheets)} timesheets for all users\\n\\n"
    elif user_scope == "specific":
        result = f"Found {len(timesheets)} timesheets for user {user_filter}\\n\\n"
    else:
        result = f"Found {len(timesheets)} timesheets for current user\\n\\n"

    if not fetched_all:
        result += f"Not all records were returned obtained records up to page f{last_page}\\n\\n"
    
    # Include user list if requested
    if filters.get("include_user_list"):
        try:
            # Try to get users from teams first (works for team leads and admins)
            users = []
            try:
                teams = await client.get_teams()
                user_dict = {}
                for team in teams:
                    try:
                        team_detail = await client.get_team(team.id)
                        if team_detail.members:
                            for member in team_detail.members:
                                user_dict[member.user.id] = member.user
                    except Exception:
                        continue
                users = list(user_dict.values())
            except Exception:
                pass

            # Fallback to get_users if no team members found
            if not users:
                users = await client.get_users()

            result += "Available users:\\n"
            for user in users[:10]:  # Limit to 10 users
                result += f"  - ID: {user.id}, Username: {user.username}, Name: {getattr(user, 'alias', None) or 'N/A'}\\n"
            if len(users) > 10:
                result += f"  ... and {len(users) - 10} more users\\n"
            result += "\\n"
        except Exception as e:
            error_msg = str(e).lower()
            if "forbidden" in error_msg or "403" in error_msg:
                result += "Note: Unable to list users (insufficient permissions). Use user_scope='self' or specify a user ID.\\n\\n"
            else:
                result += f"Note: Unable to list users: {str(e)}\\n\\n"
    
    # Calculate statistics if requested
    if filters.get("calculate_stats"):
        # Auto-enable year breakdown if time span > 1 year
        breakdown_by_year = filters.get("breakdown_by_year", False)
        if not breakdown_by_year and filters.get("begin") and filters.get("end"):
            try:
                from datetime import datetime
                begin_date = datetime.fromisoformat(filters["begin"].replace('Z', '+00:00'))
                end_date = datetime.fromisoformat(filters["end"].replace('Z', '+00:00'))
                time_span = end_date - begin_date
                if time_span.days > 365:  # More than 1 year
                    breakdown_by_year = True
            except Exception:
                pass
        
        stats = TimesheetAnalytics.calculate_statistics(
            timesheets, 
            breakdown_by_year=breakdown_by_year
        )
        
        # Load project names for better display
        try:
            projects = await client.get_projects()
            project_map = {p.id: p.name for p in projects}
            stats["project_names"] = project_map
        except Exception:
            project_map = {}
        
        if filters.get("stats_format") == "json":
            result += "\\n## Statistics (JSON):\\n"
            result += json.dumps(stats, indent=2)
            result += "\\n\\n"
        else:
            result += "\\n" + TimesheetAnalytics.format_statistics_report(stats, project_map)
            result += "\\n\\n"
        
        # If only stats requested, return early
        if filters.get("stats_format") == "summary":
            return [TextContent(type="text", text=result)]
    
    # List timesheets
    for ts in timesheets:
        duration = (ts.end - ts.begin).total_seconds() / 3600 if ts.end else "Running"
        status = "Running" if not ts.end else "Stopped"
        
        result += f"ID: {ts.id} - Project ID: {ts.project} / Activity ID: {ts.activity}\\n"
        result += f"  User ID: {ts.user if ts.user else 'Unknown'}\\n"
        result += f"  Duration: {duration:.2f} hours\\n" if isinstance(duration, float) else f"  Status: {status}\\n"
        result += f"  Begin: {ts.begin.strftime('%Y-%m-%d %H:%M')}\\n"
        if ts.end:
            result += f"  End: {ts.end.strftime('%Y-%m-%d %H:%M')}\\n"
        
        if ts.description:
            result += f"  Description: {ts.description}\\n"
        if ts.tags:
            result += f"  Tags: {', '.join(ts.tags)}\\n"
        result += "\\n"
    
    return [TextContent(type="text", text=result)]


async def _handle_timesheet_get(client: KimaiClient, id: Optional[int]) -> List[TextContent]:
    """Handle timesheet get action."""
    if not id:
        return [TextContent(type="text", text="Error: 'id' parameter is required for get action")]
    
    ts = await client.get_timesheet(id)
    
    duration = (ts.end - ts.begin).total_seconds() / 3600 if ts.end else "Running"
    status = "Running" if not ts.end else "Stopped"
    
    result = f"Timesheet ID: {ts.id}\\n"
    result += f"Project ID: {ts.project}\\n"
    result += f"Activity ID: {ts.activity}\\n"
    result += f"User ID: {ts.user if ts.user else 'Unknown'}\\n"
    result += f"Status: {status}\\n"
    
    result += f"Begin: {ts.begin.strftime('%Y-%m-%d %H:%M:%S')}\\n"
    if ts.end:
        result += f"End: {ts.end.strftime('%Y-%m-%d %H:%M:%S')}\\n"
        result += f"Duration: {duration:.2f} hours\\n"
    
    result += f"Billable: {'Yes' if ts.billable else 'No'}\\n"
    result += f"Exported: {'Yes' if ts.exported else 'No'}\\n"
    
    if ts.description:
        result += f"Description: {ts.description}\\n"
    if ts.tags:
        result += f"Tags: {', '.join(ts.tags)}\\n"
    if ts.rate:
        result += f"Rate: {ts.rate}\\n"
    if ts.fixed_rate:
        result += f"Fixed Rate: {ts.fixed_rate}\\n"
    if ts.hourly_rate:
        result += f"Hourly Rate: {ts.hourly_rate}\\n"
    if ts.break_duration:
        result += f"Break: {ts.break_duration // 60} minutes\\n"

    return [TextContent(type="text", text=result)]


async def _handle_timesheet_create(client: KimaiClient, data: Dict) -> List[TextContent]:
    """Handle timesheet create action."""
    from datetime import datetime

    if not data.get("project") or not data.get("activity"):
        return [TextContent(type="text", text="Error: 'project' and 'activity' are required for create action")]
    
    # Keep tags as string - model expects comma-separated string
    tags_str = data.get("tags", "")

    if "begin" in data:
        try:
            begin_datetime = datetime.fromisoformat(data["begin"])
        except ValueError:
            return [TextContent(type="text",
                                text=f"Error: Invalid date format for field begin '{data['begin']}'. Use ISO format (YYYY-MM-DDTHH:MM:SS)")]
    else:
        begin_datetime = datetime.now(timezone.utc).replace(microsecond=0)

    end_datetime = None
    if "end" in data:
        try:
            end_datetime = datetime.fromisoformat(data["end"])
        except ValueError:
            return [TextContent(type="text",
                                text=f"Error: Invalid date format for field end '{data['end']}'. Use ISO format (YYYY-MM-DDTHH:MM:SS)")]
    
    form = TimesheetEditForm(
        project=data["project"],
        activity=data["activity"],
        begin=begin_datetime,
        end=end_datetime,
        description=data.get("description"),
        tags=tags_str,
        user=data.get("user"),
        billable=data.get("billable", True),
        fixedRate=data.get("fixedRate"),
        hourlyRate=data.get("hourlyRate"),
        break_duration=data.get("break")
    )

    ts = await client.create_timesheet(form)
    
    status = "Started (running)" if not ts.end else "Created"
    return [TextContent(
        type="text",
        text=f"{status} timesheet ID {ts.id} for project {ts.project} / activity {ts.activity}"
    )]


async def _handle_timesheet_update(client: KimaiClient, id: Optional[int], data: Dict) -> List[TextContent]:
    """Handle timesheet update action."""
    if not id:
        return [TextContent(type="text", text="Error: 'id' parameter is required for update action")]
    if not data:
        return [TextContent(type="text", text="Error: 'data' parameter is required for update action")]
    
    # Parse tags if provided
    if "tags" in data:
        # Keep tags as string for model compatibility
        # data["tags"] is already a string from input
        pass
    
    form = TimesheetEditForm(**data)
    ts = await client.update_timesheet(id, form)
    
    return [TextContent(
        type="text",
        text=f"Updated timesheet ID {ts.id}"
    )]


async def _handle_timesheet_delete(client: KimaiClient, id: Optional[int]) -> List[TextContent]:
    """Handle timesheet delete action."""
    if not id:
        return [TextContent(type="text", text="Error: 'id' parameter is required for delete action")]
    
    await client.delete_timesheet(id)
    return [TextContent(type="text", text=f"Deleted timesheet ID {id}")]


async def _handle_timesheet_duplicate(client: KimaiClient, id: Optional[int]) -> List[TextContent]:
    """Handle timesheet duplicate action."""
    if not id:
        return [TextContent(type="text", text="Error: 'id' parameter is required for duplicate action")]
    
    ts = await client.duplicate_timesheet(id)
    return [TextContent(
        type="text",
        text=f"Duplicated timesheet ID {id} -> New timesheet ID {ts.id}"
    )]


async def _handle_timesheet_export_toggle(client: KimaiClient, id: Optional[int]) -> List[TextContent]:
    """Handle timesheet export toggle action."""
    if not id:
        return [TextContent(type="text", text="Error: 'id' parameter is required for export_toggle action")]
    
    ts = await client.mark_timesheet_exported(id)
    status = "exported" if ts.exported else "not exported"
    return [TextContent(
        type="text",
        text=f"Timesheet ID {id} marked as {status}"
    )]


async def _handle_timesheet_meta_update(client: KimaiClient, id: Optional[int], meta: List[Dict]) -> List[TextContent]:
    """Handle timesheet meta update action."""
    if not id:
        return [TextContent(type="text", text="Error: 'id' parameter is required for meta_update action")]
    if not meta:
        return [TextContent(type="text", text="Error: 'meta' parameter is required for meta_update action")]
    
    # API accepts one meta field per request - iterate through each field
    updated_count = 0
    for field_data in meta:
        meta_field = MetaFieldForm(**field_data)
        await client.update_timesheet_meta(id, meta_field)
        updated_count += 1
    
    return [TextContent(
        type="text",
        text=f"Updated {updated_count} meta field(s) for timesheet ID {id}"
    )]


async def _handle_timesheet_user_guide(client: KimaiClient, show_users: bool) -> List[TextContent]:
    """Handle timesheet user guide action."""
    guide = """# Timesheet User Selection Guide

When using the timesheet tool with action='list', you can control which users' timesheets are shown:

## User Scope Options:

1. **'self'** (default) - Show only your own timesheets
   - No additional parameters needed
   - Uses the current authenticated user

2. **'all'** - Show timesheets from all users
   - Requires appropriate permissions
   - Useful for managers and administrators

3. **'specific'** - Show timesheets for a specific user
   - Requires the 'user' parameter with a user ID
   - Example: user_scope='specific', user='5'

## Examples:

1. Your own timesheets for a project:
   ```json
   {
     "action": "list",
     "filters": {
       "user_scope": "self",
       "project": 17
     }
   }
   ```

2. All users' timesheets for today:
   ```json
   {
     "action": "list",
     "filters": {
       "user_scope": "all",
       "begin": "2024-01-15T00:00:00",
       "end": "2024-01-15T23:59:59"
     }
   }
   ```

3. Specific user's timesheets:
   ```json
   {
     "action": "list",
     "filters": {
       "user_scope": "specific",
       "user": "5"
     }
   }
   ```
"""
    
    if show_users:
        guide += "\\n## Available Users:\\n\\n"
        try:
            # Try to get users from teams first (works for team leads and admins)
            users = []
            try:
                teams = await client.get_teams()
                user_dict = {}
                for team in teams:
                    try:
                        team_detail = await client.get_team(team.id)
                        if team_detail.members:
                            for member in team_detail.members:
                                user_dict[member.user.id] = member.user
                    except Exception:
                        continue
                users = list(user_dict.values())
            except Exception:
                pass

            # Fallback to get_users if no team members found
            if not users:
                users = await client.get_users()

            for user in users[:20]:  # Limit to 20 users
                status = "Active" if getattr(user, 'enabled', True) else "Inactive"
                guide += f"- ID: {user.id} | Username: {user.username} | "
                guide += f"Name: {getattr(user, 'alias', None) or 'N/A'} | Status: {status}\\n"

            if len(users) > 20:
                guide += f"\\n... and {len(users) - 20} more users\\n"
        except Exception as e:
            error_msg = str(e).lower()
            if "forbidden" in error_msg or "403" in error_msg:
                guide += "Unable to list users (insufficient permissions).\\n"
                guide += "You may still use user_scope='specific' with a user ID if you have permission.\\n"
            else:
                guide += f"Error fetching users: {str(e)}\\n"

    return [TextContent(type="text", text=guide)]


# Timer action handlers
async def _handle_timer_start(client: KimaiClient, data: Dict) -> List[TextContent]:
    """Handle timer start action."""
    if not data.get("project") or not data.get("activity"):
        return [TextContent(type="text", text="Error: 'project' and 'activity' are required in data for start action")]
    
    # Keep tags as string - model expects comma-separated string
    tags_str = data.get("tags", "")
    
    form = TimesheetEditForm(
        project=data["project"],
        activity=data["activity"],
        begin=datetime.now(timezone.utc).isoformat(),
        description=data.get("description"),
        tags=tags_str
    )
    
    ts = await client.create_timesheet(form)
    
    return [TextContent(
        type="text",
        text=f"Started timer ID {ts.id} for project {ts.project} / activity {ts.activity}"
    )]


async def _handle_timer_stop(client: KimaiClient, id: Optional[int]) -> List[TextContent]:
    """Handle timer stop action."""
    if not id:
        return [TextContent(type="text", text="Error: 'id' parameter is required for stop action")]
    
    ts = await client.stop_timesheet(id)
    
    duration = (ts.end - ts.begin).total_seconds() / 3600
    return [TextContent(
        type="text",
        text=f"Stopped timer ID {ts.id}. Duration: {duration:.2f} hours"
    )]


async def _handle_timer_restart(client: KimaiClient, id: Optional[int]) -> List[TextContent]:
    """Handle timer restart action."""
    if not id:
        return [TextContent(type="text", text="Error: 'id' parameter is required for restart action")]
    
    ts = await client.restart_timesheet(id)
    
    return [TextContent(
        type="text",
        text=f"Restarted timer ID {ts.id} for project {ts.project} / activity {ts.activity}"
    )]


async def _handle_timer_active(client: KimaiClient) -> List[TextContent]:
    """Handle timer active action."""
    timesheets = await client.get_active_timesheets()
    
    if not timesheets:
        return [TextContent(type="text", text="No active timers running")]
    
    result = f"Found {len(timesheets)} active timer(s):\\n\\n"
    
    for ts in timesheets:
        elapsed = (datetime.now() - ts.begin).total_seconds() / 3600
        
        result += f"ID: {ts.id} - Project: {ts.project} / Activity: {ts.activity}\\n"
        result += f"  Started: {ts.begin.strftime('%Y-%m-%d %H:%M')}\\n"
        result += f"  Elapsed: {elapsed:.2f} hours\\n"
        
        if ts.description:
            result += f"  Description: {ts.description}\\n"
        if ts.tags:
            result += f"  Tags: {', '.join(ts.tags)}\\n"
        result += "\\n"
    
    return [TextContent(type="text", text=result)]


async def _handle_timer_recent(client: KimaiClient, size: int, begin: Optional[str]) -> List[TextContent]:
    """Handle timer recent action."""
    from datetime import datetime
    
    begin_datetime = None
    if begin:
        try:
            begin_datetime = datetime.fromisoformat(begin)
        except ValueError:
            return [TextContent(type="text", text=f"Error: Invalid date format '{begin}'. Use ISO format (YYYY-MM-DDTHH:MM:SS)")]
    
    # Use regular timesheet list with recent parameters
    filter_params = TimesheetFilter(
        size=size,
        begin=begin_datetime,
        page=1
    )
    timesheets, fetched_all, last_page = await client.get_timesheets(filter_params)
    
    result = f"Recent {len(timesheets)} timesheet(s):\\n\\n"
    
    for ts in timesheets:
        duration = (ts.end - ts.begin).total_seconds() / 3600 if ts.end else "Running"
        
        result += f"ID: {ts.id} - Project: {ts.project} / Activity: {ts.activity}\\n"
        result += f"  Date: {ts.begin.strftime('%Y-%m-%d')}\\n"
        
        if isinstance(duration, float):
            result += f"  Duration: {duration:.2f} hours\\n"
        else:
            result += f"  Status: {duration}\\n"
        
        if ts.description:
            result += f"  Description: {ts.description}\\n"
        result += "\\n"

    return [TextContent(type="text", text=result)]


# Batch operations

async def _handle_batch_delete(client: KimaiClient, ids: List[int]) -> List[TextContent]:
    """Batch delete multiple timesheets."""
    if not ids:
        return [TextContent(type="text", text="Error: 'ids' parameter is required for batch_delete action")]

    async def delete_one(id: int) -> int:
        await client.delete_timesheet(id)
        return id

    success, failed = await execute_batch(ids, delete_one)
    result = format_batch_result("Delete", success, failed, "timesheets")
    return [TextContent(type="text", text=result)]


async def _handle_batch_export(client: KimaiClient, ids: List[int]) -> List[TextContent]:
    """Batch mark multiple timesheets as exported."""
    if not ids:
        return [TextContent(type="text", text="Error: 'ids' parameter is required for batch_export action")]

    async def export_one(id: int) -> int:
        await client.mark_timesheet_exported(id)
        return id

    success, failed = await execute_batch(ids, export_one)
    result = format_batch_result("Export", success, failed, "timesheets")
    return [TextContent(type="text", text=result)]