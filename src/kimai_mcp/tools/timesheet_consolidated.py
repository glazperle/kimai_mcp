"""Consolidated Timesheet tools for all timesheet operations."""

import json
from datetime import datetime, timedelta
from typing import get_args

# Bounds the extra fetching for statistics so a huge date range cannot pull an
# unbounded number of pages into a single response.
MAX_STATS_RESULTS = 10000

from mcp.types import TextContent, Tool

from ..client import MAX_PAGE_SIZE, KimaiAPIError, KimaiClient
from ..models import MetaFieldForm, SortOrder, TimesheetEditForm, TimesheetFilter, TimesheetOrderBy
from .batch_utils import execute_batch, format_batch_result
from .dates import parse_local_datetime, parse_utc_datetime
from .errors import ToolError
from .timesheet_analytics import TimesheetAnalytics, worked_hours
from .user_discovery import resolve_accessible_users


def timesheet_tool() -> Tool:
    """Define the consolidated timesheet management tool."""
    return Tool(
        name="timesheet",
        description="""Timesheet management for time entries.

COMMON TASKS:
- List my timesheets: action=list, filters={user_scope:"self"}
- List all timesheets: action=list, filters={user_scope:"all"}
- Create entry: action=create, data={project:ID, activity:ID, begin:"...", end:"..."}
- Export entries: action=batch_export, ids=[...]

NOTE: For running timers (no end time), use the 'timer' tool instead.""",
        input_schema={
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
                            "description": "Start date and time filter in the user's local time, no offset or 'Z' (format: YYYY-MM-DDThh:mm:ss, e.g., 2023-10-27T09:30:00)."
                        },
                        "end": {
                            "type": "string",
                            "description": "End date and time filter in the user's local time, no offset or 'Z' (format: YYYY-MM-DDThh:mm:ss, e.g., 2023-10-27T17:00:00)."
                        },
                        "exported": {"type": "integer", "enum": [0, 1]},
                        "active": {"type": "integer", "enum": [0, 1]},
                        "billable": {"type": "integer", "enum": [0, 1]},
                        "users": {
                            "type": "array", "items": {"type": "integer"},
                            "description": "Several user IDs at once; replaces user_scope/user."
                        },
                        "customers": {"type": "array", "items": {"type": "integer"}, "description": "Several customer IDs (added to 'customer')."},
                        "projects": {"type": "array", "items": {"type": "integer"}, "description": "Several project IDs (added to 'project')."},
                        "activities": {"type": "array", "items": {"type": "integer"}, "description": "Several activity IDs (added to 'activity')."},
                        "tags": {"type": "array", "items": {"type": "string"}, "description": "Tag names; entries carrying any of them."},
                        "order_by": {"type": "string", "enum": list(get_args(TimesheetOrderBy)), "description": "Sort field. Kimai's default: begin."},
                        "order": {"type": "string", "enum": list(get_args(SortOrder)), "description": "Kimai's default: DESC."},
                        "modified_after": {
                            "type": "string",
                            "description": "Only entries changed after this date-time, in UTC (Kimai stores it in UTC), format YYYY-MM-DDThh:mm:ss."
                        },
                        "page": {"type": "integer", "default": 1, "description": "Page number for pagination. Default is 1."},
                        "size": {"type": "integer", "default": 50, "description": "Number of records per page. Default is 50."},
                        "term": {"type": "string"},
                        "meta": {
                            "type": "object",
                            "description": (
                                "Only return entries whose timesheet meta field 'name' equals 'value' "
                                "(exact match, case-insensitive), e.g. {name: 'issue_tracker_id', value: 'CA-376'}. "
                                "Omit 'value' to match any non-empty value; value '' matches entries without one."
                            ),
                            "required": ["name"],
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": "string"}
                            }
                        },
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
                        "begin": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Omit to start at the current server time."
                        },
                        "end": {"type": "string", "format": "date-time"},
                        "description": {"type": "string"},
                        "tags": {"type": "string"},
                        "user": {"type": "integer"},
                        "billable": {
                            "type": "boolean",
                            "description": (
                                "Whether the entry is billable. Only send this when the token has "
                                "edit_billable_own_timesheet (or edit_billable_other_timesheet for another "
                                "user); otherwise leave it omitted so Kimai applies its automatic default."
                            )
                        },
                        "fixedRate": {"type": "number"},
                        "hourlyRate": {"type": "number"},
                        "break": {
                            "type": ["integer", "string"],
                            "description": (
                                "Break duration. An integer is SECONDS, the same unit a "
                                "read returns (900 = 15 minutes). A string is a Kimai "
                                'duration with a unit ("15m", "0:15"); a bare number in a '
                                "string would be read as HOURS and is rejected. Only send "
                                "this when the Kimai instance has 'Break time' enabled "
                                "(Settings > Timesheet); otherwise the API rejects the whole "
                                "request with 'This form should not contain extra fields.'"
                            )
                        }
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
        description="""Timer management for running time tracking.

- Start timer: action=start, data={project:ID, activity:ID}
- Stop timer: action=stop, id=TIMESHEET_ID
- Show active: action=active
- Favorites (Kimai 2.66+): action=favorites lists the user's favorite timesheets (templates to restart);
  action=favorite / action=unfavorite, id=TIMESHEET_ID toggles one. Needs start_own_timesheet; own records only.

NOTE: Creates timesheet entries without end time. Use 'timesheet' tool for completed entries.""",
        input_schema={
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "restart", "active", "recent", "favorites", "favorite", "unfavorite"],
                    "description": "The timer action to perform"
                },
                "id": {
                    "type": "integer",
                    "description": "Timesheet ID (required for stop, restart, favorite and unfavorite actions)"
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
                    "description": "Only entries after this local date/time, no offset or 'Z' (YYYY-MM-DDTHH:MM:SS, for recent action)"
                }
            }
        }
    )


