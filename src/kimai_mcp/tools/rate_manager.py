"""Consolidated Rate Manager tool for all rate operations."""

from typing import List, Dict
from mcp.types import Tool, TextContent
from ..client import KimaiClient
from ..models import RateForm


def rate_tool() -> Tool:
    """Define the consolidated rate management tool."""
    return Tool(
        name="rate",
        description="Universal rate management tool for customer, project, and activity rates.",
        inputSchema={
            "type": "object",
            "required": ["entity", "entity_id", "action"],
            "properties": {
                "entity": {
                    "type": "string",
                    "enum": ["customer", "project", "activity"],
                    "description": "The entity type to manage rates for"
                },
                "entity_id": {
                    "type": "integer",
                    "description": "The ID of the entity (customer, project, or activity)"
                },
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "delete"],
                    "description": "The action to perform"
                },
                "rate_id": {
                    "type": "integer",
                    "description": "Rate ID (required for delete action)"
                },
                "data": {
                    "type": "object",
                    "description": "Rate data for add action",
                    "properties": {
                        "user": {"type": "integer", "description": "User ID for the rate"},
                        "rate": {"type": "number", "description": "The rate value"},
                        "internal_rate": {"type": "number", "description": "The internal rate value"},
                        "is_fixed": {"type": "boolean", "description": "Whether this is a fixed rate"}
                    }
                }
            }
        }
    )


async def handle_rate(client: KimaiClient, **params) -> List[TextContent]:
    """Handle consolidated rate operations."""
    entity = params.get("entity")
    entity_id = params.get("entity_id")
    action = params.get("action")
    rate_id = params.get("rate_id")
    data = params.get("data", {})
    
    if not entity_id:
        return [TextContent(type="text", text="Error: 'entity_id' parameter is required")]
    
    # Route to appropriate handler
    handlers = {
        "customer": CustomerRateHandler(client),
        "project": ProjectRateHandler(client),
        "activity": ActivityRateHandler(client)
    }
    
    handler = handlers.get(entity)
    if not handler:
        return [TextContent(
            type="text",
            text=f"Error: Unknown entity type '{entity}'. Valid types: customer, project, activity"
        )]
    
    # Execute action
    try:
        if action == "list":
            return await handler.list(entity_id)
        elif action == "add":
            if not data:
                return [TextContent(type="text", text="Error: 'data' parameter is required for add action")]
            return await handler.add(entity_id, data)
        elif action == "delete":
            if not rate_id:
                return [TextContent(type="text", text="Error: 'rate_id' parameter is required for delete action")]
            return await handler.delete(entity_id, rate_id)
        else:
            return [TextContent(
                type="text",
                text=f"Error: Unknown action '{action}'. Valid actions: list, add, delete"
            )]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


class BaseRateHandler:
    """Base class for rate handlers."""
    
    def __init__(self, client: KimaiClient):
        self.client = client
        self.entity_name = ""
    
    async def list(self, entity_id: int) -> List[TextContent]:
        raise NotImplementedError
    
    async def add(self, entity_id: int, data: Dict) -> List[TextContent]:
        raise NotImplementedError
    
    async def delete(self, entity_id: int, rate_id: int) -> List[TextContent]:
        raise NotImplementedError
    
    def format_rate_list(self, rates: List, entity_name: str, entity_id: int) -> str:
        """Format a list of rates for display."""
        if not rates:
            return f"No rates configured for {entity_name} ID {entity_id}"
        
        result = f"Found {len(rates)} rate(s) for {entity_name} ID {entity_id}:\\n\\n"
        
        for rate in rates:
            result += f"Rate ID: {rate.id}\\n"
            
            if hasattr(rate, "user") and rate.user:
                result += f"  User: {rate.user.username} (ID: {rate.user.id})\\n"
            else:
                result += "  User: All users (default rate)\\n"
            
            result += f"  Rate: {rate.rate}\\n"
            
            if hasattr(rate, "internalRate") and rate.internalRate is not None:
                result += f"  Internal Rate: {rate.internalRate}\\n"
            
            if hasattr(rate, "isFixed"):
                result += f"  Type: {'Fixed' if rate.isFixed else 'Hourly'}\\n"
            
            result += "\\n"
        
        return result


