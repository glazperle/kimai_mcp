"""Project-related MCP tools."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from mcp.types import Tool, TextContent

from ..client import KimaiClient
from ..models import ProjectFilter, ProjectEditForm, RateForm, MetaFieldForm


# Tool definitions

def list_projects_tool() -> Tool:
    """Define the list projects tool."""
    return Tool(
        name="project_list",
        description="List projects with optional filters",
        inputSchema={
            "type": "object",
            "properties": {
                "customer": {"type": "integer", "description": "Customer ID filter"},
                "visible": {"type": "integer", "enum": [1, 2, 3], "description": "Visibility: 1=visible, 2=hidden, 3=both"},
                "start": {"type": "string", "format": "date-time", "description": "Projects starting before this date (ISO format)"},
                "end": {"type": "string", "format": "date-time", "description": "Projects ending after this date (ISO format)"},
                "ignoreDates": {"type": "string", "description": "Set to '1' to ignore date filters"},
                "globalActivities": {"type": "string", "enum": ["0", "1"], "description": "Filter by global activities support"},
                "order": {"type": "string", "enum": ["ASC", "DESC"], "description": "Sort order"},
                "orderBy": {"type": "string", "enum": ["id", "name", "customer"], "description": "Sort field"},
                "term": {"type": "string", "description": "Search term"}
            }
        }
    )


def get_project_tool() -> Tool:
    """Define the get project tool."""
    return Tool(
        name="project_get",
        description="Get detailed information about a specific project",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Project ID"}
            }
        }
    )


def create_project_tool() -> Tool:
    """Define the create project tool."""
    return Tool(
        name="project_create",
        description="Create a new project",
        inputSchema={
            "type": "object",
            "required": ["name", "customer"],
            "properties": {
                "name": {"type": "string", "description": "Project name"},
                "customer": {"type": "integer", "description": "Customer ID"},
                "comment": {"type": "string", "description": "Project comment"},
                "visible": {"type": "boolean", "description": "Whether project is visible"},
                "billable": {"type": "boolean", "description": "Whether project is billable"},
                "budget": {"type": "number", "description": "Project budget"},
                "timeBudget": {"type": "integer", "description": "Time budget in seconds"},
                "color": {"type": "string", "description": "Project color (hex format)"},
                "globalActivities": {"type": "boolean", "description": "Whether to enable global activities"},
                "number": {"type": "string", "description": "Project number"},
                "orderNumber": {"type": "string", "description": "Order number"},
                "start": {"type": "string", "format": "date-time", "description": "Project start date (ISO format)"},
                "end": {"type": "string", "format": "date-time", "description": "Project end date (ISO format)"}
            }
        }
    )


def update_project_tool() -> Tool:
    """Define the update project tool."""
    return Tool(
        name="project_update",
        description="Update an existing project",
        inputSchema={
            "type": "object",
            "required": ["id", "name", "customer"],
            "properties": {
                "id": {"type": "integer", "description": "Project ID to update"},
                "name": {"type": "string", "description": "Project name"},
                "customer": {"type": "integer", "description": "Customer ID"},
                "comment": {"type": "string", "description": "Project comment"},
                "visible": {"type": "boolean", "description": "Whether project is visible"},
                "billable": {"type": "boolean", "description": "Whether project is billable"},
                "budget": {"type": "number", "description": "Project budget"},
                "timeBudget": {"type": "integer", "description": "Time budget in seconds"},
                "color": {"type": "string", "description": "Project color (hex format)"},
                "globalActivities": {"type": "boolean", "description": "Whether to enable global activities"},
                "number": {"type": "string", "description": "Project number"},
                "orderNumber": {"type": "string", "description": "Order number"},
                "start": {"type": "string", "format": "date-time", "description": "Project start date (ISO format)"},
                "end": {"type": "string", "format": "date-time", "description": "Project end date (ISO format)"}
            }
        }
    )


def delete_project_tool() -> Tool:
    """Define the delete project tool."""
    return Tool(
        name="project_delete",
        description="Delete a project (WARNING: Deletes ALL linked activities and timesheets)",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Project ID to delete"}
            }
        }
    )


def get_project_rates_tool() -> Tool:
    """Define the get project rates tool."""
    return Tool(
        name="project_rates_list",
        description="Get rates for a project",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Project ID"}
            }
        }
    )


def add_project_rate_tool() -> Tool:
    """Define the add project rate tool."""
    return Tool(
        name="project_rate_add",
        description="Add a rate for a project",
        inputSchema={
            "type": "object",
            "required": ["id", "rate"],
            "properties": {
                "id": {"type": "integer", "description": "Project ID"},
                "user": {"type": "integer", "description": "User ID (optional, for user-specific rates)"},
                "rate": {"type": "number", "description": "Rate amount"},
                "internalRate": {"type": "number", "description": "Internal rate amount"},
                "isFixed": {"type": "boolean", "description": "Whether this is a fixed rate"}
            }
        }
    )


def delete_project_rate_tool() -> Tool:
    """Define the delete project rate tool."""
    return Tool(
        name="project_rate_delete",
        description="Delete a rate for a project",
        inputSchema={
            "type": "object",
            "required": ["id", "rate_id"],
            "properties": {
                "id": {"type": "integer", "description": "Project ID"},
                "rate_id": {"type": "integer", "description": "Rate ID to delete"}
            }
        }
    )


def update_project_meta_tool() -> Tool:
    """Define the update project meta field tool."""
    return Tool(
        name="project_meta_update",
        description="Update a project's custom field",
        inputSchema={
            "type": "object",
            "required": ["id", "name", "value"],
            "properties": {
                "id": {"type": "integer", "description": "Project ID"},
                "name": {"type": "string", "description": "Custom field name"},
                "value": {"type": "string", "description": "Custom field value"}
            }
        }
    )


# Tool handlers

async def handle_list_projects(client: KimaiClient, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
    """Handle listing projects."""
    filters = ProjectFilter()
    
    if arguments:
        # Parse filters
        if 'customer' in arguments:
            filters.customer = arguments['customer']
        if 'visible' in arguments:
            filters.visible = arguments['visible']
        if 'start' in arguments:
            filters.start = datetime.fromisoformat(arguments['start'].replace('Z', '+00:00'))
        if 'end' in arguments:
            filters.end = datetime.fromisoformat(arguments['end'].replace('Z', '+00:00'))
        if 'ignoreDates' in arguments:
            filters.ignore_dates = arguments['ignoreDates']
        if 'globalActivities' in arguments:
            filters.global_activities = arguments['globalActivities']
        if 'order' in arguments:
            filters.order = arguments['order']
        if 'orderBy' in arguments:
            filters.order_by = arguments['orderBy']
        if 'term' in arguments:
            filters.term = arguments['term']
    
    projects = await client.get_projects(filters)
    
    if not projects:
        return [TextContent(type="text", text="No projects found matching the criteria.")]
    
    # Format results
    results = []
    for proj in projects:
        visibility = "👁️ Visible" if proj.visible else "🚫 Hidden"
        billable = "💰 Billable" if proj.billable else "🆓 Non-billable"
        global_acts = "🌍 Global activities" if proj.global_activities else "📁 Project activities only"
        
        result = f"""ID: {proj.id} - {proj.name} {visibility}