async def handle_timesheet(client: KimaiClient, **params) -> list[TextContent]:
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
        raise ToolError(
            f"Error: Unknown action '{action}'. Valid actions: list, get, create, update, delete, duplicate, export_toggle, meta_update, user_guide, batch_delete, batch_export"
        )


async def handle_timer(client: KimaiClient, **params) -> list[TextContent]:
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
    elif action == "favorites":
        return await _handle_timer_favorites(client)
    elif action == "favorite":
        return await _handle_timer_favorite(client, params.get("id"), add=True)
    elif action == "unfavorite":
        return await _handle_timer_favorite(client, params.get("id"), add=False)
    else:
        raise ToolError(
            f"Error: Unknown action '{action}'. Valid actions: start, stop, restart, active, recent, favorites, favorite, unfavorite"
        )


def _format_meta_fields(meta_fields: list[dict] | None) -> str | None:
    """Render the non-empty meta fields as ``name=value, ...`` (None if there are none).

    Kimai serializes every *visible* meta field definition, so an entry without a
    value still carries ``{"name": ..., "value": null}``; those are skipped.
    """
    parts = [
        f"{field.get('name')}={field.get('value')}"
        for field in meta_fields or []
        if field.get("value") not in (None, "")
    ]
    return ", ".join(parts) if parts else None


def _meta_value(meta_fields: list[dict] | None, name: str) -> str:
    """Value of the meta field ``name`` as a string, '' when missing or empty."""
    for field in meta_fields or []:
        if field.get("name") == name and field.get("value") is not None:
            return str(field["value"])
    return ""


def _matches_meta(meta_fields: list[dict] | None, name: str, wanted: str | None) -> bool:
    """Exact, case-insensitive meta match; ``wanted=None`` means "has any value"."""
    actual = _meta_value(meta_fields, name)
    if wanted is None:
        return actual != ""
    return actual.casefold() == str(wanted).casefold()


def _meta_search_term(name: str, value: str | None) -> str | None:
    """Translate a meta filter into Kimai's ``name:value`` search term syntax.

    Kimai matches ``name:value`` with ``LIKE '%value%'`` (so ``CA-376`` also
    returns ``CA-3760``), which makes the server-side term a pre-filter only;
    the exact comparison happens afterwards in ``_handle_timesheet_list``.
    The term is split on spaces and ``!``, ``*``, ``~`` and ``""`` are operators,
    so a value that cannot be expressed falls back to ``name:*`` (any value).
    Returns None when even the name cannot be expressed.
    """
    if not name or any(c.isspace() for c in name) or ":" in name:
        return None
    if value is None:
        return f"{name}:*"
    if value == "":
        return f'{name}:""'
    if any(c.isspace() for c in value) or value.startswith("!") or value in ("*", "~", '""'):
        return f"{name}:*"
    return f"{name}:{value}"


