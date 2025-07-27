"""Activity-related MCP tools."""

from typing import Any, Dict, List, Optional

from mcp.types import Tool, TextContent

from ..client import KimaiClient
from ..models import ActivityFilter, ActivityEditForm, RateForm, MetaFieldForm


# Tool definitions

def list_activities_tool() -> Tool:
    """Define the list activities tool."""
    return Tool(
        name="activity_list",
        description="List activities with optional filters",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {"type": "integer", "description": "Project ID filter"},
                "projects": {"type": "array", "items": {"type": "integer"}, "description": "List of project IDs to filter"},
                "visible": {"type": "integer", "enum": [1, 2, 3], "description": "Visibility: 1=visible, 2=hidden, 3=all"},
                "globals": {"type": "string", "enum": ["0", "1"], "description": "Global activities: 0=no, 1=yes"},
                "orderBy": {"type": "string", "enum": ["id", "name", "project"], "description": "Sort field"},
                "order": {"type": "string", "enum": ["ASC", "DESC"], "description": "Sort order"},
                "term": {"type": "string", "description": "Search term"}
            }
        }
    )


def get_activity_tool() -> Tool:
    """Define the get activity tool."""
    return Tool(
        name="activity_get",
        description="Get detailed information about a specific activity",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Activity ID"}
            }
        }
    )


def create_activity_tool() -> Tool:
    """Define the create activity tool."""
    return Tool(
        name="activity_create",
        description="Create a new activity",
        inputSchema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "description": "Activity name"},
                "project": {"type": "integer", "description": "Project ID (omit for global activity)"},
                "comment": {"type": "string", "description": "Activity comment"},
                "visible": {"type": "boolean", "description": "Whether activity is visible"},
                "billable": {"type": "boolean", "description": "Whether activity is billable"},
                "budget": {"type": "number", "description": "Activity budget"},
                "timeBudget": {"type": "integer", "description": "Time budget in seconds"},
                "color": {"type": "string", "description": "Activity color (hex format)"},
                "number": {"type": "string", "description": "Activity number"}
            }
        }
    )


def update_activity_tool() -> Tool:
    """Define the update activity tool."""
    return Tool(
        name="activity_update",
        description="Update an existing activity",
        inputSchema={
            "type": "object",
            "required": ["id", "name"],
            "properties": {
                "id": {"type": "integer", "description": "Activity ID to update"},
                "name": {"type": "string", "description": "Activity name"},
                "project": {"type": "integer", "description": "Project ID (omit for global activity)"},
                "comment": {"type": "string", "description": "Activity comment"},
                "visible": {"type": "boolean", "description": "Whether activity is visible"},
                "billable": {"type": "boolean", "description": "Whether activity is billable"},
                "budget": {"type": "number", "description": "Activity budget"},
                "timeBudget": {"type": "integer", "description": "Time budget in seconds"},
                "color": {"type": "string", "description": "Activity color (hex format)"},
                "number": {"type": "string", "description": "Activity number"}
            }
        }
    )


def delete_activity_tool() -> Tool:
    """Define the delete activity tool."""
    return Tool(
        name="activity_delete",
        description="Delete an activity (WARNING: Deletes ALL linked timesheets)",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Activity ID to delete"}
            }
        }
    )


def get_activity_rates_tool() -> Tool:
    """Define the get activity rates tool."""
    return Tool(
        name="activity_rates_list",
        description="Get rates for an activity",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Activity ID"}
            }
        }
    )


def add_activity_rate_tool() -> Tool:
    """Define the add activity rate tool."""
    return Tool(
        name="activity_rate_add",
        description="Add a rate for an activity",
        inputSchema={
            "type": "object",
            "required": ["id", "rate"],
            "properties": {
                "id": {"type": "integer", "description": "Activity ID"},
                "user": {"type": "integer", "description": "User ID (optional, for user-specific rates)"},
                "rate": {"type": "number", "description": "Rate amount"},
                "internalRate": {"type": "number", "description": "Internal rate amount"},
                "isFixed": {"type": "boolean", "description": "Whether this is a fixed rate"}
            }
        }
    )