Customer ID: {proj.customer}
Number: {proj.number or '(none)'}
{billable} | {global_acts}
Comment: {proj.comment or '(no comment)'}
Color: {proj.color or '(default)'}
---"""
        results.append(result)
    
    summary = f"Found {len(projects)} project(s):\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_get_project(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle getting a specific project."""
    project_id = arguments['id']
    proj = await client.get_project(project_id)
    
    visibility = "👁️ Visible" if proj.visible else "🚫 Hidden"
    billable = "💰 Billable" if proj.billable else "🆓 Non-billable"
    global_acts = "🌍 Global activities enabled" if proj.global_activities else "📁 Project activities only"
    
    result = f"""Project #{proj.id}: {proj.name} {visibility}
Customer ID: {proj.customer}
Number: {proj.number or '(none)'}
Status: {billable} | {global_acts}
Comment: {proj.comment or '(no comment)'}
Color: {proj.color or '(default)'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_create_project(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle creating a new project."""
    project_data = {
        "name": arguments["name"],
        "customer": arguments["customer"]
    }
    
    # Optional fields
    optional_fields = [
        'comment', 'visible', 'billable', 'budget', 'timeBudget', 
        'color', 'globalActivities', 'number', 'orderNumber', 'start', 'end'
    ]
    
    for field in optional_fields:
        if field in arguments:
            if field == 'timeBudget':
                project_data['time_budget'] = arguments[field]
            elif field == 'globalActivities':
                project_data['global_activities'] = arguments[field]
            elif field == 'orderNumber':
                project_data['order_number'] = arguments[field]
            elif field in ['start', 'end']:
                project_data[field] = datetime.fromisoformat(arguments[field].replace('Z', '+00:00'))
            else:
                project_data[field] = arguments[field]
    
    project_form = ProjectEditForm(**project_data)
    project = await client.create_project(project_form)
    
    visibility = "👁️ Visible" if project.visible else "🚫 Hidden"
    billable = "💰 Billable" if project.billable else "🆓 Non-billable"
    
    result = f"""Project created successfully! {visibility}

ID: {project.id}
Name: {project.name}
Customer ID: {project.customer}
Number: {project.number or '(none)'}
Status: {billable}
Comment: {project.comment or '(no comment)'}
Color: {project.color or '(default)'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_update_project(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle updating an existing project."""
    project_id = arguments.pop('id')
    project_data = {
        "name": arguments["name"],
        "customer": arguments["customer"]
    }
    
    # Optional fields
    optional_fields = [
        'comment', 'visible', 'billable', 'budget', 'timeBudget', 
        'color', 'globalActivities', 'number', 'orderNumber', 'start', 'end'
    ]
    
    for field in optional_fields:
        if field in arguments:
            if field == 'timeBudget':
                project_data['time_budget'] = arguments[field]
            elif field == 'globalActivities':
                project_data['global_activities'] = arguments[field]
            elif field == 'orderNumber':
                project_data['order_number'] = arguments[field]
            elif field in ['start', 'end']:
                project_data[field] = datetime.fromisoformat(arguments[field].replace('Z', '+00:00'))
            else:
                project_data[field] = arguments[field]
    
    project_form = ProjectEditForm(**project_data)
    project = await client.update_project(project_id, project_form)
    
    visibility = "👁️ Visible" if project.visible else "🚫 Hidden"
    billable = "💰 Billable" if project.billable else "🆓 Non-billable"
    
    result = f"""Project updated successfully! {visibility}

ID: {project.id}
Name: {project.name}
Customer ID: {project.customer}
Number: {project.number or '(none)'}
Status: {billable}
Comment: {project.comment or '(no comment)'}
Color: {project.color or '(default)'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_delete_project(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle deleting a project."""
    project_id = arguments['id']
    await client.delete_project(project_id)
    
    return [TextContent(type="text", text=f"Project #{project_id} deleted successfully. WARNING: All linked activities and timesheets have been deleted.")]


