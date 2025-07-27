"""Calendar integration MCP tools."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from mcp.types import Tool, TextContent

from ..client import KimaiClient
from ..models import AbsenceFilter


# Tool definitions

def get_absences_calendar_tool() -> Tool:
    """Define the get absences calendar tool."""
    return Tool(
        name="calendar_absences",
        description="Get absences for calendar integration",
        inputSchema={
            "type": "object",
            "properties": {
                "begin": {"type": "string", "format": "date", "description": "Start date (YYYY-MM-DD)"},
                "end": {"type": "string", "format": "date", "description": "End date (YYYY-MM-DD)"},
                "user": {"type": "string", "description": "User ID to filter absences"},
                "language": {"type": "string", "description": "Language for display (e.g., 'en', 'de')"}
            }
        }
    )


def get_public_holidays_calendar_tool() -> Tool:
    """Define the get public holidays calendar tool."""
    return Tool(
        name="calendar_holidays",
        description="Get public holidays for calendar integration",
        inputSchema={
            "type": "object",
            "properties": {
                "begin": {"type": "string", "format": "date", "description": "Start date (YYYY-MM-DD)"},
                "end": {"type": "string", "format": "date", "description": "End date (YYYY-MM-DD)"},
                "country": {"type": "string", "description": "Country code filter"}
            }
        }
    )


# Tool handlers

async def handle_get_absences_calendar(client: KimaiClient, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
    """Handle getting absences for calendar integration."""
    filters = AbsenceFilter()
    language = None
    
    if arguments:
        if 'begin' in arguments:
            filters.begin = datetime.fromisoformat(arguments['begin'] + 'T00:00:00')
        if 'end' in arguments:
            filters.end = datetime.fromisoformat(arguments['end'] + 'T23:59:59')
        if 'user' in arguments:
            filters.user = arguments['user']
        if 'language' in arguments:
            language = arguments['language']
    
    calendar_events = await client.get_absences_calendar(filters, language)
    
    if not calendar_events:
        return [TextContent(type="text", text="No absences found for the specified period.")]
    
    results = []
    for event in calendar_events:
        event_info = f"""📅 {event.title}
Start: {event.start}
End: {event.end}
All Day: {'Yes' if event.all_day else 'No'}
URL: {event.url or 'N/A'}
---"""
        results.append(event_info)
    
    summary = f"Found {len(calendar_events)} absence event(s):\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_get_public_holidays_calendar(client: KimaiClient, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
    """Handle getting public holidays for calendar integration."""
    from ..models import PublicHolidayFilter
    
    filters = PublicHolidayFilter()
    
    if arguments:
        if 'begin' in arguments:
            filters.begin = datetime.fromisoformat(arguments['begin'] + 'T00:00:00')
        if 'end' in arguments:
            filters.end = datetime.fromisoformat(arguments['end'] + 'T23:59:59')
        if 'country' in arguments:
            filters.country = arguments['country']
    
    calendar_events = await client.get_public_holidays_calendar(filters)
    
    if not calendar_events:
        return [TextContent(type="text", text="No public holidays found for the specified period.")]
    
    results = []
    for event in calendar_events:
        event_info = f"""🎉 {event.title}
Start: {event.start}
End: {event.end}
All Day: {'Yes' if event.all_day else 'No'}
URL: {event.url or 'N/A'}
---"""
        results.append(event_info)
    
    summary = f"Found {len(calendar_events)} public holiday(s):\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]