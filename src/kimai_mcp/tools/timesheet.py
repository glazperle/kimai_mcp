"""Timesheet-related MCP tools."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from mcp.types import Tool, TextContent
from pydantic import BaseModel, Field

from ..client import KimaiClient
from ..models import TimesheetEditForm, TimesheetFilter, MetaFieldForm


# Tool definitions

def list_timesheets_tool() -> Tool:
    """Define the list timesheets tool."""
    return Tool(
        name="timesheet_list",
        description="List timesheets with optional filters",
        inputSchema={
            "type": "object",
            "properties": {
                "user": {"type": "string", "description": "User ID or 'all' for all users"},
                "project": {"type": "integer", "description": "Project ID filter"},
                "activity": {"type": "integer", "description": "Activity ID filter"},
                "customer": {"type": "integer", "description": "Customer ID filter"},
                "begin": {"type": "string", "format": "date-time", "description": "Start date filter (ISO format)"},
                "end": {"type": "string", "format": "date-time", "description": "End date filter (ISO format)"},
                "exported": {"type": "integer", "enum": [0, 1], "description": "Export status: 0=not exported, 1=exported"},
                "active": {"type": "integer", "enum": [0, 1], "description": "Active status: 0=stopped, 1=active"},
                "billable": {"type": "integer", "enum": [0, 1], "description": "Billable status: 0=non-billable, 1=billable"},
                "page": {"type": "integer", "description": "Page number for pagination"},
                "size": {"type": "integer", "description": "Page size (default: 50)"},
                "term": {"type": "string", "description": "Search term"}
            }
        }
    )


def get_timesheet_tool() -> Tool:
    """Define the get timesheet tool."""
    return Tool(
        name="timesheet_get",
        description="Get a specific timesheet by ID",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Timesheet ID"}
            }
        }
    )


def create_timesheet_tool() -> Tool:
    """Define the create timesheet tool."""
    return Tool(
        name="timesheet_create",
        description="Create a new timesheet entry",
        inputSchema={
            "type": "object",
            "required": ["project", "activity"],
            "properties": {
                "project": {"type": "integer", "description": "Project ID"},
                "activity": {"type": "integer", "description": "Activity ID"},
                "begin": {"type": "string", "format": "date-time", "description": "Start time (ISO format, default: now)"},
                "end": {"type": "string", "format": "date-time", "description": "End time (ISO format, if not set: running)"},
                "description": {"type": "string", "description": "Description/notes"},
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "user": {"type": "integer", "description": "User ID (requires permission)"},
                "billable": {"type": "boolean", "description": "Whether entry is billable"},
                "fixedRate": {"type": "number", "description": "Fixed rate override"},
                "hourlyRate": {"type": "number", "description": "Hourly rate override"}
            }
        }
    )


def update_timesheet_tool() -> Tool:
    """Define the update timesheet tool."""
    return Tool(
        name="timesheet_update",
        description="Update an existing timesheet entry",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Timesheet ID to update"},
                "project": {"type": "integer", "description": "Project ID"},
                "activity": {"type": "integer", "description": "Activity ID"},
                "begin": {"type": "string", "format": "date-time", "description": "Start time (ISO format)"},
                "end": {"type": "string", "format": "date-time", "description": "End time (ISO format)"},
                "description": {"type": "string", "description": "Description/notes"},
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "billable": {"type": "boolean", "description": "Whether entry is billable"},
                "exported": {"type": "boolean", "description": "Export status"},
                "fixedRate": {"type": "number", "description": "Fixed rate override"},
                "hourlyRate": {"type": "number", "description": "Hourly rate override"}
            }
        }
    )


def delete_timesheet_tool() -> Tool:
    """Define the delete timesheet tool."""
    return Tool(
        name="timesheet_delete",
        description="Delete a timesheet entry",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Timesheet ID to delete"}
            }
        }
    )


def start_timer_tool() -> Tool:
    """Define the start timer tool."""
    return Tool(
        name="timesheet_start",
        description="Start a new timer (creates a running timesheet)",
        inputSchema={
            "type": "object",
            "required": ["project", "activity"],
            "properties": {
                "project": {"type": "integer", "description": "Project ID"},
                "activity": {"type": "integer", "description": "Activity ID"},
                "description": {"type": "string", "description": "Description/notes"},
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "user": {"type": "integer", "description": "User ID (requires permission)"}
            }
        }
    )


def stop_timer_tool() -> Tool:
    """Define the stop timer tool."""
    return Tool(
        name="timesheet_stop",
        description="Stop a running timer",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Timesheet ID of the running timer"}
            }
        }
    )


def get_active_timers_tool() -> Tool:
    """Define the get active timers tool."""
    return Tool(
        name="timesheet_active",
        description="Get all active/running timers for the current user",
        inputSchema={
            "type": "object",
            "properties": {}
        }
    )


def get_recent_activities_tool() -> Tool:
    """Define the get recent activities tool."""
    return Tool(
        name="timesheet_recent",
        description="Get recent timesheet activities for quick access",
        inputSchema={
            "type": "object",
            "properties": {
                "size": {"type": "integer", "description": "Number of entries to return (default: 10)"},
                "begin": {"type": "string", "format": "date-time", "description": "Only entries after this date (ISO format)"}
            }
        }
    )


def restart_timesheet_tool() -> Tool:
    """Define the restart timesheet tool."""
    return Tool(
        name="timesheet_restart",
        description="Restart a timesheet (create a new one based on an existing entry)",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Timesheet ID to restart"},
                "copy_all": {"type": "boolean", "description": "Whether to copy all data from original", "default": False},
                "begin": {"type": "string", "format": "date-time", "description": "Optional start time for new timesheet (ISO format)"}
            }
        }
    )


def duplicate_timesheet_tool() -> Tool:
    """Define the duplicate timesheet tool."""
    return Tool(
        name="timesheet_duplicate",
        description="Duplicate a timesheet entry",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Timesheet ID to duplicate"}
            }
        }
    )


def toggle_timesheet_export_tool() -> Tool:
    """Define the toggle timesheet export tool."""
    return Tool(
        name="timesheet_export_toggle",
        description="Toggle the export/lock state of a timesheet",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Timesheet ID to toggle export state"}
            }
        }
    )


def update_timesheet_meta_tool() -> Tool:
    """Define the update timesheet meta field tool."""
    return Tool(
        name="timesheet_meta_update",
        description="Update a timesheet's custom field",
        inputSchema={
            "type": "object",
            "required": ["id", "name", "value"],
            "properties": {
                "id": {"type": "integer", "description": "Timesheet ID"},
                "name": {"type": "string", "description": "Custom field name"},
                "value": {"type": "string", "description": "Custom field value"}
            }
        }
    )


# Tool handlers

async def handle_list_timesheets(client: KimaiClient, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
    """Handle listing timesheets."""
    filters = TimesheetFilter()
    
    if arguments:
        # Parse filters
        if 'user' in arguments:
            filters.user = arguments['user']
        if 'project' in arguments:
            filters.project = arguments['project']
        if 'activity' in arguments:
            filters.activity = arguments['activity']
        if 'customer' in arguments:
            filters.customer = arguments['customer']
        if 'begin' in arguments:
            filters.begin = datetime.fromisoformat(arguments['begin'].replace('Z', '+00:00'))
        if 'end' in arguments:
            filters.end = datetime.fromisoformat(arguments['end'].replace('Z', '+00:00'))
        if 'exported' in arguments:
            filters.exported = arguments['exported']
        if 'active' in arguments:
            filters.active = arguments['active']
        if 'billable' in arguments:
            filters.billable = arguments['billable']
        if 'page' in arguments:
            filters.page = arguments['page']
        if 'size' in arguments:
            filters.size = arguments['size']
        if 'term' in arguments:
            filters.term = arguments['term']
    
    timesheets = await client.get_timesheets(filters)
    
    if not timesheets:
        return [TextContent(type="text", text="No timesheets found matching the criteria.")]
    
    # Format results
    results = []
    for ts in timesheets:
        duration_str = f"{ts.duration // 3600}h {(ts.duration % 3600) // 60}m" if ts.duration else "Running"
        status = "🟢 Active" if ts.end is None else "⏹️ Stopped"
        
        result = f"""ID: {ts.id} {status}
