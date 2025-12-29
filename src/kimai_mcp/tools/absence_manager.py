"""Consolidated Absence Manager tool for all absence operations."""

from typing import List, Dict, Optional
from datetime import datetime
from mcp.types import Tool, TextContent
from ..client import KimaiClient
from ..models import AbsenceForm, AbsenceFilter


def absence_tool() -> Tool:
    """Define the consolidated absence management tool."""
    return Tool(
        name="absence",
        description="Universal absence management tool for complete absence workflow. Supports list, create, delete, approve, reject, and request approval actions.",
        inputSchema={
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "types", "create", "delete", "approve", "reject", "request"],
                    "description": "The action to perform"
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
        else:
            return [TextContent(
                type="text",
                text=f"Error: Unknown action '{action}'. Valid actions: list, types, create, delete, approve, reject, request"
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


async def _handle_absence_create(client: KimaiClient, data: Dict) -> List[TextContent]:
    """Handle absence create action."""
    required_fields = ["comment", "date", "type"]
    missing_fields = [field for field in required_fields if not data.get(field)]
    
    if missing_fields:
        return [TextContent(
            type="text",
            text=f"Error: Missing required fields: {', '.join(missing_fields)}"
        )]
    
    # Create absence form
    form = AbsenceForm(
        comment=data["comment"],
        date=data["date"],
        type=data["type"],
        user=data.get("user"),
        end=data.get("end"),
        halfDay=data.get("halfDay", False),
        duration=data.get("duration")
    )
    
    absence = await client.create_absence(form)
    
    duration_text = ""
    if hasattr(absence, "endDate") and absence.endDate:
        duration_text = f" from {absence.date} to {absence.endDate}"
    elif hasattr(absence, "halfDay") and absence.halfDay:
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