"""Public holiday management MCP tools."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from mcp.types import Tool, TextContent

from ..client import KimaiClient
from ..models import PublicHolidayFilter


# Tool definitions

def list_public_holidays_tool() -> Tool:
    """Define the list public holidays tool."""
    return Tool(
        name="holiday_list",
        description="List public holidays with optional filters",
        inputSchema={
            "type": "object",
            "properties": {
                "begin": {"type": "string", "format": "date", "description": "Start date (YYYY-MM-DD)"},
                "end": {"type": "string", "format": "date", "description": "End date (YYYY-MM-DD)"},
                "country": {"type": "string", "description": "Country code filter"},
                "year": {"type": "integer", "description": "Year filter"}
            }
        }
    )


def delete_public_holiday_tool() -> Tool:
    """Define the delete public holiday tool."""
    return Tool(
        name="holiday_delete",
        description="Delete a public holiday",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Public holiday ID to delete"}
            }
        }
    )


# Tool handlers

async def handle_list_public_holidays(client: KimaiClient, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
    """Handle listing public holidays."""
    filters = PublicHolidayFilter()
    
    if arguments:
        if 'begin' in arguments:
            filters.begin = datetime.fromisoformat(arguments['begin'] + 'T00:00:00')
        if 'end' in arguments:
            filters.end = datetime.fromisoformat(arguments['end'] + 'T23:59:59')
        if 'country' in arguments:
            filters.country = arguments['country']
        if 'year' in arguments:
            # Convert year to date range
            year = arguments['year']
            filters.begin = datetime(year, 1, 1)
            filters.end = datetime(year, 12, 31, 23, 59, 59)
    
    holidays = await client.get_public_holidays(filters)
    
    if not holidays:
        return [TextContent(type="text", text="No public holidays found matching the criteria.")]
    
    results = []
    for holiday in holidays:
        holiday_info = f"""🎉 {holiday.name}
ID: {holiday.id}
Date: {holiday.date.strftime('%Y-%m-%d')}
Country: {holiday.country or 'N/A'}
Type: {holiday.type or 'Public Holiday'}
---"""
        results.append(holiday_info)
    
    summary = f"Found {len(holidays)} public holiday(s):\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_delete_public_holiday(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle deleting a public holiday."""
    holiday_id = arguments['id']
    
    await client.delete_public_holiday(holiday_id)
    
    return [TextContent(type="text", text=f"Public holiday #{holiday_id} deleted successfully.")]