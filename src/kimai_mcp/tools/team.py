"""Team management MCP tools."""

from typing import Any, Dict, List, Optional

from mcp.types import Tool, TextContent

from ..client import KimaiClient
from ..models import TeamEditForm


# Tool definitions

def list_teams_tool() -> Tool:
    """Define the list teams tool."""
    return Tool(
        name="team_list",
        description="List all teams",
        inputSchema={
            "type": "object",
            "properties": {}
        }
    )


def get_team_tool() -> Tool:
    """Define the get team tool."""
    return Tool(
        name="team_get",
        description="Get detailed information about a specific team",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Team ID to retrieve"}
            }
        }
    )


def create_team_tool() -> Tool:
    """Define the create team tool."""
    return Tool(
        name="team_create",
        description="Create a new team",
        inputSchema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "description": "Team name"},
                "color": {"type": "string", "description": "Team color (hex format)"},
                "members": {
                    "type": "array",
                    "description": "Initial team members",
                    "items": {
                        "type": "object",
                        "required": ["user"],
                        "properties": {
                            "user": {"type": "integer", "description": "User ID"},
                            "teamlead": {"type": "boolean", "description": "Whether user is team lead", "default": False}
                        }
                    }
                }
            }
        }
    )


def update_team_tool() -> Tool:
    """Define the update team tool."""
    return Tool(
        name="team_update",
        description="Update an existing team",
        inputSchema={
            "type": "object",
            "required": ["id", "name"],
            "properties": {
                "id": {"type": "integer", "description": "Team ID to update"},
                "name": {"type": "string", "description": "Team name"},
                "color": {"type": "string", "description": "Team color (hex format)"},
                "members": {
                    "type": "array",
                    "description": "Team members (replaces existing)",
                    "items": {
                        "type": "object",
                        "required": ["user"],
                        "properties": {
                            "user": {"type": "integer", "description": "User ID"},
                            "teamlead": {"type": "boolean", "description": "Whether user is team lead", "default": False}
                        }
                    }
                }
            }
        }
    )


def delete_team_tool() -> Tool:
    """Define the delete team tool."""
    return Tool(
        name="team_delete",
        description="Delete a team",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Team ID to delete"}
            }
        }
    )


def add_team_member_tool() -> Tool:
    """Define the add team member tool."""
    return Tool(
        name="team_add_member",
        description="Add a member to a team",
        inputSchema={
            "type": "object",
            "required": ["team_id", "user_id"],
            "properties": {
                "team_id": {"type": "integer", "description": "Team ID"},
                "user_id": {"type": "integer", "description": "User ID to add"}
            }
        }
    )


def remove_team_member_tool() -> Tool:
    """Define the remove team member tool."""
    return Tool(
        name="team_remove_member",
        description="Remove a member from a team",
        inputSchema={
            "type": "object",
            "required": ["team_id", "user_id"],
            "properties": {
                "team_id": {"type": "integer", "description": "Team ID"},
                "user_id": {"type": "integer", "description": "User ID to remove"}
            }
        }
    )


def grant_team_customer_access_tool() -> Tool:
    """Define the grant team customer access tool."""
    return Tool(
        name="team_grant_customer_access",
        description="Grant team access to a customer",
        inputSchema={
            "type": "object",
            "required": ["team_id", "customer_id"],
            "properties": {
                "team_id": {"type": "integer", "description": "Team ID"},
                "customer_id": {"type": "integer", "description": "Customer ID to grant access to"}
            }
        }
    )


def revoke_team_customer_access_tool() -> Tool:
    """Define the revoke team customer access tool."""
    return Tool(
        name="team_revoke_customer_access",
        description="Revoke team access to a customer",
        inputSchema={
            "type": "object",
            "required": ["team_id", "customer_id"],
            "properties": {
                "team_id": {"type": "integer", "description": "Team ID"},
                "customer_id": {"type": "integer", "description": "Customer ID to revoke access from"}
            }
        }
    )


def grant_team_project_access_tool() -> Tool:
    """Define the grant team project access tool."""
    return Tool(
        name="team_grant_project_access",
        description="Grant team access to a project",
        inputSchema={
            "type": "object",
            "required": ["team_id", "project_id"],
            "properties": {
                "team_id": {"type": "integer", "description": "Team ID"},
                "project_id": {"type": "integer", "description": "Project ID to grant access to"}
            }
        }
    )