# Timesheet action handlers
async def _handle_timesheet_list(client: KimaiClient, filters: dict) -> list[TextContent]:
    """Handle timesheet list action."""
    from datetime import datetime

    # Handle user scope
    user_scope = filters.get("user_scope", "self")
    user_filter = None

    if filters.get("users"):
        # Several users replace the scope: Kimai adds `user` to `users`, so
        # sending the current user as well would mix their records in.
        user_scope = "users"
    elif user_scope == "self":
        current_user = await client.get_current_user()
        user_filter = str(current_user.id)
    elif user_scope == "specific":
        user_filter = filters.get("user")
        if not user_filter:
            raise ToolError("Error: 'user' parameter required when user_scope is 'specific'")
    elif user_scope == "all":
        user_filter = "all"  # API requires explicit "all" to return all users' timesheets

    begin_datetime = parse_local_datetime(filters["begin"], "begin") if filters.get("begin") else None
    end_datetime = parse_local_datetime(filters["end"], "end") if filters.get("end") else None


    if (
        begin_datetime is not None
        and end_datetime is not None
        and begin_datetime == end_datetime
        and begin_datetime.time() == datetime.min.time()
    ):
        end_datetime = begin_datetime + timedelta(days=1)

    meta_filter = filters.get("meta")
    term = filters.get("term")
    if meta_filter is not None:
        if not isinstance(meta_filter, dict) or not meta_filter.get("name"):
            raise ToolError("Error: 'meta' filter requires a 'name', e.g. {name: 'issue_tracker_id', value: 'CA-376'}")
        meta_term = _meta_search_term(meta_filter["name"], meta_filter.get("value"))
        if meta_term:
            # Kimai ANDs the space-separated parts of a search term.
            term = f"{term} {meta_term}" if term else meta_term

    # Build filter
    timesheet_filter = TimesheetFilter(
        user=user_filter,
        users=filters.get("users"),
        project=filters.get("project"),
        projects=filters.get("projects"),
        activity=filters.get("activity"),
        activities=filters.get("activities"),
        customer=filters.get("customer"),
        customers=filters.get("customers"),
        tags=filters.get("tags"),
        begin=begin_datetime,
        end=end_datetime,
        modified_after=(
            parse_utc_datetime(filters["modified_after"], "modified_after")
            if filters.get("modified_after") else None
        ),
        exported=filters.get("exported"),
        active=filters.get("active"),
        billable=filters.get("billable"),
        order_by=filters.get("order_by"),
        order=filters.get("order"),
        # Only pass 'page' when explicitly requested by the user,
        # otherwise the client's auto-pagination is disabled.
        page=filters.get("page"),
        size=filters.get("size", 50),
        term=term
    )

    requested_page = filters.get("page") or 1
    page_size = min(timesheet_filter.size or 50, MAX_PAGE_SIZE)
    stats_input = None

    if filters.get("calculate_stats") and requested_page > 1:
        # Statistics cover the whole filter: start at page 1 rather than
        # fetching the requested page first and throwing it away.
        timesheet_filter.page = 1
        timesheets, fetched_all, last_page = await client.get_timesheets(timesheet_filter)
    else:
        timesheets, fetched_all, last_page = await client.get_timesheets(timesheet_filter)

    # Auto-fetch remaining pages if calculate_stats is enabled and the client
    # did not already fetch everything (e.g. manual pagination was used).
    if filters.get("calculate_stats") and not fetched_all:
        all_timesheets = list(timesheets)
        page = (last_page or 1) + 1
        while len(all_timesheets) < MAX_STATS_RESULTS:
            timesheet_filter.page = page
            try:
                batch, _fetched, last_page = await client.get_timesheets(timesheet_filter)
            except KimaiAPIError as e:
                # Kimai answers the page after a full last page with 404.
                if e.status_code != 404:
                    raise
                batch = []
            if not batch:
                fetched_all = True
                break
            all_timesheets.extend(batch)
            if len(batch) < page_size:
                fetched_all = True
                break
            page += 1
        timesheets = all_timesheets

    # The server-side term is a substring pre-filter (see _meta_search_term);
    # narrow it down to exact matches here, after pagination and before the
    # statistics see the records.
    if meta_filter is not None:
        timesheets = [
            ts for ts in timesheets
            if _matches_meta(ts.meta_fields, meta_filter["name"], meta_filter.get("value"))
        ]

    if filters.get("calculate_stats"):
        stats_input = timesheets
        if requested_page > 1:
            # The listing after the report still shows only the requested page.
            start = (requested_page - 1) * page_size
            timesheets = timesheets[start:start + page_size]

    # Build response
    found = len(stats_input) if stats_input is not None else len(timesheets)
    if user_scope == "all":
        result = f"Found {found} timesheets for all users\n\n"
    elif user_scope == "specific":
        result = f"Found {found} timesheets for user {user_filter}\n\n"
    elif user_scope == "users":
        result = f"Found {found} timesheets for users {', '.join(map(str, filters['users']))}\n\n"
    else:
        result = f"Found {found} timesheets for current user\n\n"

    if meta_filter is not None:
        wanted = meta_filter.get("value")
        result += f"Meta filter: {meta_filter['name']}={'<any>' if wanted is None else wanted}\n\n"

    if not fetched_all:
        result += f"Not all records were returned; fetched records up to page {last_page}\n\n"
    
    # Include user list if requested
    if filters.get("include_user_list"):
        try:
            # Teams-first discovery with get_users fallback
            users = await resolve_accessible_users(client)

            result += "Available users:\n"
            for user in users[:10]:  # Limit to 10 users
                result += f"  - ID: {user.id}, Username: {user.username}, Name: {getattr(user, 'alias', None) or 'N/A'}\n"
            if len(users) > 10:
                result += f"  ... and {len(users) - 10} more users\n"
            result += "\n"
        # Listing users is supplementary context; any failure is reported inline
        # instead of failing the timesheet listing itself.
        except Exception as e:  # noqa: BLE001
            if isinstance(e, KimaiAPIError) and e.status_code == 403:
                result += "Note: Unable to list users (insufficient permissions). Use user_scope='self' or specify a user ID.\n\n"
            else:
                result += f"Note: Unable to list users: {e!s}\n\n"
    
    # Calculate statistics if requested
    if filters.get("calculate_stats"):
        # Auto-enable year breakdown if time span > 1 year
        breakdown_by_year = filters.get("breakdown_by_year", False)
        if (
            not breakdown_by_year
            and begin_datetime is not None
            and end_datetime is not None
            and (end_datetime - begin_datetime).days > 365
        ):
            breakdown_by_year = True

        stats = TimesheetAnalytics.calculate_statistics(
            stats_input,
            breakdown_by_year=breakdown_by_year,
            period=(begin_datetime, end_datetime),
        )
        
        # Load project names for better display
        try:
            projects = await client.get_projects()
            project_map = {p.id: p.name for p in projects}
            stats["project_names"] = project_map
        # Project names are cosmetic; without them the report shows IDs.
        except Exception:  # noqa: BLE001
            project_map = {}
        
        # The schema default is not applied server-side, so default here.
        stats_format = filters.get("stats_format", "summary")
        if stats_format == "json":
            result += "\n## Statistics (JSON):\n"
            result += json.dumps(stats, indent=2)
            result += "\n\n"
        else:
            result += "\n" + TimesheetAnalytics.format_statistics_report(stats, project_map)
            result += "\n\n"
        
        # If only stats requested, return early
        if stats_format == "summary":
            return [TextContent(type="text", text=result)]
    
    # List timesheets
    for ts in timesheets:
        result += _describe_timesheet(ts) + "\n"

    return [TextContent(type="text", text=result)]