Project: {ts.project} | Activity: {ts.activity}
Time: {ts.begin.strftime('%Y-%m-%d %H:%M')} - {ts.end.strftime('%H:%M') if ts.end else 'now'}
Duration: {duration_str}
Description: {ts.description or '(no description)'}
Tags: {', '.join(ts.tags) if ts.tags else '(no tags)'}
Rate: {ts.rate} | Billable: {'Yes' if ts.billable else 'No'} | Exported: {'Yes' if ts.exported else 'No'}
---"""
        results.append(result)
    
    summary = f"Found {len(timesheets)} timesheet(s):\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_get_timesheet(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle getting a specific timesheet."""
    timesheet_id = arguments['id']
    ts = await client.get_timesheet(timesheet_id)
    
    duration_str = f"{ts.duration // 3600}h {(ts.duration % 3600) // 60}m" if ts.duration else "Running"
    status = "🟢 Active" if ts.end is None else "⏹️ Stopped"
    
    result = f"""Timesheet #{ts.id} {status}
Project ID: {ts.project}
Activity ID: {ts.activity}
User ID: {ts.user}
Started: {ts.begin.strftime('%Y-%m-%d %H:%M:%S')}
Ended: {ts.end.strftime('%Y-%m-%d %H:%M:%S') if ts.end else 'Still running'}
Duration: {duration_str} ({ts.duration} seconds)
Description: {ts.description or '(no description)'}
Tags: {', '.join(ts.tags) if ts.tags else '(no tags)'}
Rate: {ts.rate}
Hourly Rate: {ts.hourly_rate}
Fixed Rate: {ts.fixed_rate}
Internal Rate: {ts.internal_rate}
Billable: {'Yes' if ts.billable else 'No'}
Exported: {'Yes' if ts.exported else 'No'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_create_timesheet(client: KimaiClient, arguments: Dict[str, Any], default_user_id: Optional[str] = None) -> List[TextContent]:
    """Handle creating a new timesheet."""
    form_data = {
        'project': arguments['project'],
        'activity': arguments['activity']
    }
    
    # Optional fields
    if 'begin' in arguments:
        form_data['begin'] = datetime.fromisoformat(arguments['begin'].replace('Z', '+00:00'))
    if 'end' in arguments:
        form_data['end'] = datetime.fromisoformat(arguments['end'].replace('Z', '+00:00'))
    if 'description' in arguments:
        form_data['description'] = arguments['description']
    if 'tags' in arguments:
        form_data['tags'] = arguments['tags']
    if 'user' in arguments:
        form_data['user'] = arguments['user']
    elif default_user_id:
        form_data['user'] = int(default_user_id)
    if 'billable' in arguments:
        form_data['billable'] = arguments['billable']
    if 'fixedRate' in arguments:
        form_data['fixed_rate'] = arguments['fixedRate']
    if 'hourlyRate' in arguments:
        form_data['hourly_rate'] = arguments['hourlyRate']
    
    timesheet_form = TimesheetEditForm(**form_data)
    ts = await client.create_timesheet(timesheet_form)
    
    status = "🟢 Started" if ts.end is None else "⏹️ Created"
    
    result = f"""Timesheet created successfully! {status}
