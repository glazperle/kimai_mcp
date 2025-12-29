"""Consolidated Absence Manager tool for all absence operations."""

from typing import List, Dict, Optional, Tuple
from datetime import datetime, date, timedelta
from mcp.types import Tool, TextContent
from ..client import KimaiClient
from ..models import AbsenceForm, AbsenceFilter
from .absence_analytics import AbsenceAnalytics
from .batch_utils import execute_batch, format_batch_result


def absence_tool() -> Tool:
    """Define the consolidated absence management tool."""
    return Tool(
        name="absence",
        description="Universal absence management tool for complete absence workflow. Supports list, statistics, create, delete, approve, reject, and request approval actions.",
        inputSchema={
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "statistics", "types", "create", "delete", "approve", "reject", "request", "attendance", "batch_delete", "batch_approve", "batch_reject"],
                    "description": "The action to perform"
                },
                "ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of absence IDs for batch operations (batch_delete, batch_approve, batch_reject)"
                },
                "id": {
                    "type": "integer",
                    "description": "Absence ID (required for delete, approve, reject, request actions)"
                },
                "filters": {
                    "type": "object",
                    "description": "Filters for list action",
                    "properties": {
                        "user_scope": {
                            "type": "string",
                            "enum": ["self", "all", "specific"],
                            "description": "User scope: 'self' (current user), 'all' (all users), 'specific' (particular user)",
                            "default": "self"
                        },
                        "user": {
                            "type": "string",
                            "description": "User ID when user_scope is 'specific'"
                        },
                        "begin": {
                            "type": "string",
                            "format": "date",
                            "description": "Start date filter (YYYY-MM-DD)"
                        },
                        "end": {
                            "type": "string",
                            "format": "date",
                            "description": "End date filter (YYYY-MM-DD)"
                        },
                        "status": {
                            "type": "string",
                            "enum": ["approved", "open", "all"],
                            "description": "Status filter",
                            "default": "all"
                        }
                    }
                },
                "data": {
                    "type": "object",
                    "description": "Data for create action",
                    "properties": {
                        "comment": {
                            "type": "string",
                            "description": "Comment/reason for the absence"
                        },
                        "date": {
                            "type": "string",
                            "format": "date",
                            "description": "Start date of absence (YYYY-MM-DD)"
                        },
                        "type": {
                            "type": "string",
                            "enum": ["holiday", "time_off", "sickness", "sickness_child", "other", "parental", "unpaid_vacation"],
                            "description": "Type of absence",
                            "default": "other"
                        },
                        "user": {
                            "type": "integer",
                            "description": "User ID (requires permission, defaults to current user)"
                        },
                        "end": {
                            "type": "string",
                            "format": "date",
                            "description": "End date for multi-day absences"
                        },
                        "halfDay": {
                            "type": "boolean",
                            "description": "Whether this is a half-day absence"
                        },
                        "duration": {
                            "type": "string",
                            "description": "Duration in Kimai format"
                        }
                    }
                },
                "language": {
                    "type": "string",
                    "description": "Language code for absence types (for types action)",
                    "default": "en"
                },
                "group_by": {
                    "type": "string",
                    "enum": ["type", "user", "month"],
                    "description": "Grouping for statistics action",
                    "default": "type"
                },
                "breakdown_by_month": {
                    "type": "boolean",
                    "description": "Include monthly breakdown in statistics",
                    "default": False
                },
                "date": {
                    "type": "string",
                    "format": "date",
                    "description": "Date for attendance check (YYYY-MM-DD). Defaults to today."
                }
            }
        }
    )