async def _handle_timesheet_get(client: KimaiClient, id: int | None) -> list[TextContent]:
    """Handle timesheet get action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for get action")
    
    ts = await client.get_timesheet(id)
    
    duration = worked_hours(ts) if ts.end else "Running"
    status = "Running" if not ts.end else "Stopped"
    
    result = f"Timesheet ID: {ts.id}\n"
    result += f"Project ID: {ts.project}\n"
    result += f"Activity ID: {ts.activity}\n"
    result += f"User ID: {ts.user if ts.user else 'Unknown'}\n"
    result += f"Status: {status}\n"
    
    result += f"Begin: {ts.begin.strftime('%Y-%m-%d %H:%M:%S')}\n"
    if ts.end:
        result += f"End: {ts.end.strftime('%Y-%m-%d %H:%M:%S')}\n"
        result += f"Duration: {duration:.2f} hours\n"
    
    result += f"Billable: {'Yes' if ts.billable else 'No'}\n"
    result += f"Exported: {'Yes' if ts.exported else 'No'}\n"
    
    if ts.description:
        result += f"Description: {ts.description}\n"
    if ts.tags:
        result += f"Tags: {', '.join(ts.tags)}\n"
    if ts.rate is None and ts.internal_rate is None and ts.fixed_rate is None and ts.hourly_rate is None:
        # Kimai 2.66+ strips all four rate fields per record when the token
        # lacks view_rate_own_timesheet / view_rate_other_timesheet.
        result += "Rates: not visible to this token (needs view_rate_own_timesheet resp. view_rate_other_timesheet; Kimai 2.66+ omits them per record)\n"
    # `is not None`, not truthiness: a visible 0.0 is a real value and must
    # stay distinguishable from a stripped field.
    if ts.rate is not None:
        result += f"Rate: {ts.rate}\n"
    if ts.internal_rate is not None:
        result += f"Internal Rate: {ts.internal_rate}\n"
    if ts.fixed_rate is not None:
        result += f"Fixed Rate: {ts.fixed_rate}\n"
    if ts.hourly_rate is not None:
        result += f"Hourly Rate: {ts.hourly_rate}\n"
    if ts.break_duration:
        result += f"Break: {ts.break_duration // 60} minutes\n"
    meta = _format_meta_fields(ts.meta_fields)
    if meta:
        result += f"Meta: {meta}\n"

    return [TextContent(type="text", text=result)]


async def _handle_timesheet_create(client: KimaiClient, data: dict) -> list[TextContent]:
    """Handle timesheet create action."""
    from datetime import datetime

    if not data.get("project") or not data.get("activity"):
        raise ToolError("Error: 'project' and 'activity' are required for create action")

    # Keep tags as string - model expects comma-separated string. Leave it
    # absent when the caller did not provide it: Kimai builds the API form from
    # the user's permissions and settings, so optional fields must not be
    # manufactured here.
    tags_str = data.get("tags")

    if "begin" in data:
        try:
            begin_datetime = datetime.fromisoformat(data["begin"])
        except ValueError:
            raise ToolError(
                f"Error: Invalid date format for field begin '{data['begin']}'. Use ISO format (YYYY-MM-DDTHH:MM:SS)")
    else:
        # Leave begin to Kimai ("the users current timestamp will be used").
        # In punch-in/out tracking mode the API form has no begin/end field
        # unless the token holds view_other_timesheet, so a manufactured
        # value fails the whole request as an extra field.
        begin_datetime = None

    end_datetime = None
    if "end" in data:
        try:
            end_datetime = datetime.fromisoformat(data["end"])
        except ValueError:
            raise ToolError(
                f"Error: Invalid date format for field end '{data['end']}'. Use ISO format (YYYY-MM-DDTHH:MM:SS)")
    
    form = TimesheetEditForm(
        project=data["project"],
        activity=data["activity"],
        begin=begin_datetime,
        end=end_datetime,
        description=data.get("description"),
        tags=tags_str,
        user=data.get("user"),
        # ``billable`` is only present in Kimai's form when the token has the
        # corresponding edit permission. Sending a default True made an
        # otherwise ordinary create fail with "extra fields" for ROLE_USER.
        billable=data.get("billable"),
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


async def _handle_timesheet_update(client: KimaiClient, id: int | None, data: dict) -> list[TextContent]:
    """Handle timesheet update action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for update action")
    if not data:
        raise ToolError("Error: 'data' parameter is required for update action")
    
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


