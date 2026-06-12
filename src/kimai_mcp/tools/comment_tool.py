"""Consolidated Comment tool for project and customer comments (Kimai 2.57+)."""

from typing import List
from mcp.types import Tool, TextContent
from ..client import KimaiClient
from ..models import CommentForm


def comment_tool() -> Tool:
    """Define the consolidated comment management tool."""
    return Tool(
        name="comment",
        description="""Comment management for projects and customers (requires Kimai 2.57+).

COMMON TASKS:
- List comments: entity="project", entity_id=ID, action=list
- Add comment: entity="customer", entity_id=ID, action=create, data={message:"...", pinned:false}
- Pin/unpin: action=pin, entity_id=ID, comment_id=COMMENT_ID (toggles pinned status)
- Delete: action=delete, entity_id=ID, comment_id=COMMENT_ID

Markdown is supported in comment messages. Pinned comments always appear first.""",
        inputSchema={
            "type": "object",
            "required": ["entity", "entity_id", "action"],
            "properties": {
                "entity": {
                    "type": "string",
                    "enum": ["project", "customer"],
                    "description": "The entity type the comment belongs to"
                },
                "entity_id": {
                    "type": "integer",
                    "description": "The ID of the project or customer"
                },
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "delete", "pin"],
                    "description": "list: all comments; create: add comment; delete: remove comment; pin: toggle pinned status"
                },
                "comment_id": {
                    "type": "integer",
                    "description": "Comment ID (required for delete and pin actions)"
                },
                "data": {
                    "type": "object",
                    "description": "Comment data for create action",
                    "properties": {
                        "message": {"type": "string", "description": "The comment text (markdown supported)"},
                        "pinned": {"type": "boolean", "description": "Pinned comments always appear first", "default": False}
                    },
                    "required": ["message"]
                }
            }
        }
    )


async def handle_comment(client: KimaiClient, **params) -> List[TextContent]:
    """Handle consolidated comment operations."""
    entity = params.get("entity")
    entity_id = params.get("entity_id")
    action = params.get("action")
    comment_id = params.get("comment_id")
    data = params.get("data", {})

    if entity not in ("project", "customer"):
        return [TextContent(
            type="text",
            text=f"Error: Unknown entity type '{entity}'. Valid types: project, customer"
        )]
    if not entity_id:
        return [TextContent(type="text", text="Error: 'entity_id' parameter is required")]

    if action == "list":
        if entity == "project":
            comments = await client.get_project_comments(entity_id)
        else:
            comments = await client.get_customer_comments(entity_id)
        return [TextContent(type="text", text=_format_comment_list(comments, entity, entity_id))]

    elif action == "create":
        if not data.get("message"):
            return [TextContent(type="text", text="Error: 'data.message' is required for create action")]
        form = CommentForm(message=data["message"], pinned=data.get("pinned"))
        if entity == "project":
            comment = await client.create_project_comment(entity_id, form)
        else:
            comment = await client.create_customer_comment(entity_id, form)
        pinned_info = " (pinned)" if comment.pinned else ""
        return [TextContent(
            type="text",
            text=f"Added comment ID {comment.id} to {entity} ID {entity_id}{pinned_info}"
        )]

    elif action == "delete":
        if not comment_id:
            return [TextContent(type="text", text="Error: 'comment_id' parameter is required for delete action")]
        if entity == "project":
            await client.delete_project_comment(entity_id, comment_id)
        else:
            await client.delete_customer_comment(entity_id, comment_id)
        return [TextContent(type="text", text=f"Deleted comment ID {comment_id} from {entity} ID {entity_id}")]

    elif action == "pin":
        if not comment_id:
            return [TextContent(type="text", text="Error: 'comment_id' parameter is required for pin action")]
        if entity == "project":
            comment = await client.pin_project_comment(entity_id, comment_id)
        else:
            comment = await client.pin_customer_comment(entity_id, comment_id)
        status = "pinned" if comment.pinned else "unpinned"
        return [TextContent(type="text", text=f"Comment ID {comment_id} is now {status}")]

    else:
        return [TextContent(
            type="text",
            text=f"Error: Unknown action '{action}'. Valid actions: list, create, delete, pin"
        )]


def _format_comment_list(comments: List, entity: str, entity_id: int) -> str:
    """Format a list of comments for display."""
    if not comments:
        return f"No comments found for {entity} ID {entity_id}"

    result = f"Found {len(comments)} comment(s) for {entity} ID {entity_id}:\n\n"
    for comment in comments:
        pinned = " [PINNED]" if comment.pinned else ""
        result += f"Comment ID: {comment.id}{pinned}\n"
        if comment.created_by:
            result += f"  By: {comment.created_by.username}\n"
        if comment.created_at:
            result += f"  At: {comment.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        result += f"  {comment.message}\n\n"
    return result