async def handle_absence(client: KimaiClient, **params) -> List[TextContent]:
    """Handle consolidated absence operations."""
    action = params.get("action")
    
    try:
        if action == "list":
            return await _handle_absence_list(client, params.get("filters", {}))
        elif action == "statistics":
            return await _handle_absence_statistics(
                client,
                params.get("filters", {}),
                params.get("group_by", "type"),
                params.get("breakdown_by_month", False)
            )
        elif action == "types":
            return await _handle_absence_types(client, params.get("language", "en"))
        elif action == "create":
            return await _handle_absence_create(client, params.get("data", {}))
        elif action == "delete":
            return await _handle_absence_delete(client, params.get("id"))
        elif action == "approve":
            return await _handle_absence_approve(client, params.get("id"))
        elif action == "reject":
            return await _handle_absence_reject(client, params.get("id"))
        elif action == "request":
            return await _handle_absence_request(client, params.get("id"))
        elif action == "attendance":
            return await _handle_attendance(
                client,
                params.get("filters", {}),
                params.get("date")
            )
        elif action == "batch_delete":
            return await _handle_batch_delete(client, params.get("ids", []))
        elif action == "batch_approve":
            return await _handle_batch_approve(client, params.get("ids", []))
        elif action == "batch_reject":
            return await _handle_batch_reject(client, params.get("ids", []))
        else:
            return [TextContent(
                type="text",
                text=f"Error: Unknown action '{action}'. Valid actions: list, statistics, types, create, delete, approve, reject, request, attendance, batch_delete, batch_approve, batch_reject"
            )]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def _handle_absence_list(client: KimaiClient, filters: Dict) -> List[TextContent]:
    """Handle absence list action."""
    # Handle user scope - API only supports single user or no user filter
    user_scope = filters.get("user_scope", "self")
    
    # Process date formats - convert YYYY-MM-DD to ISO 8601 with time
    begin_date = filters.get("begin")
    end_date = filters.get("end")
    
    if begin_date:
        try:
            # Parse the date and add time component
            parsed_date = datetime.strptime(begin_date, "%Y-%m-%d")
            begin_date = parsed_date.strftime("%Y-%m-%dT00:00:00")
        except ValueError:
            return [TextContent(type="text", text=f"Error: Invalid begin date format. Expected YYYY-MM-DD, got '{begin_date}'")]
    
    if end_date:
        try:
            # Parse the date and add time component (end of day)
            parsed_date = datetime.strptime(end_date, "%Y-%m-%d")
            end_date = parsed_date.strftime("%Y-%m-%dT23:59:59")
        except ValueError:
            return [TextContent(type="text", text=f"Error: Invalid end date format. Expected YYYY-MM-DD, got '{end_date}'")]
    
    # Handle different user scopes
    absences = []
    
    if user_scope == "self":
        # Get absences for current user
        current_user = await client.get_current_user()
        absence_filter = AbsenceFilter(
            user=str(current_user.id),
            begin=begin_date,
            end=end_date,
            status=filters.get("status", "all")
        )
        absences = await client.get_absences(absence_filter)
        
    elif user_scope == "specific":
        # Get absences for specific user
        user_filter = filters.get("user")
        if not user_filter:
            return [TextContent(type="text", text="Error: 'user' parameter required when user_scope is 'specific'")]
        
        absence_filter = AbsenceFilter(
            user=user_filter,
            begin=begin_date,
            end=end_date,
            status=filters.get("status", "all")
        )
        absences = await client.get_absences(absence_filter)
        
    elif user_scope == "all":
        # Try to get absences for all users the current user has access to
        try:
            all_absences = []

            # First, try to get users from teams (works for team leads and admins)
            accessible_user_ids = set()
            try:
                teams = await client.get_teams()
                # Need to fetch each team individually to get members
                for team in teams:
                    try:
                        team_detail = await client.get_team(team.id)
                        if team_detail.members:
                            for member in team_detail.members:
                                accessible_user_ids.add(member.user.id)
                    except Exception:
                        continue
            except Exception:
                # No team access, try get_users as fallback
                pass

            # If no users from teams, try get_users (requires higher permissions)
            if not accessible_user_ids:
                try:
                    users = await client.get_users()
                    accessible_user_ids = {user.id for user in users}
                except Exception as e:
                    error_msg = str(e).lower()
                    if "forbidden" in error_msg or "403" in error_msg:
                        return [TextContent(
                            type="text",
                            text="Error: You don't have permission to view all users' absences.\n\n"
                                 "This requires either:\n"
                                 "- System Administrator role, or\n"
                                 "- Being a team lead (to see team members' absences)\n\n"
                                 "Use user_scope='self' to view your own absences, or\n"
                                 "user_scope='specific' with a user ID if you have permission for that user."
                        )]
                    raise

            # Now fetch absences for each accessible user
            for user_id in accessible_user_ids:
                try:
                    user_filter = AbsenceFilter(
                        user=str(user_id),
                        begin=begin_date,
                        end=end_date,
                        status=filters.get("status", "all")
                    )
                    user_absences = await client.get_absences(user_filter)
                    all_absences.extend(user_absences)
                except Exception:
                    # Skip users we don't have permission to view
                    continue

            absences = all_absences

        except Exception as e:
            return [TextContent(type="text", text=f"Error fetching all users' absences: {str(e)}")]
    
    # Build response
    if user_scope == "all":
        result = f"Found {len(absences)} absence(s) for all users\\n\\n"
    elif user_scope == "specific":
        user_id = filters.get("user")
        result = f"Found {len(absences)} absence(s) for user {user_id}\\n\\n"
    else:
        result = f"Found {len(absences)} absence(s) for current user\\n\\n"
    
    if not absences:
        result += "No absences found for the specified criteria."
        return [TextContent(type="text", text=result)]
    
    for absence in absences:
        result += f"ID: {absence.id} - {absence.type}\\n"
        result += f"  User: {absence.user.username if absence.user else 'Unknown'}\\n"
        result += f"  Date: {absence.date}\\n"
        
        if hasattr(absence, "endDate") and absence.endDate:
            result += f"  End Date: {absence.endDate}\\n"
        
        result += f"  Status: {getattr(absence, 'status', 'Unknown')}\\n"
        
        if hasattr(absence, "halfDay") and absence.halfDay:
            result += "  Half Day: Yes\\n"
        
        if hasattr(absence, "comment") and absence.comment:
            result += f"  Comment: {absence.comment}\\n"
        
        if hasattr(absence, "duration") and absence.duration:
            result += f"  Duration: {absence.duration}\\n"
        
        result += "\\n"
    
    return [TextContent(type="text", text=result)]


