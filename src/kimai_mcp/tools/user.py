"""User management MCP tools."""

from typing import Any, Dict, List, Optional

from mcp.types import Tool, TextContent

from ..client import KimaiClient
from ..models import UserFilter, UserCreateForm, UserEditForm


# Tool definitions

def list_users_tool() -> Tool:
    """Define the list users tool."""
    return Tool(
        name="user_list",
        description="List users with optional filters",
        inputSchema={
            "type": "object",
            "properties": {
                "visible": {"type": "integer", "enum": [1, 2, 3], "description": "Visibility filter: 1=visible, 2=hidden, 3=all"},
                "term": {"type": "string", "description": "Search term for username/email"},
                "order_by": {"type": "string", "enum": ["id", "username", "alias", "email"], "description": "Sort field"},
                "order": {"type": "string", "enum": ["ASC", "DESC"], "description": "Sort order"},
                "full": {"type": "string", "enum": ["0", "1", "false", "true"], "description": "Include full user details"}
            }
        }
    )


def get_user_tool() -> Tool:
    """Define the get user tool."""
    return Tool(
        name="user_get",
        description="Get detailed information about a specific user",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "User ID to retrieve"}
            }
        }
    )


def get_current_user_tool() -> Tool:
    """Define the get current user tool."""
    return Tool(
        name="user_current",
        description="Get information about the currently authenticated user",
        inputSchema={
            "type": "object",
            "properties": {}
        }
    )


def create_user_tool() -> Tool:
    """Define the create user tool."""
    return Tool(
        name="user_create",
        description="Create a new user account",
        inputSchema={
            "type": "object",
            "required": ["username", "email", "language", "locale", "timezone", "plainPassword"],
            "properties": {
                "username": {"type": "string", "description": "Unique username"},
                "email": {"type": "string", "format": "email", "description": "User email address"},
                "alias": {"type": "string", "description": "Display name/alias"},
                "title": {"type": "string", "description": "Job title or role"},
                "accountNumber": {"type": "string", "description": "Account number for invoicing"},
                "color": {"type": "string", "description": "Color code for user (hex format)"},
                "language": {"type": "string", "description": "Language code (e.g., 'en', 'de')"},
                "locale": {"type": "string", "description": "Locale code (e.g., 'en_US', 'de_DE')"},
                "timezone": {"type": "string", "description": "Timezone (e.g., 'Europe/Berlin')"},
                "supervisor": {"type": "integer", "description": "Supervisor user ID"},
                "roles": {"type": "array", "items": {"type": "string"}, "description": "User roles"},
                "plainPassword": {"type": "string", "description": "Plain text password"},
                "plainApiToken": {"type": "string", "description": "Optional API token"},
                "enabled": {"type": "boolean", "description": "Whether user is enabled"},
                "systemAccount": {"type": "boolean", "description": "Whether this is a system account"},
                "requiresPasswordReset": {"type": "boolean", "description": "Force password reset on next login"}
            }
        }
    )


def update_user_tool() -> Tool:
    """Define the update user tool."""
    return Tool(
        name="user_update",
        description="Update an existing user account",
        inputSchema={
            "type": "object",
            "required": ["id", "email", "language", "locale", "timezone"],
            "properties": {
                "id": {"type": "integer", "description": "User ID to update"},
                "email": {"type": "string", "format": "email", "description": "User email address"},
                "alias": {"type": "string", "description": "Display name/alias"},
                "title": {"type": "string", "description": "Job title or role"},
                "accountNumber": {"type": "string", "description": "Account number for invoicing"},
                "color": {"type": "string", "description": "Color code for user (hex format)"},
                "language": {"type": "string", "description": "Language code (e.g., 'en', 'de')"},
                "locale": {"type": "string", "description": "Locale code (e.g., 'en_US', 'de_DE')"},
                "timezone": {"type": "string", "description": "Timezone (e.g., 'Europe/Berlin')"},
                "supervisor": {"type": "integer", "description": "Supervisor user ID"},
                "roles": {"type": "array", "items": {"type": "string"}, "description": "User roles"},
                "enabled": {"type": "boolean", "description": "Whether user is enabled"},
                "systemAccount": {"type": "boolean", "description": "Whether this is a system account"},
                "requiresPasswordReset": {"type": "boolean", "description": "Force password reset on next login"}
            }
        }
    )


# Tool handlers