def revoke_team_project_access_tool() -> Tool:
    """Define the revoke team project access tool."""
    return Tool(
        name="team_revoke_project_access",
        description="Revoke team access to a project",
        inputSchema={
            "type": "object",
            "required": ["team_id", "project_id"],
            "properties": {
                "team_id": {"type": "integer", "description": "Team ID"},
                "project_id": {"type": "integer", "description": "Project ID to revoke access from"}
            }
        }
    )


def grant_team_activity_access_tool() -> Tool:
    """Define the grant team activity access tool."""
    return Tool(
        name="team_grant_activity_access",
        description="Grant team access to an activity",
        inputSchema={
            "type": "object",
            "required": ["team_id", "activity_id"],
            "properties": {
                "team_id": {"type": "integer", "description": "Team ID"},
                "activity_id": {"type": "integer", "description": "Activity ID to grant access to"}
            }
        }
    )


def revoke_team_activity_access_tool() -> Tool:
    """Define the revoke team activity access tool."""
    return Tool(
        name="team_revoke_activity_access",
        description="Revoke team access to an activity",
        inputSchema={
            "type": "object",
            "required": ["team_id", "activity_id"],
            "properties": {
                "team_id": {"type": "integer", "description": "Team ID"},
                "activity_id": {"type": "integer", "description": "Activity ID to revoke access from"}
            }
        }
    )


# Tool handlers

async def handle_list_teams(client: KimaiClient) -> List[TextContent]:
    """Handle listing teams."""
    teams = await client.get_teams()
    
    if not teams:
        return [TextContent(type="text", text="No teams found.")]
    
    # Format results
    results = []
    for team in teams:
        member_count = len(team.members)
        leads = [member.user.username for member in team.members if member.teamlead]
        lead_info = f" (Leads: {', '.join(leads)})" if leads else ""
        
        customer_count = len(team.customers)
        project_count = len(team.projects)
        activity_count = len(team.activities)
        
        result = f"""ID: {team.id} 👥
Name: {team.name}
Color: {team.color or 'Default'}
Members: {member_count}{lead_info}
Access: {customer_count} customers, {project_count} projects, {activity_count} activities
---"""
        results.append(result)
    
    summary = f"Found {len(teams)} team(s):\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_get_team(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle getting a specific team."""
    team_id = arguments['id']
    team = await client.get_team(team_id)
    
    # Format members
    member_details = []
    for member in team.members:
        role = " (Team Lead)" if member.teamlead else ""
        member_details.append(f"  • {member.user.username} (ID: {member.user.id}){role}")
    
    members_info = "\n".join(member_details) if member_details else "  No members"
    
    # Format access permissions
    customers_info = ", ".join([f"{c.name} (ID: {c.id})" for c in team.customers]) if team.customers else "None"
    projects_info = ", ".join([f"{p.name} (ID: {p.id})" for p in team.projects]) if team.projects else "None"
    activities_info = ", ".join([f"{a.name} (ID: {a.id})" for a in team.activities]) if team.activities else "None"
    
    result = f"""Team Details 👥

ID: {team.id}
Name: {team.name}
Color: {team.color or 'Default'}

Members:
{members_info}

Access Permissions:
Customers: {customers_info}
Projects: {projects_info}
Activities: {activities_info}"""
    
    return [TextContent(type="text", text=result)]