async def _handle_absence_statistics(
    client: KimaiClient,
    filters: Dict,
    group_by: str,
    breakdown_by_month: bool
) -> List[TextContent]:
    """Handle absence statistics action."""
    # First, fetch absences using the same logic as list
    user_scope = filters.get("user_scope", "all")  # Default to all for statistics

    # Process date formats
    begin_date = filters.get("begin")
    end_date = filters.get("end")

    if begin_date:
        try:
            parsed_date = datetime.strptime(begin_date, "%Y-%m-%d")
            begin_date = parsed_date.strftime("%Y-%m-%dT00:00:00")
        except ValueError:
            return [TextContent(type="text", text=f"Error: Invalid begin date format. Expected YYYY-MM-DD, got '{begin_date}'")]

    if end_date:
        try:
            parsed_date = datetime.strptime(end_date, "%Y-%m-%d")
            end_date = parsed_date.strftime("%Y-%m-%dT23:59:59")
        except ValueError:
            return [TextContent(type="text", text=f"Error: Invalid end date format. Expected YYYY-MM-DD, got '{end_date}'")]

    # Fetch absences based on user scope
    absences = []

    if user_scope == "self":
        current_user = await client.get_current_user()
        absence_filter = AbsenceFilter(
            user=str(current_user.id),
            begin=begin_date,
            end=end_date,
            status=filters.get("status", "all")
        )
        absences = await client.get_absences(absence_filter)

    elif user_scope == "specific":
        user_filter = filters.get("user")
        if not user_filter:
            return [TextContent(type="text", text="Error: 'user' parameter required when user_scope is 'specific'")]

        absence_filter = AbsenceFilter(
            user=user_filter,
            begin=begin_date,
            end=end_date,
            status=filters.get("status", "all")
        )
        absences = await client.get_absences(absence_filter)

    else:  # user_scope == "all"
        try:
            all_absences = []
            accessible_user_ids = set()

            # First, try to get users from teams
            try:
                teams = await client.get_teams()
                for team in teams:
                    try:
                        team_detail = await client.get_team(team.id)
                        if team_detail.members:
                            for member in team_detail.members:
                                accessible_user_ids.add(member.user.id)
                    except Exception:
                        continue
            except Exception:
                pass

            # Fallback to get_users
            if not accessible_user_ids:
                try:
                    users = await client.get_users()
                    accessible_user_ids = {user.id for user in users}
                except Exception as e:
                    error_msg = str(e).lower()
                    if "forbidden" in error_msg or "403" in error_msg:
                        return [TextContent(
                            type="text",
                            text="Error: You don't have permission to view all users' absences.\n\n"
                                 "This requires either:\n"
                                 "- System Administrator role, or\n"
                                 "- Being a team lead (to see team members' absences)\n\n"
                                 "Use user_scope='self' to view your own absence statistics."
                        )]
                    raise

            # Fetch absences for each accessible user
            for user_id in accessible_user_ids:
                try:
                    user_filter = AbsenceFilter(
                        user=str(user_id),
                        begin=begin_date,
                        end=end_date,
                        status=filters.get("status", "all")
                    )
                    user_absences = await client.get_absences(user_filter)
                    all_absences.extend(user_absences)
                except Exception:
                    continue

            absences = all_absences

        except Exception as e:
            return [TextContent(type="text", text=f"Error fetching absences for statistics: {str(e)}")]

    # Calculate statistics
    stats = AbsenceAnalytics.calculate_statistics(
        absences,
        group_by=group_by,
        breakdown_by_month=breakdown_by_month
    )

    # Generate report title based on filters
    title = "Absence Statistics Report"
    if begin_date and end_date:
        title += f" ({filters.get('begin')} to {filters.get('end')})"
    elif begin_date:
        title += f" (from {filters.get('begin')})"
    elif end_date:
        title += f" (until {filters.get('end')})"

    # Format and return report
    report = AbsenceAnalytics.format_statistics_report(stats, title)

    return [TextContent(type="text", text=report)]