ID: {ts.id}
Project: {ts.project} | Activity: {ts.activity}
Started: {ts.begin.strftime('%Y-%m-%d %H:%M:%S')}
Description: {ts.description or '(no description)'}
Tags: {', '.join(ts.tags) if ts.tags else '(no tags)'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_update_timesheet(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle updating a timesheet."""
    timesheet_id = arguments.pop('id')
    
    form_data = {}
    
    # Map fields
    if 'project' in arguments:
        form_data['project'] = arguments['project']
    if 'activity' in arguments:
        form_data['activity'] = arguments['activity']
    if 'begin' in arguments:
        form_data['begin'] = datetime.fromisoformat(arguments['begin'].replace('Z', '+00:00'))
    if 'end' in arguments:
        form_data['end'] = datetime.fromisoformat(arguments['end'].replace('Z', '+00:00'))
    if 'description' in arguments:
        form_data['description'] = arguments['description']
    if 'tags' in arguments:
        form_data['tags'] = arguments['tags']
    if 'billable' in arguments:
        form_data['billable'] = arguments['billable']
    if 'exported' in arguments:
        form_data['exported'] = arguments['exported']
    if 'fixedRate' in arguments:
        form_data['fixed_rate'] = arguments['fixedRate']
    if 'hourlyRate' in arguments:
        form_data['hourly_rate'] = arguments['hourlyRate']
    
    # Need at least project and activity for update
    if 'project' not in form_data or 'activity' not in form_data:
        # Fetch current timesheet to get required fields
        current = await client.get_timesheet(timesheet_id)
        if 'project' not in form_data:
            form_data['project'] = current.project
        if 'activity' not in form_data:
            form_data['activity'] = current.activity
    
    timesheet_form = TimesheetEditForm(**form_data)
    ts = await client.update_timesheet(timesheet_id, timesheet_form)
    
    result = f"""Timesheet #{ts.id} updated successfully!
Project: {ts.project} | Activity: {ts.activity}
Time: {ts.begin.strftime('%Y-%m-%d %H:%M')} - {ts.end.strftime('%H:%M') if ts.end else 'now'}
Description: {ts.description or '(no description)'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_delete_timesheet(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle deleting a timesheet."""
    timesheet_id = arguments['id']
    await client.delete_timesheet(timesheet_id)
    
    return [TextContent(type="text", text=f"Timesheet #{timesheet_id} deleted successfully.")]


async def handle_start_timer(client: KimaiClient, arguments: Dict[str, Any], default_user_id: Optional[str] = None) -> List[TextContent]:
    """Handle starting a new timer."""
    form_data = {
        'project': arguments['project'],
        'activity': arguments['activity'],
        'begin': datetime.now()  # Start now
    }
    
    # Optional fields
    if 'description' in arguments:
        form_data['description'] = arguments['description']
    if 'tags' in arguments:
        form_data['tags'] = arguments['tags']
    if 'user' in arguments:
        form_data['user'] = arguments['user']
    elif default_user_id:
        form_data['user'] = int(default_user_id)
    
    timesheet_form = TimesheetEditForm(**form_data)
    ts = await client.create_timesheet(timesheet_form)
    
    result = f"""Timer started! 🟢
ID: {ts.id}
Project: {ts.project} | Activity: {ts.activity}
Started: {ts.begin.strftime('%Y-%m-%d %H:%M:%S')}
Description: {ts.description or '(no description)'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_stop_timer(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle stopping a timer."""
    timesheet_id = arguments['id']
    ts = await client.stop_timesheet(timesheet_id)
    
    duration_str = f"{ts.duration // 3600}h {(ts.duration % 3600) // 60}m"
    
    result = f"""Timer stopped! ⏹️
ID: {ts.id}
Duration: {duration_str}
Ended: {ts.end.strftime('%Y-%m-%d %H:%M:%S')}"""
    
    return [TextContent(type="text", text=result)]


async def handle_get_active_timers(client: KimaiClient) -> List[TextContent]:
    """Handle getting active timers."""
    timesheets = await client.get_active_timesheets()
    
    if not timesheets:
        return [TextContent(type="text", text="No active timers running.")]
    
    results = []
    for ts in timesheets:
        # Calculate running duration
        now = datetime.now(ts.begin.tzinfo)
        duration = int((now - ts.begin).total_seconds())
        duration_str = f"{duration // 3600}h {(duration % 3600) // 60}m"
        
        result = f"""🟢 Timer #{ts.id}
Project: {ts.project} | Activity: {ts.activity}
Started: {ts.begin.strftime('%Y-%m-%d %H:%M')}
Running for: {duration_str}
Description: {ts.description or '(no description)'}
---"""
        results.append(result)
    
    summary = f"Found {len(timesheets)} active timer(s):\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_get_recent_activities(client: KimaiClient, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
    """Handle getting recent activities."""
    size = 10
    begin = None
    
    if arguments:
        if 'size' in arguments:
            size = arguments['size']
        if 'begin' in arguments:
            begin = datetime.fromisoformat(arguments['begin'].replace('Z', '+00:00'))
    
    timesheets = await client.get_recent_timesheets(begin=begin, size=size)
    
    if not timesheets:
        return [TextContent(type="text", text="No recent activities found.")]
    
    results = []
    for ts in timesheets:
        result = f"""Project: {ts.project} | Activity: {ts.activity}
Last used: {ts.begin.strftime('%Y-%m-%d %H:%M')}
Description: {ts.description or '(no description)'}
Tags: {', '.join(ts.tags) if ts.tags else '(no tags)'}
---"""
        results.append(result)
    
    summary = f"Recent activities (last {len(timesheets)}):\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_restart_timesheet(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle restarting a timesheet."""
    timesheet_id = arguments['id']
    copy_all = arguments.get('copy_all', False)
    begin = None
    
    if 'begin' in arguments:
        begin = datetime.fromisoformat(arguments['begin'].replace('Z', '+00:00'))
    
    timesheet = await client.restart_timesheet(timesheet_id, copy_all=copy_all, begin=begin)
    
    result = f"""Timesheet restarted successfully! ▶️

New Timer ID: {timesheet.id}
Project: {timesheet.project} | Activity: {timesheet.activity}
Started: {timesheet.begin.strftime('%Y-%m-%d %H:%M')}
Description: {timesheet.description or '(no description)'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_duplicate_timesheet(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle duplicating a timesheet."""
    timesheet_id = arguments['id']
    
    timesheet = await client.duplicate_timesheet(timesheet_id)
    
    duration_str = ""
    if timesheet.duration:
        hours = timesheet.duration // 3600
        minutes = (timesheet.duration % 3600) // 60
        duration_str = f"\nDuration: {hours}h {minutes}m"
    
    result = f"""Timesheet duplicated successfully! 📋

New Entry ID: {timesheet.id}
Project: {timesheet.project} | Activity: {timesheet.activity}
Started: {timesheet.begin.strftime('%Y-%m-%d %H:%M')}
Ended: {timesheet.end.strftime('%Y-%m-%d %H:%M') if timesheet.end else 'Still running'}{duration_str}
Description: {timesheet.description or '(no description)'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_toggle_timesheet_export(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle toggling timesheet export state."""
    timesheet_id = arguments['id']
    
    timesheet = await client.toggle_timesheet_export(timesheet_id)
    
    export_status = "🔒 Locked (Exported)" if timesheet.exported else "🔓 Unlocked (Not Exported)"
    
    result = f"""Export state toggled successfully! {export_status}

Timesheet ID: {timesheet.id}
Project: {timesheet.project} | Activity: {timesheet.activity}
Date: {timesheet.begin.strftime('%Y-%m-%d %H:%M')}
Status: {export_status}"""
    
    return [TextContent(type="text", text=result)]


async def handle_update_timesheet_meta(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle updating a timesheet's custom field."""
    timesheet_id = arguments['id']
    
    meta_field = MetaFieldForm(
        name=arguments['name'],
        value=arguments['value']
    )
    
    timesheet = await client.update_timesheet_meta(timesheet_id, meta_field)
    
    result = f"""Custom field updated successfully!

Timesheet ID: {timesheet.id}
Project: {timesheet.project} | Activity: {timesheet.activity}
Field: {arguments['name']} = {arguments['value']}"""
    
    return [TextContent(type="text", text=result)]