"""Tag management MCP tools."""

from typing import Any, Dict, List, Optional

from mcp.types import Tool, TextContent

from ..client import KimaiClient
from ..models import TagFilter, TagEditForm


# Tool definitions

def list_tags_tool() -> Tool:
    """Define the list tags tool."""
    return Tool(
        name="tag_list",
        description="List all tags with optional name filter",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Filter tags by name (partial match)"}
            }
        }
    )


def create_tag_tool() -> Tool:
    """Define the create tag tool."""
    return Tool(
        name="tag_create",
        description="Create a new tag",
        inputSchema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "description": "Tag name"},
                "color": {"type": "string", "description": "Tag color (hex format)"},
                "visible": {"type": "boolean", "description": "Whether tag is visible", "default": True}
            }
        }
    )


def delete_tag_tool() -> Tool:
    """Define the delete tag tool."""
    return Tool(
        name="tag_delete",
        description="Delete a tag",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Tag ID to delete"}
            }
        }
    )


# Tool handlers

async def handle_list_tags(client: KimaiClient, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
    """Handle listing tags."""
    filters = None
    
    if arguments and 'name' in arguments:
        filters = TagFilter(name=arguments['name'])
    
    tags = await client.get_tags_full(filters)
    
    if not tags:
        search_info = f" matching '{arguments['name']}'" if arguments and 'name' in arguments else ""
        return [TextContent(type="text", text=f"No tags found{search_info}.")]
    
    # Format results
    results = []
    for tag in tags:
        visibility_icon = "👁️" if tag.visible else "🙈"
        color_info = f" ({tag.color})" if tag.color else ""
        
        result = f"""ID: {tag.id} {visibility_icon} 🏷️
Name: {tag.name}{color_info}
Visible: {'Yes' if tag.visible else 'No'}
---"""
        results.append(result)
    
    search_info = f" matching '{arguments['name']}'" if arguments and 'name' in arguments else ""
    summary = f"Found {len(tags)} tag(s){search_info}:\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_create_tag(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle creating a new tag."""
    tag_data = {
        'name': arguments['name']
    }
    
    # Optional fields
    if 'color' in arguments:
        tag_data['color'] = arguments['color']
    if 'visible' in arguments:
        tag_data['visible'] = arguments['visible']
    
    tag_form = TagEditForm(**tag_data)
    tag = await client.create_tag(tag_form)
    
    visibility_icon = "👁️" if tag.visible else "🙈"
    color_info = f" ({tag.color})" if tag.color else ""
    
    result = f"""Tag created successfully! {visibility_icon} 🏷️

ID: {tag.id}
Name: {tag.name}{color_info}
Visible: {'Yes' if tag.visible else 'No'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_delete_tag(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle deleting a tag."""
    tag_id = arguments['id']
    await client.delete_tag(tag_id)
    
    return [TextContent(type="text", text=f"Tag #{tag_id} deleted successfully.")]