async def _handle_timesheet_delete(client: KimaiClient, id: int | None) -> list[TextContent]:
    """Handle timesheet delete action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for delete action")
    
    await client.delete_timesheet(id)
    return [TextContent(type="text", text=f"Deleted timesheet ID {id}")]


async def _handle_timesheet_duplicate(client: KimaiClient, id: int | None) -> list[TextContent]:
    """Handle timesheet duplicate action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for duplicate action")
    
    ts = await client.duplicate_timesheet(id)
    return [TextContent(
        type="text",
        text=f"Duplicated timesheet ID {id} -> New timesheet ID {ts.id}"
    )]


async def _handle_timesheet_export_toggle(client: KimaiClient, id: int | None) -> list[TextContent]:
    """Handle timesheet export toggle action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for export_toggle action")
    
    ts = await client.toggle_timesheet_export(id)
    status = "exported" if ts.exported else "not exported"
    return [TextContent(
        type="text",
        text=f"Timesheet ID {id} marked as {status}"
    )]


async def _handle_timesheet_meta_update(client: KimaiClient, id: int | None, meta: list[dict]) -> list[TextContent]:
    """Handle timesheet meta update action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for meta_update action")
    if not meta:
        raise ToolError("Error: 'meta' parameter is required for meta_update action")
    
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