async def handle_create_team(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle creating a new team."""
    team_data = {
        'name': arguments['name'],
        'members': arguments.get('members', [])
    }
    
    if 'color' in arguments:
        team_data['color'] = arguments['color']
    
    team_form = TeamEditForm(**team_data)
    team = await client.create_team(team_form)
    
    member_count = len(team.members)
    leads = [member.user.username for member in team.members if member.teamlead]
    lead_info = f" (Leads: {', '.join(leads)})" if leads else ""
    
    result = f"""Team created successfully! 👥

ID: {team.id}
Name: {team.name}
Color: {team.color or 'Default'}
Members: {member_count}{lead_info}"""
    
    return [TextContent(type="text", text=result)]


async def handle_update_team(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle updating an existing team."""
    team_id = arguments.pop('id')
    
    team_data = {
        'name': arguments['name'],
        'members': arguments.get('members', [])
    }
    
    if 'color' in arguments:
        team_data['color'] = arguments['color']
    
    team_form = TeamEditForm(**team_data)
    team = await client.update_team(team_id, team_form)
    
    member_count = len(team.members)
    leads = [member.user.username for member in team.members if member.teamlead]
    lead_info = f" (Leads: {', '.join(leads)})" if leads else ""
    
    result = f"""Team updated successfully! 👥

ID: {team.id}
Name: {team.name}
Color: {team.color or 'Default'}
Members: {member_count}{lead_info}"""
    
    return [TextContent(type="text", text=result)]


async def handle_delete_team(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle deleting a team."""
    team_id = arguments['id']
    await client.delete_team(team_id)
    
    return [TextContent(type="text", text=f"Team #{team_id} deleted successfully.")]


async def handle_add_team_member(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle adding a member to a team."""
    team_id = arguments['team_id']
    user_id = arguments['user_id']
    
    team = await client.add_team_member(team_id, user_id)
    
    # Find the added user
    added_member = next((m for m in team.members if m.user.id == user_id), None)
    username = added_member.user.username if added_member else f"User #{user_id}"
    
    result = f"""Member added successfully! 👥

Team: {team.name} (ID: {team.id})
Added: {username} (ID: {user_id})
Total members: {len(team.members)}"""
    
    return [TextContent(type="text", text=result)]


async def handle_remove_team_member(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle removing a member from a team."""
    team_id = arguments['team_id']
    user_id = arguments['user_id']
    
    team = await client.remove_team_member(team_id, user_id)
    
    result = f"""Member removed successfully! 👥

Team: {team.name} (ID: {team.id})
Removed: User #{user_id}
Remaining members: {len(team.members)}"""
    
    return [TextContent(type="text", text=result)]


async def handle_grant_team_customer_access(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle granting team access to a customer."""
    team_id = arguments['team_id']
    customer_id = arguments['customer_id']
    
    team = await client.grant_team_customer_access(team_id, customer_id)
    
    result = f"""Customer access granted successfully!
    
Team: {team.name} (ID: {team.id})
Customer ID: {customer_id}
Access: Granted"""
    
    return [TextContent(type="text", text=result)]


async def handle_revoke_team_customer_access(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle revoking team access to a customer."""
    team_id = arguments['team_id']
    customer_id = arguments['customer_id']
    
    team = await client.revoke_team_customer_access(team_id, customer_id)
    
    result = f"""Customer access revoked successfully!
    
Team: {team.name} (ID: {team.id})
Customer ID: {customer_id}
Access: Revoked"""
    
    return [TextContent(type="text", text=result)]


async def handle_grant_team_project_access(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle granting team access to a project."""
    team_id = arguments['team_id']
    project_id = arguments['project_id']
    
    team = await client.grant_team_project_access(team_id, project_id)
    
    result = f"""Project access granted successfully!
    
Team: {team.name} (ID: {team.id})
Project ID: {project_id}
Access: Granted"""
    
    return [TextContent(type="text", text=result)]


async def handle_revoke_team_project_access(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle revoking team access to a project."""
    team_id = arguments['team_id']
    project_id = arguments['project_id']
    
    team = await client.revoke_team_project_access(team_id, project_id)
    
    result = f"""Project access revoked successfully!
    
Team: {team.name} (ID: {team.id})
Project ID: {project_id}
Access: Revoked"""
    
    return [TextContent(type="text", text=result)]


async def handle_grant_team_activity_access(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle granting team access to an activity."""
    team_id = arguments['team_id']
    activity_id = arguments['activity_id']
    
    team = await client.grant_team_activity_access(team_id, activity_id)
    
    result = f"""Activity access granted successfully!
    
Team: {team.name} (ID: {team.id})
Activity ID: {activity_id}
Access: Granted"""
    
    return [TextContent(type="text", text=result)]


async def handle_revoke_team_activity_access(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle revoking team access to an activity."""
    team_id = arguments['team_id']
    activity_id = arguments['activity_id']
    
    team = await client.revoke_team_activity_access(team_id, activity_id)
    
    result = f"""Activity access revoked successfully!
    
Team: {team.name} (ID: {team.id})
Activity ID: {activity_id}
Access: Revoked"""
    
    return [TextContent(type="text", text=result)]