async def _handle_absence_types(client: KimaiClient, language: str) -> List[TextContent]:
    """Handle absence types action."""
    types = await client.get_absence_types(language=language)
    
    if not types:
        result = "No absence types available"
    else:
        result = f"Available absence types ({language}):\\n\\n"
        
        for absence_type in types:
            result += f"- {absence_type}\\n"
    
    return [TextContent(type="text", text=result)]


# Kimai limits absences to max 30 days per entry
MAX_ABSENCE_DAYS = 30


def _split_date_range(start: date, end: date) -> List[Tuple[date, date]]:
    """Split a date range respecting year boundaries and 30-day limit.

    Returns list of (start, end) tuples.
    """
    chunks = []
    current_start = start

    while current_start <= end:
        # Constraint 1: Year boundary (Dec 31)
        year_end = date(current_start.year, 12, 31)

        # Constraint 2: 30-day limit
        max_end_by_days = current_start + timedelta(days=MAX_ABSENCE_DAYS - 1)

        # Take the most restrictive end date
        current_end = min(year_end, max_end_by_days, end)

        chunks.append((current_start, current_end))

        # Move to next chunk
        current_start = current_end + timedelta(days=1)

    return chunks


async def _handle_absence_create(client: KimaiClient, data: Dict) -> List[TextContent]:
    """Handle absence create action."""
    required_fields = ["comment", "date", "type"]
    missing_fields = [field for field in required_fields if not data.get(field)]

    if missing_fields:
        return [TextContent(
            type="text",
            text=f"Error: Missing required fields: {', '.join(missing_fields)}"
        )]

    # Parse dates
    start_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
    end_date = start_date
    if data.get("end"):
        end_date = datetime.strptime(data["end"], "%Y-%m-%d").date()

    # Calculate total days
    total_days = (end_date - start_date).days + 1

    # Check if splitting is needed (year boundary OR > 30 days)
    needs_split = (start_date.year != end_date.year) or (total_days > MAX_ABSENCE_DAYS)

    if needs_split:
        chunks = _split_date_range(start_date, end_date)
        created_absences = []

        for chunk_start, chunk_end in chunks:
            form = AbsenceForm(
                comment=data["comment"],
                date=chunk_start.strftime("%Y-%m-%d"),
                end=chunk_end.strftime("%Y-%m-%d") if chunk_start != chunk_end else None,
                type=data["type"],
                user=data.get("user"),
                half_day=data.get("halfDay", False),
                duration=data.get("duration")
            )

            try:
                absence_list = await client.create_absence(form)
                if isinstance(absence_list, list):
                    created_absences.extend(absence_list)
                else:
                    created_absences.append(absence_list)
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=f"Error creating absence chunk {chunk_start} - {chunk_end}: {str(e)}"
                )]

        # Success message
        ids = ", ".join(str(a.id) for a in created_absences)
        return [TextContent(
            type="text",
            text=f"Created {len(created_absences)} absence(s) for {data['type']}\n"
                 f"Period: {start_date} to {end_date} ({total_days} days)\n"
                 f"IDs: {ids}\n"
                 f"(Automatically split due to Kimai limitations)"
        )]

    # Normal case: single absence (<=30 days, same year)
    form = AbsenceForm(
        comment=data["comment"],
        date=data["date"],
        type=data["type"],
        user=data.get("user"),
        end=data.get("end"),
        half_day=data.get("halfDay", False),
        duration=data.get("duration")
    )

    absence_list = await client.create_absence(form)
    # create_absence returns a list
    absence = absence_list[0] if isinstance(absence_list, list) else absence_list

    duration_text = ""
    if hasattr(absence, "end_date") and absence.end_date:
        duration_text = f" from {absence.date} to {absence.end_date}"
    elif hasattr(absence, "half_day") and absence.half_day:
        duration_text = f" (half day) on {absence.date}"
    else:
        duration_text = f" on {absence.date}"

    return [TextContent(
        type="text",
        text=f"Created absence ID {absence.id} for {absence.type}{duration_text}"
    )]