async def _handle_timesheet_user_guide(client: KimaiClient, show_users: bool) -> list[TextContent]:
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
        guide += "\n## Available Users:\n\n"
        try:
            # Teams-first discovery with get_users fallback
            users = await resolve_accessible_users(client)

            for user in users[:20]:  # Limit to 20 users
                status = "Active" if getattr(user, 'enabled', True) else "Inactive"
                guide += f"- ID: {user.id} | Username: {user.username} | "
                guide += f"Name: {getattr(user, 'alias', None) or 'N/A'} | Status: {status}\n"

            if len(users) > 20:
                guide += f"\n... and {len(users) - 20} more users\n"
        # The user guide stays useful even when user discovery fails.
        except Exception as e:  # noqa: BLE001
            if isinstance(e, KimaiAPIError) and e.status_code == 403:
                guide += "Unable to list users (insufficient permissions).\n"
                guide += "You may still use user_scope='specific' with a user ID if you have permission.\n"
            else:
                guide += f"Error fetching users: {e!s}\n"

    return [TextContent(type="text", text=guide)]


# Timer action handlers
async def _handle_timer_start(client: KimaiClient, data: dict) -> list[TextContent]:
    """Handle timer start action."""
    if not data.get("project") or not data.get("activity"):
        raise ToolError("Error: 'project' and 'activity' are required in data for start action")
    
    # Keep tags as string - model expects comma-separated string. Do not add an
    # empty tags field when the caller omitted it.
    tags_str = data.get("tags")
    
    form = TimesheetEditForm(
        project=data["project"],
        activity=data["activity"],
        # No begin: Kimai starts the record at the current timestamp itself,
        # and punch-in/out mode has no begin field for plain users.
        description=data.get("description"),
        tags=tags_str
    )
    
    ts = await client.create_timesheet(form)
    
    return [TextContent(
        type="text",
        text=f"Started timer ID {ts.id} for project {ts.project} / activity {ts.activity}"
    )]


async def _handle_timer_stop(client: KimaiClient, id: int | None) -> list[TextContent]:
    """Handle timer stop action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for stop action")
    
    ts = await client.stop_timesheet(id)
    
    duration = worked_hours(ts)
    return [TextContent(
        type="text",
        text=f"Stopped timer ID {ts.id}. Duration: {duration:.2f} hours"
    )]


async def _handle_timer_restart(client: KimaiClient, id: int | None) -> list[TextContent]:
    """Handle timer restart action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for restart action")
    
    ts = await client.restart_timesheet(id)
    
    return [TextContent(
        type="text",
        text=f"Restarted timer ID {ts.id} for project {ts.project} / activity {ts.activity}"
    )]


def _describe_timesheet(ts) -> str:
    """One record of a listing, with every field Kimai sent for it.

    ``timesheet list`` and ``timer recent`` get ``TimesheetEntity`` rows, whose
    relations are ids. ``/timesheets/active`` and ``/favorites/timesheets`` are
    Expanded schemas, so there the relations are objects and can be named
    (issue #24). Rates are printed only where Kimai sent them: since 2.66 it
    strips them per record unless the token may view rates.
    """
    if isinstance(ts.project, int):
        text = f"ID: {ts.id} - Project ID: {ts.project} / Activity ID: {ts.activity}\n"
        text += f"  User ID: {ts.user if ts.user else 'Unknown'}\n"
    else:
        project = ts.project.name
        if ts.project.customer:
            project = f"{ts.project.customer.name} / {project}"
        text = f"ID: {ts.id} - Project: {project} / Activity: {ts.activity.name}\n"
        if ts.user:
            text += f"  User: {ts.user.alias or ts.user.username} (ID: {ts.user.id})\n"

    if ts.end:
        text += f"  Duration: {worked_hours(ts):.2f} hours\n"
    else:
        text += "  Status: Running\n"
    text += f"  Begin: {ts.begin.strftime('%Y-%m-%d %H:%M')}\n"
    if ts.end:
        text += f"  End: {ts.end.strftime('%Y-%m-%d %H:%M')}\n"
    if ts.break_duration:
        text += f"  Break: {ts.break_duration // 60} minutes\n"
    text += f"  Billable: {'Yes' if ts.billable else 'No'} | Exported: {'Yes' if ts.exported else 'No'}\n"

    rates = [
        f"{label}: {value}"
        for label, value in (
            ("Rate", ts.rate),
            ("Internal Rate", ts.internal_rate),
            ("Fixed Rate", ts.fixed_rate),
            ("Hourly Rate", ts.hourly_rate),
        )
        if value is not None
    ]
    if rates:
        text += f"  {' | '.join(rates)}\n"

    if ts.description:
        text += f"  Description: {ts.description}\n"
    if ts.tags:
        text += f"  Tags: {', '.join(ts.tags)}\n"
    meta = _format_meta_fields(ts.meta_fields)
    if meta:
        text += f"  Meta: {meta}\n"
    return text


