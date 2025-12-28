"""Calendar and Meta tools for additional functionality."""

from typing import List, Dict
from mcp.types import Tool, TextContent
from ..client import KimaiClient
from ..models import MetaFieldForm


def calendar_tool() -> Tool:
    """Define the consolidated calendar tool."""
    return Tool(
        name="calendar",
        description="Universal calendar tool for accessing absences and holidays data.",
        inputSchema={
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["absences", "holidays"],
                    "description": "The type of calendar data to retrieve"
                },
                "filters": {
                    "type": "object",
                    "description": "Filters for calendar data",
                    "properties": {
                        "user": {
                            "type": "integer",
                            "description": "User ID filter (for absences)"
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
                        }
                    }
                }
            }
        }
    )


def meta_tool() -> Tool:
    """Define the consolidated meta fields tool."""
    return Tool(
        name="meta",
        description="Universal meta fields management tool for custom field operations across all entity types.",
        inputSchema={
            "type": "object",
            "required": ["entity", "entity_id", "action"],
            "properties": {
                "entity": {
                    "type": "string",
                    "enum": ["customer", "project", "activity", "timesheet"],
                    "description": "The entity type to manage meta fields for"
                },
                "entity_id": {
                    "type": "integer",
                    "description": "The ID of the entity"
                },
                "action": {
                    "type": "string",
                    "enum": ["update"],
                    "description": "The action to perform (currently only update is supported)"
                },
                "data": {
                    "type": "array",
                    "description": "Meta field data for update action",
                    "items": {
                        "type": "object",
                        "required": ["name", "value"],
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Meta field name"
                            },
                            "value": {
                                "description": "Meta field value (can be any type)"
                            }
                        }
                    }
                }
            }
        }
    )


def user_current_tool() -> Tool:
    """Define the current user tool."""
    return Tool(
        name="user_current",
        description="Get information about the currently authenticated user.",
        inputSchema={
            "type": "object",
            "properties": {}
        }
    )