async def _handle_absence_delete(client: KimaiClient, id: Optional[int]) -> List[TextContent]:
    """Handle absence delete action."""
    if not id:
        return [TextContent(type="text", text="Error: 'id' parameter is required for delete action")]
    
    await client.delete_absence(id)
    return [TextContent(type="text", text=f"Deleted absence ID {id}")]


async def _handle_absence_approve(client: KimaiClient, id: Optional[int]) -> List[TextContent]:
    """Handle absence approve action."""
    if not id:
        return [TextContent(type="text", text="Error: 'id' parameter is required for approve action")]
    
    await client.confirm_absence_approval(id)
    return [TextContent(type="text", text=f"Approved absence ID {id}")]


async def _handle_absence_reject(client: KimaiClient, id: Optional[int]) -> List[TextContent]:
    """Handle absence reject action."""
    if not id:
        return [TextContent(type="text", text="Error: 'id' parameter is required for reject action")]
    
    await client.reject_absence_approval(id)
    return [TextContent(type="text", text=f"Rejected absence ID {id}")]


async def _handle_absence_request(client: KimaiClient, id: Optional[int]) -> List[TextContent]:
    """Handle absence request approval action."""
    if not id:
        return [TextContent(type="text", text="Error: 'id' parameter is required for request action")]

    await client.request_absence_approval(id)
    return [TextContent(type="text", text=f"Requested approval for absence ID {id}")]


async def _get_accessible_users(client: KimaiClient, user_scope: str) -> List:
    """Get users based on scope with Teams-first approach.

    Returns list of user objects (not just IDs) for building reports.
    """
    if user_scope == "self":
        current_user = await client.get_current_user()
        return [current_user]

    # For "all" scope, try teams first then fallback to get_users
    accessible_users = []
    seen_user_ids = set()

    # Try to get users from teams (works for team leads and admins)
    try:
        teams = await client.get_teams()
        for team in teams:
            try:
                team_detail = await client.get_team(team.id)
                if team_detail.members:
                    for member in team_detail.members:
                        if member.user.id not in seen_user_ids:
                            seen_user_ids.add(member.user.id)
                            # Only include active users
                            if getattr(member.user, 'enabled', True):
                                accessible_users.append(member.user)
            except Exception:
                continue
    except Exception:
        pass

    # If no users from teams, try get_users (requires higher permissions)
    if not accessible_users:
        try:
            users = await client.get_users()
            # Only include active users
            accessible_users = [u for u in users if getattr(u, 'enabled', True)]
        except Exception:
            # If both fail, return empty list
            pass

    return accessible_users