async def _handle_timer_active(client: KimaiClient) -> list[TextContent]:
    """Handle timer active action."""
    timesheets = await client.get_active_timesheets()
    
    if not timesheets:
        return [TextContent(type="text", text="No active timers running")]
    
    result = f"Found {len(timesheets)} active timer(s):\n\n"
    
    for ts in timesheets:
        # tzinfo=None mirrors ts.begin being naive, so both sides stay comparable.
        now = datetime.now(ts.begin.tzinfo)
        elapsed = (now - ts.begin).total_seconds() / 3600

        result += _describe_timesheet(ts)
        result += f"  Elapsed: {elapsed:.2f} hours\n"
        result += "\n"
    
    return [TextContent(type="text", text=result)]


async def _handle_timer_favorites(client: KimaiClient) -> list[TextContent]:
    """Handle timer favorites action (Kimai 2.66+)."""
    timesheets = await client.get_favorite_timesheets()

    if not timesheets:
        return [TextContent(
            type="text",
            text="No favorite timesheets. Mark one of your own records with timer action=favorite id=<timesheet id> (Kimai 2.66+).",
        )]

    result = f"Found {len(timesheets)} favorite timesheet(s). Start one with timer action=restart id=<ID>.\n\n"

    for ts in timesheets:
        result += _describe_timesheet(ts) + "\n"

    return [TextContent(type="text", text=result)]


async def _handle_timer_favorite(client: KimaiClient, id: int | None, add: bool) -> list[TextContent]:
    """Handle timer favorite / unfavorite actions (Kimai 2.66+)."""
    action = "favorite" if add else "unfavorite"
    if not id:
        raise ToolError(f"Error: 'id' parameter is required for {action} action")

    if add:
        await client.add_favorite_timesheet(id)
        text = f"Timesheet ID {id} added to favorites"
    else:
        await client.remove_favorite_timesheet(id)
        text = f"Timesheet ID {id} removed from favorites"

    return [TextContent(type="text", text=text)]


async def _handle_timer_recent(client: KimaiClient, size: int, begin: str | None) -> list[TextContent]:
    """Handle timer recent action."""
    
    begin_datetime = parse_local_datetime(begin, "begin") if begin else None
    
    # Use regular timesheet list with recent parameters
    filter_params = TimesheetFilter(
        size=size,
        begin=begin_datetime,
        page=1
    )
    timesheets, _fetched_all, _last_page = await client.get_timesheets(filter_params)
    
    result = f"Recent {len(timesheets)} timesheet(s):\n\n"

    for ts in timesheets:
        result += _describe_timesheet(ts) + "\n"

    return [TextContent(type="text", text=result)]


# Batch operations

async def _handle_batch_delete(client: KimaiClient, ids: list[int]) -> list[TextContent]:
    """Batch delete multiple timesheets."""
    if not ids:
        raise ToolError("Error: 'ids' parameter is required for batch_delete action")

    async def delete_one(id: int) -> int:
        await client.delete_timesheet(id)
        return id

    success, failed = await execute_batch(ids, delete_one)
    result = format_batch_result("Delete", success, failed, "timesheets")
    return [TextContent(type="text", text=result)]


async def _handle_batch_export(client: KimaiClient, ids: list[int]) -> list[TextContent]:
    """Batch mark multiple timesheets as exported."""
    if not ids:
        raise ToolError("Error: 'ids' parameter is required for batch_export action")

    async def export_one(id: int) -> int:
        await client.toggle_timesheet_export(id)
        return id

    success, failed = await execute_batch(ids, export_one)
    result = format_batch_result("Export", success, failed, "timesheets")
    return [TextContent(type="text", text=result)]