async def handle_list_users(client: KimaiClient, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
    """Handle listing users."""
    filters = UserFilter()
    
    if arguments:
        if 'visible' in arguments:
            filters.visible = arguments['visible']
        if 'term' in arguments:
            filters.term = arguments['term']
        if 'order_by' in arguments:
            filters.order_by = arguments['order_by']
        if 'order' in arguments:
            filters.order = arguments['order']
        if 'full' in arguments:
            filters.full = arguments['full']
    
    users = await client.get_users_extended(filters)
    
    if not users:
        return [TextContent(type="text", text="No users found matching the criteria.")]
    
    # Format results
    results = []
    for user in users:
        status_icon = "✅" if user.enabled else "❌"
        supervisor_info = f"\nSupervisor: {user.supervisor.username}" if user.supervisor else ""
        roles_info = f"\nRoles: {', '.join(user.roles)}" if user.roles else ""
        teams_info = f"\nTeams: {', '.join([team.name for team in user.teams])}" if user.teams else ""
        
        result = f"""ID: {user.id} {status_icon}
Username: {user.username}
Email: {getattr(user, 'email', 'N/A')}
Alias: {user.alias or 'None'}
Title: {user.title or 'None'}
Language: {user.language or 'N/A'}
Timezone: {user.timezone or 'N/A'}{supervisor_info}{roles_info}{teams_info}
---"""
        results.append(result)
    
    summary = f"Found {len(users)} user(s):\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_get_user(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle getting a specific user."""
    user_id = arguments['id']
    user = await client.get_user_extended(user_id)
    
    status_icon = "✅" if user.enabled else "❌"
    supervisor_info = f"Supervisor: {user.supervisor.username} (ID: {user.supervisor.id})" if user.supervisor else "No supervisor"
    roles_info = f"Roles: {', '.join(user.roles)}" if user.roles else "No roles assigned"
    teams_info = f"Teams: {', '.join([f'{team.name} (ID: {team.id})' for team in user.teams])}" if user.teams else "No teams"
    
    result = f"""User Details {status_icon}

ID: {user.id}
Username: {user.username}
Email: {getattr(user, 'email', 'N/A')}
Alias: {user.alias or 'None'}
Title: {user.title or 'None'}
Color: {user.color or 'Default'}
Language: {user.language or 'N/A'}
Locale: {user.locale or 'N/A'}
Timezone: {user.timezone or 'N/A'}
Avatar: {user.avatar or 'None'}

{supervisor_info}
{roles_info}
{teams_info}

Status: {'Enabled' if user.enabled else 'Disabled'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_get_current_user(client: KimaiClient) -> List[TextContent]:
    """Handle getting current user information."""
    user = await client.get_current_user()
    
    status_icon = "✅" if user.enabled else "❌"
    
    result = f"""Current User {status_icon}

ID: {user.id}
Username: {user.username}
Alias: {user.alias or 'None'}
Title: {user.title or 'None'}
Color: {user.color or 'Default'}

Status: {'Enabled' if user.enabled else 'Disabled'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_create_user(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle creating a new user."""
    user_data = {
        'username': arguments['username'],
        'email': arguments['email'],
        'language': arguments['language'],
        'locale': arguments['locale'],
        'timezone': arguments['timezone'],
        'plain_password': arguments['plainPassword']
    }
    
    # Optional fields
    optional_fields = [
        'alias', 'title', 'accountNumber', 'color', 'supervisor', 
        'roles', 'plainApiToken', 'enabled', 'systemAccount', 'requiresPasswordReset'
    ]
    
    for field in optional_fields:
        if field in arguments:
            if field == 'accountNumber':
                user_data['account_number'] = arguments[field]
            elif field == 'plainApiToken':
                user_data['plain_api_token'] = arguments[field]
            elif field == 'systemAccount':
                user_data['system_account'] = arguments[field]
            elif field == 'requiresPasswordReset':
                user_data['requires_password_reset'] = arguments[field]
            else:
                user_data[field] = arguments[field]
    
    user_form = UserCreateForm(**user_data)
    user = await client.create_user(user_form)
    
    status_icon = "✅" if user.enabled else "❌"
    roles_info = f"\nRoles: {', '.join(user.roles)}" if user.roles else ""
    
    result = f"""User created successfully! {status_icon}

ID: {user.id}
Username: {user.username}
Email: {getattr(user, 'email', arguments['email'])}
Alias: {user.alias or 'None'}
Title: {user.title or 'None'}
Language: {user.language}
Timezone: {user.timezone}
Status: {'Enabled' if user.enabled else 'Disabled'}{roles_info}"""
    
    return [TextContent(type="text", text=result)]


async def handle_update_user(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle updating an existing user."""
    user_id = arguments.pop('id')
    
    user_data = {
        'email': arguments['email'],
        'language': arguments['language'],
        'locale': arguments['locale'],
        'timezone': arguments['timezone']
    }
    
    # Optional fields
    optional_fields = [
        'alias', 'title', 'accountNumber', 'color', 'supervisor', 
        'roles', 'enabled', 'systemAccount', 'requiresPasswordReset'
    ]
    
    for field in optional_fields:
        if field in arguments:
            if field == 'accountNumber':
                user_data['account_number'] = arguments[field]
            elif field == 'systemAccount':
                user_data['system_account'] = arguments[field]
            elif field == 'requiresPasswordReset':
                user_data['requires_password_reset'] = arguments[field]
            else:
                user_data[field] = arguments[field]
    
    user_form = UserEditForm(**user_data)
    user = await client.update_user(user_id, user_form)
    
    status_icon = "✅" if user.enabled else "❌"
    roles_info = f"\nRoles: {', '.join(user.roles)}" if user.roles else ""
    
    result = f"""User updated successfully! {status_icon}

ID: {user.id}
Username: {user.username}
Email: {getattr(user, 'email', user_data['email'])}
Alias: {user.alias or 'None'}
Title: {user.title or 'None'}
Language: {user.language}
Timezone: {user.timezone}
Status: {'Enabled' if user.enabled else 'Disabled'}{roles_info}"""
    
    return [TextContent(type="text", text=result)]