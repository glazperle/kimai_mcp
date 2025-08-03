"""Calendar and Meta tools for additional functionality."""

from typing import List, Dict, Any, Optional
from mcp.types import Tool, TextContent
from ..client import KimaiClient
from ..models import MetaFieldForm


def calendar_tool() -> Tool:
    """Define the consolidated calendar tool."""
    return Tool(
        name="calendar",
        description="Universal calendar tool for accessing absences and holidays data. Replaces 2 individual calendar tools.",
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
                        "year": {
                            "type": "integer",
                            "description": "Year filter"
                        },
                        "month": {
                            "type": "integer",
                            "description": "Month filter (1-12)"
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
        description="Universal meta fields management tool for custom field operations across all entity types. Replaces 4 individual meta tools.",
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
        description="Get information about the currently authenticated user. This is a specialized tool kept separate from the entity tool.",
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
        result += f"Email: {user.email}\\n"
        result += f"Status: {'Active' if user.enabled else 'Inactive'}\\n"
        result += f"Language: {user.language}\\n"
        result += f"Timezone: {user.timezone}\\n"
        
        if user.roles:
            result += f"Roles: {', '.join(user.roles)}\\n"
        
        if hasattr(user, "supervisor") and user.supervisor:
            result += f"Supervisor: {user.supervisor.username}\\n"
        
        return [TextContent(type="text", text=result)]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def _handle_calendar_absences(client: KimaiClient, filters: Dict) -> List[TextContent]:
    """Handle calendar absences request."""
    absences = await client.get_calendar_absences(
        user=filters.get("user"),
        year=filters.get("year"),
        month=filters.get("month"),
        begin=filters.get("begin"),
        end=filters.get("end")
    )
    
    if not absences:
        result = "No absences found for the specified calendar period"
    else:
        result = f"Found {len(absences)} absence(s) in calendar:\\n\\n"
        
        for absence in absences:
            result += f"Date: {absence.date} - {absence.type}\\n"
            result += f"  User: {absence.user.username if absence.user else 'Unknown'}\\n"
            
            if hasattr(absence, "endDate") and absence.endDate:
                result += f"  End Date: {absence.endDate}\\n"
            
            if hasattr(absence, "halfDay") and absence.halfDay:
                result += f"  Half Day: Yes\\n"
            
            if absence.comment:
                result += f"  Comment: {absence.comment}\\n"
            
            result += "\\n"
    
    return [TextContent(type="text", text=result)]


async def _handle_calendar_holidays(client: KimaiClient, filters: Dict) -> List[TextContent]:
    """Handle calendar holidays request."""
    holidays = await client.get_calendar_holidays(
        year=filters.get("year"),
        month=filters.get("month")
    )
    
    if not holidays:
        result = "No holidays found for the specified calendar period"
    else:
        result = f"Found {len(holidays)} holiday(s) in calendar:\\n\\n"
        
        for holiday in holidays:
            result += f"Date: {holiday.date} - {holiday.name}\\n"
            
            if hasattr(holiday, "type") and holiday.type:
                result += f"  Type: {holiday.type}\\n"
            
            if hasattr(holiday, "country") and holiday.country:
                result += f"  Country: {holiday.country}\\n"
            
            result += "\\n"
    
    return [TextContent(type="text", text=result)]