async def _handle_attendance(
    client: KimaiClient,
    filters: Dict,
    date_str: Optional[str] = None
) -> List[TextContent]:
    """Show who is present (not absent) on a given day."""

    # Type labels for German output
    TYPE_LABELS = {
        "holiday": "Urlaub",
        "sickness": "Krankheit",
        "sickness_child": "Kind krank",
        "time_off": "Zeitausgleich",
        "parental": "Elternzeit",
        "unpaid_vacation": "Unbezahlter Urlaub",
        "other": "Sonstiges"
    }

    # 1. Determine date (Default: today)
    if date_str:
        try:
            check_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return [TextContent(
                type="text",
                text=f"Error: Invalid date format. Expected YYYY-MM-DD, got '{date_str}'"
            )]
    else:
        check_date = datetime.now().date()

    # 2. Get all accessible users
    user_scope = filters.get("user_scope", "all")
    all_users = await _get_accessible_users(client, user_scope)

    if not all_users:
        return [TextContent(
            type="text",
            text="Error: Could not retrieve any users. You may need:\n"
                 "- System Administrator role, or\n"
                 "- Being a team lead (to see team members)"
        )]

    # 3. Check absences for this day
    begin = check_date.strftime("%Y-%m-%dT00:00:00")
    end = check_date.strftime("%Y-%m-%dT23:59:59")

    absent_users_with_reason = {}  # user_id -> (user, absence_type)

    for user in all_users:
        try:
            absences = await client.get_absences(AbsenceFilter(
                user=str(user.id),
                begin=begin,
                end=end,
                status="all"  # All absences (approved + open)
            ))
            if absences:
                # Take first absence type (if multiple)
                absence_type = absences[0].type if absences else "Abwesend"
                absent_users_with_reason[user.id] = (user, absence_type)
        except Exception:
            # Skip users we can't check
            continue

    # 4. Present = All - Absent
    present_users = [u for u in all_users if u.id not in absent_users_with_reason]

    # 5. Build report
    # Format date with weekday
    weekday_names = {
        0: "Montag", 1: "Dienstag", 2: "Mittwoch", 3: "Donnerstag",
        4: "Freitag", 5: "Samstag", 6: "Sonntag"
    }
    weekday = weekday_names.get(check_date.weekday(), "")
    formatted_date = f"{weekday}, {check_date.strftime('%d.%m.%Y')}"

    result = f"# Attendance Report for {formatted_date}\n\n"
    result += f"## Present ({len(present_users)} of {len(all_users)})\n"

    for user in sorted(present_users, key=lambda u: u.username.lower()):
        display_name = user.alias if hasattr(user, 'alias') and user.alias else user.username
        result += f"- ✓ {display_name}\n"

    if absent_users_with_reason:
        result += f"\n## Absent ({len(absent_users_with_reason)})\n"
        for user, absence_type in sorted(absent_users_with_reason.values(), key=lambda x: x[0].username.lower()):
            display_name = user.alias if hasattr(user, 'alias') and user.alias else user.username
            type_label = TYPE_LABELS.get(absence_type, absence_type)
            result += f"- ✗ {display_name} ({type_label})\n"

    return [TextContent(type="text", text=result)]


# Batch operations

async def _handle_batch_delete(client: KimaiClient, ids: List[int]) -> List[TextContent]:
    """Batch delete multiple absences."""
    if not ids:
        return [TextContent(type="text", text="Error: 'ids' parameter is required for batch_delete action")]

    async def delete_one(id: int) -> int:
        await client.delete_absence(id)
        return id

    success, failed = await execute_batch(ids, delete_one)
    result = format_batch_result("Delete", success, failed, "absences")
    return [TextContent(type="text", text=result)]


async def _handle_batch_approve(client: KimaiClient, ids: List[int]) -> List[TextContent]:
    """Batch approve multiple absences."""
    if not ids:
        return [TextContent(type="text", text="Error: 'ids' parameter is required for batch_approve action")]

    async def approve_one(id: int) -> int:
        await client.approve_absence_approval(id)
        return id

    success, failed = await execute_batch(ids, approve_one)
    result = format_batch_result("Approve", success, failed, "absences")
    return [TextContent(type="text", text=result)]


async def _handle_batch_reject(client: KimaiClient, ids: List[int]) -> List[TextContent]:
    """Batch reject multiple absences."""
    if not ids:
        return [TextContent(type="text", text="Error: 'ids' parameter is required for batch_reject action")]

    async def reject_one(id: int) -> int:
        await client.reject_absence_approval(id)
        return id

    success, failed = await execute_batch(ids, reject_one)
    result = format_batch_result("Reject", success, failed, "absences")
    return [TextContent(type="text", text=result)]