class CustomerRateHandler(BaseRateHandler):
    """Handler for customer rate operations."""
    
    def __init__(self, client: KimaiClient):
        super().__init__(client)
        self.entity_name = "customer"
    
    async def list(self, entity_id: int) -> List[TextContent]:
        rates = await self.client.get_customer_rates(entity_id)
        result = self.format_rate_list(rates, self.entity_name, entity_id)
        return [TextContent(type="text", text=result)]
    
    async def add(self, entity_id: int, data: Dict) -> List[TextContent]:
        rate_form = RateForm(
            user=data.get("user"),
            rate=data.get("rate", 0),
            internal_rate=data.get("internal_rate"),
            is_fixed=data.get("is_fixed", False)
        )
        
        rate = await self.client.add_customer_rate(entity_id, rate_form)
        
        user_info = f"user {rate.user.username}" if rate.user else "all users"
        return [TextContent(
            type="text",
            text=f"Added rate ID {rate.id} for {user_info} to customer ID {entity_id}"
        )]
    
    async def delete(self, entity_id: int, rate_id: int) -> List[TextContent]:
        await self.client.delete_customer_rate(entity_id, rate_id)
        return [TextContent(
            type="text",
            text=f"Deleted rate ID {rate_id} from customer ID {entity_id}"
        )]


class ProjectRateHandler(BaseRateHandler):
    """Handler for project rate operations."""
    
    def __init__(self, client: KimaiClient):
        super().__init__(client)
        self.entity_name = "project"
    
    async def list(self, entity_id: int) -> List[TextContent]:
        rates = await self.client.get_project_rates(entity_id)
        result = self.format_rate_list(rates, self.entity_name, entity_id)
        return [TextContent(type="text", text=result)]
    
    async def add(self, entity_id: int, data: Dict) -> List[TextContent]:
        rate_form = RateForm(
            user=data.get("user"),
            rate=data.get("rate", 0),
            internal_rate=data.get("internal_rate"),
            is_fixed=data.get("is_fixed", False)
        )
        
        rate = await self.client.add_project_rate(entity_id, rate_form)
        
        user_info = f"user {rate.user.username}" if rate.user else "all users"
        return [TextContent(
            type="text",
            text=f"Added rate ID {rate.id} for {user_info} to project ID {entity_id}"
        )]
    
    async def delete(self, entity_id: int, rate_id: int) -> List[TextContent]:
        await self.client.delete_project_rate(entity_id, rate_id)
        return [TextContent(
            type="text",
            text=f"Deleted rate ID {rate_id} from project ID {entity_id}"
        )]


class ActivityRateHandler(BaseRateHandler):
    """Handler for activity rate operations."""
    
    def __init__(self, client: KimaiClient):
        super().__init__(client)
        self.entity_name = "activity"
    
    async def list(self, entity_id: int) -> List[TextContent]:
        rates = await self.client.get_activity_rates(entity_id)
        result = self.format_rate_list(rates, self.entity_name, entity_id)
        return [TextContent(type="text", text=result)]
    
    async def add(self, entity_id: int, data: Dict) -> List[TextContent]:
        rate_form = RateForm(
            user=data.get("user"),
            rate=data.get("rate", 0),
            internal_rate=data.get("internal_rate"),
            is_fixed=data.get("is_fixed", False)
        )
        
        rate = await self.client.add_activity_rate(entity_id, rate_form)
        
        user_info = f"user {rate.user.username}" if rate.user else "all users"
        return [TextContent(
            type="text",
            text=f"Added rate ID {rate.id} for {user_info} to activity ID {entity_id}"
        )]
    
    async def delete(self, entity_id: int, rate_id: int) -> List[TextContent]:
        await self.client.delete_activity_rate(entity_id, rate_id)
        return [TextContent(
            type="text",
            text=f"Deleted rate ID {rate_id} from activity ID {entity_id}"
        )]