async def handle_calendar(client: KimaiClient, **params) -> List[TextContent]:
    """Handle calendar operations."""
    calendar_type = params.get("type")
    filters = params.get("filters", {})
    
    try:
        if calendar_type == "absences":
            return await _handle_calendar_absences(client, filters)
        elif calendar_type == "holidays":
            return await _handle_calendar_holidays(client, filters)
        else:
            return [TextContent(
                type="text",
                text=f"Error: Unknown calendar type '{calendar_type}'. Valid types: absences, holidays"
            )]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def handle_meta(client: KimaiClient, **params) -> List[TextContent]:
    """Handle meta field operations."""
    entity = params.get("entity")
    entity_id = params.get("entity_id")
    action = params.get("action")
    data = params.get("data", [])
    
    if not entity_id:
        return [TextContent(type="text", text="Error: 'entity_id' parameter is required")]
    
    if action != "update":
        return [TextContent(
            type="text",
            text=f"Error: Unknown action '{action}'. Currently only 'update' is supported"
        )]
    
    if not data:
        return [TextContent(type="text", text="Error: 'data' parameter is required for update action")]
    
    try:
        # Route to appropriate meta handler
        handlers = {
            "customer": client.update_customer_meta,
            "project": client.update_project_meta,
            "activity": client.update_activity_meta,
            "timesheet": client.update_timesheet_meta
        }
        
        handler = handlers.get(entity)
        if not handler:
            return [TextContent(
                type="text",
                text=f"Error: Unknown entity type '{entity}'. Valid types: customer, project, activity, timesheet"
            )]
        
        # Convert data to MetaFieldForm objects
        meta_fields = [MetaFieldForm(name=field["name"], value=field["value"]) for field in data]
        
        # Execute meta update
        await handler(entity_id, meta_fields)
        
        return [TextContent(
            type="text",
            text=f"Updated {len(meta_fields)} meta field(s) for {entity} ID {entity_id}"
        )]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def handle_user_current(client: KimaiClient, **params) -> List[TextContent]:
    """Handle current user request."""
    try:
        user = await client.get_current_user()
        
        result = f"Current User: {user.username} (ID: {user.id})\\n"
        result += f"Name: {user.alias or 'Not set'}\\n"
        result += f"Title: {user.title or 'Not set'}\\n"
        result += f"Status: {'Active' if user.enabled else 'Inactive'}\\n"
        
        if hasattr(user, 'language') and user.language:
            result += f"Language: {user.language}\\n"
        if hasattr(user, 'timezone') and user.timezone:
            result += f"Timezone: {user.timezone}\\n"
        if hasattr(user, 'roles') and user.roles:
            result += f"Roles: {', '.join(user.roles)}\\n"
        
        if hasattr(user, "supervisor") and user.supervisor:
            result += f"Supervisor: {user.supervisor.username}\\n"
        
        return [TextContent(type="text", text=result)]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def _handle_calendar_absences(client: KimaiClient, filters: Dict) -> List[TextContent]:
    """Handle calendar absences request."""
    # Build filter object - API doesn't support year/month, only begin/end dates
    # Convert date formats to ISO with time like in absence manager
    filter_params = {}
    if filters.get("user"):
        filter_params["user"] = str(filters["user"])
    if filters.get("begin"):
        from datetime import datetime
        try:
            parsed_date = datetime.strptime(filters["begin"], "%Y-%m-%d")
            filter_params["begin"] = parsed_date.strftime("%Y-%m-%dT00:00:00")
        except ValueError:
            filter_params["begin"] = filters["begin"]  # Use as-is if not in expected format
    if filters.get("end"):
        from datetime import datetime
        try:
            parsed_date = datetime.strptime(filters["end"], "%Y-%m-%d")
            filter_params["end"] = parsed_date.strftime("%Y-%m-%dT23:59:59")
        except ValueError:
            filter_params["end"] = filters["end"]  # Use as-is if not in expected format
    
    from ..models import AbsenceFilter
    absence_filter = AbsenceFilter(**filter_params) if filter_params else None
    
    absences = await client.get_absences_calendar(absence_filter)
    
    if not absences:
        result = "No absences found for the specified calendar period"
    else:
        result = f"Found {len(absences)} absence event(s) in calendar:\\n\\n"
        
        for event in absences:
            result += f"Title: {event.title}\\n"
            result += f"  Start: {event.start}\\n"
            
            if event.end:
                result += f"  End: {event.end}\\n"
            
            if event.all_day:
                result += "  All Day: Yes\\n"
            
            if event.color:
                result += f"  Color: {event.color}\\n"
            
            result += "\\n"
    
    return [TextContent(type="text", text=result)]


async def _handle_calendar_holidays(client: KimaiClient, filters: Dict) -> List[TextContent]:
    """Handle calendar holidays request."""
    # Build filter object - API doesn't support year/month, only begin/end dates
    filter_params = {}
    if filters.get("begin"):
        filter_params["begin"] = filters["begin"]
    if filters.get("end"):
        filter_params["end"] = filters["end"]
    
    from ..models import PublicHolidayFilter
    holiday_filter = PublicHolidayFilter(**filter_params) if filter_params else None
    
    holidays = await client.get_public_holidays_calendar(holiday_filter)
    
    if not holidays:
        result = "No holidays found for the specified calendar period"
    else:
        result = f"Found {len(holidays)} holiday event(s) in calendar:\\n\\n"
        
        for event in holidays:
            result += f"Title: {event.title}\\n"
            result += f"  Start: {event.start}\\n"
            
            if event.end:
                result += f"  End: {event.end}\\n"
            
            if event.all_day:
                result += "  All Day: Yes\\n"
            
            if event.color:
                result += f"  Color: {event.color}\\n"
            
            result += "\\n"
    
    return [TextContent(type="text", text=result)]