async def handle_get_project_rates(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle getting project rates."""
    project_id = arguments['id']
    rates = await client.get_project_rates(project_id)
    
    if not rates:
        return [TextContent(type="text", text=f"No rates found for project #{project_id}.")]
    
    results = []
    for rate in rates:
        user_info = f" (User: {rate.user.username})" if rate.user else " (Default)"
        fixed_info = " [Fixed Rate]" if rate.is_fixed else ""
        internal_info = f" | Internal: {rate.internal_rate:.2f}" if rate.internal_rate else ""
        
        result = f"""Rate ID: {rate.id}{user_info}{fixed_info}
Amount: {rate.rate:.2f}{internal_info}
---"""
        results.append(result)
    
    summary = f"Found {len(rates)} rate(s) for project #{project_id}:\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_add_project_rate(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle adding a project rate."""
    project_id = arguments.pop('id')
    
    rate_data = {"rate": arguments["rate"]}
    
    # Optional fields
    if 'user' in arguments:
        rate_data['user'] = arguments['user']
    if 'internalRate' in arguments:
        rate_data['internal_rate'] = arguments['internalRate']
    if 'isFixed' in arguments:
        rate_data['is_fixed'] = arguments['isFixed']
    
    rate_form = RateForm(**rate_data)
    rate = await client.add_project_rate(project_id, rate_form)
    
    user_info = f" for user {rate.user.username}" if rate.user else " (default rate)"
    fixed_info = " [Fixed Rate]" if rate.is_fixed else ""
    internal_info = f" | Internal: {rate.internal_rate:.2f}" if rate.internal_rate else ""
    
    result = f"""Rate added successfully!{fixed_info}

Rate ID: {rate.id}
Project ID: {project_id}{user_info}
Amount: {rate.rate:.2f}{internal_info}"""
    
    return [TextContent(type="text", text=result)]


async def handle_delete_project_rate(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle deleting a project rate."""
    project_id = arguments['id']
    rate_id = arguments['rate_id']
    
    await client.delete_project_rate(project_id, rate_id)
    
    return [TextContent(type="text", text=f"Rate #{rate_id} deleted successfully from project #{project_id}.")]


async def handle_update_project_meta(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle updating a project's custom field."""
    project_id = arguments['id']
    
    meta_field = MetaFieldForm(
        name=arguments['name'],
        value=arguments['value']
    )
    
    project = await client.update_project_meta(project_id, meta_field)
    
    result = f"""Custom field updated successfully!

Project: {project.name} (ID: {project.id})
Field: {arguments['name']} = {arguments['value']}"""
    
    return [TextContent(type="text", text=result)]