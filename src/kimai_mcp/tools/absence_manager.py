"""Consolidated Absence Manager tool for all absence operations."""

from typing import List, Dict, Any, Optional
from datetime import datetime
from mcp.types import Tool, TextContent
from ..client import KimaiClient
from ..models import AbsenceForm, AbsenceFilter


def absence_tool() -> Tool:
    """Define the consolidated absence management tool."""
    return Tool(
        name="absence",
        description="Universal absence management tool for complete absence workflow. Replaces 7 individual absence tools with one flexible interface.",
        inputSchema={
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "types", "create", "delete", "approve", "reject"],
                    "description": "The action to perform"
                },
                "id": {
                    "type": "integer",
                    "description": "Absence ID (required for delete, approve, reject actions)"
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
                            "description": "Type of absence (holiday, time_off, sickness, etc.)"
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
        else:
            return [TextContent(
                type="text",
                text=f"Error: Unknown action '{action}'. Valid actions: list, types, create, delete, approve, reject"
            )]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def _handle_absence_list(client: KimaiClient, filters: Dict) -> List[TextContent]:
    """Handle absence list action."""
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
    # user_scope == "all" means no user filter
    
    # Build absence filter - convert string dates to datetime objects
    begin_date = None
    end_date = None
    
    if filters.get("begin"):
        try:
            begin_date = datetime.strptime(filters["begin"], "%Y-%m-%d")
        except ValueError:
            return [TextContent(type="text", text=f"Error: Invalid begin date format. Expected YYYY-MM-DD, got '{filters['begin']}'")]
    
    if filters.get("end"):
        try:
            end_date = datetime.strptime(filters["end"], "%Y-%m-%d")
        except ValueError:
            return [TextContent(type="text", text=f"Error: Invalid end date format. Expected YYYY-MM-DD, got '{filters['end']}'")]
    
    absence_filter = AbsenceFilter(
        user=user_filter,
        begin=begin_date,
        end=end_date,
        status=filters.get("status", "all")
    )
    
    # Fetch absences
    absences = await client.get_absences(absence_filter)
    
    # Build response
    if user_scope == "all":
        result = f"Found {len(absences)} absence(s) for all users\\n\\n"
    elif user_scope == "specific":
        result = f"Found {len(absences)} absence(s) for user {user_filter}\\n\\n"
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
            result += f"  Half Day: Yes\\n"
        
        if absence.comment:
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
    
    await client.approve_absence(id)
    return [TextContent(type="text", text=f"Approved absence ID {id}")]


async def _handle_absence_reject(client: KimaiClient, id: Optional[int]) -> List[TextContent]:
    """Handle absence reject action."""
    if not id:
        return [TextContent(type="text", text="Error: 'id' parameter is required for reject action")]
    
    await client.reject_absence(id)
    return [TextContent(type="text", text=f"Rejected absence ID {id}")]