def delete_activity_rate_tool() -> Tool:
    """Define the delete activity rate tool."""
    return Tool(
        name="activity_rate_delete",
        description="Delete a rate for an activity",
        inputSchema={
            "type": "object",
            "required": ["id", "rate_id"],
            "properties": {
                "id": {"type": "integer", "description": "Activity ID"},
                "rate_id": {"type": "integer", "description": "Rate ID to delete"}
            }
        }
    )


def update_activity_meta_tool() -> Tool:
    """Define the update activity meta field tool."""
    return Tool(
        name="activity_meta_update",
        description="Update an activity's custom field",
        inputSchema={
            "type": "object",
            "required": ["id", "name", "value"],
            "properties": {
                "id": {"type": "integer", "description": "Activity ID"},
                "name": {"type": "string", "description": "Custom field name"},
                "value": {"type": "string", "description": "Custom field value"}
            }
        }
    )


# Tool handlers

async def handle_list_activities(client: KimaiClient, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
    """Handle listing activities."""
    filters = ActivityFilter()
    
    if arguments:
        # Parse filters
        if 'project' in arguments:
            filters.project = arguments['project']
        if 'projects' in arguments:
            filters.projects = arguments['projects']
        if 'visible' in arguments:
            filters.visible = arguments['visible']
        if 'globals' in arguments:
            filters.globals = arguments['globals']
        if 'orderBy' in arguments:
            filters.order_by = arguments['orderBy']
        if 'order' in arguments:
            filters.order = arguments['order']
        if 'term' in arguments:
            filters.term = arguments['term']
    
    activities = await client.get_activities(filters)
    
    if not activities:
        return [TextContent(type="text", text="No activities found matching the criteria.")]
    
    # Format results
    results = []
    for act in activities:
        visibility = "👁️ Visible" if act.visible else "🚫 Hidden"
        billable = "💰 Billable" if act.billable else "🆓 Non-billable"
        scope = "🌍 Global" if act.project is None else f"📁 Project {act.project}"
        
        result = f"""ID: {act.id} - {act.name} {visibility}
{scope}
Number: {act.number or '(none)'}
{billable}
Comment: {act.comment or '(no comment)'}
Color: {act.color or '(default)'}
---"""
        results.append(result)
    
    summary = f"Found {len(activities)} activity/activities:\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_get_activity(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle getting a specific activity."""
    activity_id = arguments['id']
    act = await client.get_activity(activity_id)
    
    visibility = "👁️ Visible" if act.visible else "🚫 Hidden"
    billable = "💰 Billable" if act.billable else "🆓 Non-billable"
    scope = "🌍 Global activity" if act.project is None else f"📁 Project activity (Project ID: {act.project})"
    
    result = f"""Activity #{act.id}: {act.name} {visibility}
{scope}
Number: {act.number or '(none)'}
Status: {billable}
Comment: {act.comment or '(no comment)'}
Color: {act.color or '(default)'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_create_activity(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle creating a new activity."""
    activity_data = {
        "name": arguments["name"]
    }
    
    # Optional fields
    optional_fields = [
        'project', 'comment', 'visible', 'billable', 'budget', 'timeBudget', 
        'color', 'number'
    ]
    
    for field in optional_fields:
        if field in arguments:
            if field == 'timeBudget':
                activity_data['time_budget'] = arguments[field]
            else:
                activity_data[field] = arguments[field]
    
    activity_form = ActivityEditForm(**activity_data)
    activity = await client.create_activity(activity_form)
    
    visibility = "👁️ Visible" if activity.visible else "🚫 Hidden"
    billable = "💰 Billable" if activity.billable else "🆓 Non-billable"
    scope = "🌍 Global activity" if activity.project is None else f"📁 Project activity (Project ID: {activity.project})"
    
    result = f"""Activity created successfully! {visibility}

ID: {activity.id}
Name: {activity.name}
{scope}
Number: {activity.number or '(none)'}
Status: {billable}
Comment: {activity.comment or '(no comment)'}
Color: {activity.color or '(default)'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_update_activity(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle updating an existing activity."""
    activity_id = arguments.pop('id')
    activity_data = {
        "name": arguments["name"]
    }
    
    # Optional fields
    optional_fields = [
        'project', 'comment', 'visible', 'billable', 'budget', 'timeBudget', 
        'color', 'number'
    ]
    
    for field in optional_fields:
        if field in arguments:
            if field == 'timeBudget':
                activity_data['time_budget'] = arguments[field]
            else:
                activity_data[field] = arguments[field]
    
    activity_form = ActivityEditForm(**activity_data)
    activity = await client.update_activity(activity_id, activity_form)
    
    visibility = "👁️ Visible" if activity.visible else "🚫 Hidden"
    billable = "💰 Billable" if activity.billable else "🆓 Non-billable"
    scope = "🌍 Global activity" if activity.project is None else f"📁 Project activity (Project ID: {activity.project})"
    
    result = f"""Activity updated successfully! {visibility}

ID: {activity.id}
Name: {activity.name}
{scope}
Number: {activity.number or '(none)'}
Status: {billable}
Comment: {activity.comment or '(no comment)'}
Color: {activity.color or '(default)'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_delete_activity(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle deleting an activity."""
    activity_id = arguments['id']
    await client.delete_activity(activity_id)
    
    return [TextContent(type="text", text=f"Activity #{activity_id} deleted successfully. WARNING: All linked timesheets have been deleted.")]


async def handle_get_activity_rates(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle getting activity rates."""
    activity_id = arguments['id']
    rates = await client.get_activity_rates(activity_id)
    
    if not rates:
        return [TextContent(type="text", text=f"No rates found for activity #{activity_id}.")]
    
    results = []
    for rate in rates:
        user_info = f" (User: {rate.user.username})" if rate.user else " (Default)"
        fixed_info = " [Fixed Rate]" if rate.is_fixed else ""
        internal_info = f" | Internal: {rate.internal_rate:.2f}" if rate.internal_rate else ""
        
        result = f"""Rate ID: {rate.id}{user_info}{fixed_info}
Amount: {rate.rate:.2f}{internal_info}
---"""
        results.append(result)
    
    summary = f"Found {len(rates)} rate(s) for activity #{activity_id}:\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_add_activity_rate(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle adding an activity rate."""
    activity_id = arguments.pop('id')
    
    rate_data = {"rate": arguments["rate"]}
    
    # Optional fields
    if 'user' in arguments:
        rate_data['user'] = arguments['user']
    if 'internalRate' in arguments:
        rate_data['internal_rate'] = arguments['internalRate']
    if 'isFixed' in arguments:
        rate_data['is_fixed'] = arguments['isFixed']
    
    rate_form = RateForm(**rate_data)
    rate = await client.add_activity_rate(activity_id, rate_form)
    
    user_info = f" for user {rate.user.username}" if rate.user else " (default rate)"
    fixed_info = " [Fixed Rate]" if rate.is_fixed else ""
    internal_info = f" | Internal: {rate.internal_rate:.2f}" if rate.internal_rate else ""
    
    result = f"""Rate added successfully!{fixed_info}

Rate ID: {rate.id}
Activity ID: {activity_id}{user_info}
Amount: {rate.rate:.2f}{internal_info}"""
    
    return [TextContent(type="text", text=result)]


async def handle_delete_activity_rate(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle deleting an activity rate."""
    activity_id = arguments['id']
    rate_id = arguments['rate_id']
    
    await client.delete_activity_rate(activity_id, rate_id)
    
    return [TextContent(type="text", text=f"Rate #{rate_id} deleted successfully from activity #{activity_id}.")]


async def handle_update_activity_meta(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle updating an activity's custom field."""
    activity_id = arguments['id']
    
    meta_field = MetaFieldForm(
        name=arguments['name'],
        value=arguments['value']
    )
    
    activity = await client.update_activity_meta(activity_id, meta_field)
    
    result = f"""Custom field updated successfully!

Activity: {activity.name} (ID: {activity.id})
Field: {arguments['name']} = {arguments['value']}"""
    
    return [TextContent(type="text", text=result)]