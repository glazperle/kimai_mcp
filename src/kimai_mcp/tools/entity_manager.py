"""Consolidated Entity Manager tool for all CRUD operations."""

import json
from typing import List, Dict, Any, Optional
from mcp.types import Tool, TextContent
from ..client import KimaiClient
from ..models import (
    ProjectEditForm, ActivityEditForm, CustomerEditForm,
    UserCreateForm, UserEditForm, TeamEditForm, TagEditForm,
    ProjectFilter, ActivityFilter, CustomerFilter
)


def entity_tool() -> Tool:
    """Define the consolidated entity management tool."""
    return Tool(
        name="entity",
        description="Universal entity management tool for CRUD operations on projects, activities, customers, users, teams, tags, invoices, and holidays. Replaces 35 individual tools with one flexible interface.",
        inputSchema={
            "type": "object",
            "required": ["type", "action"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["project", "activity", "customer", "user", "team", "tag", "invoice", "holiday"],
                    "description": "The entity type to operate on"
                },
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "update", "delete", "unlock_month"],
                    "description": "The action to perform"
                },
                "id": {
                    "type": "integer",
                    "description": "Entity ID (required for get, update, delete actions)"
                },
                "filters": {
                    "type": "object",
                    "description": "Filters for list action (e.g., visible, term, customer, project)",
                    "properties": {
                        "visible": {"type": "integer", "enum": [1, 2, 3], "description": "1=visible, 2=hidden, 3=both"},
                        "term": {"type": "string", "description": "Search term"},
                        "customer": {"type": "integer", "description": "Customer ID filter (for projects)"},
                        "project": {"type": "integer", "description": "Project ID filter (for activities)"},
                        "globals": {"type": "string", "enum": ["0", "1"], "description": "Global activities filter"},
                        "page": {"type": "integer", "description": "Page number"},
                        "size": {"type": "integer", "description": "Page size"},
                        "order_by": {"type": "string", "description": "Sort field"},
                        "order": {"type": "string", "enum": ["ASC", "DESC"], "description": "Sort order"},
                        "begin": {"type": "string", "format": "date", "description": "Start date filter"},
                        "end": {"type": "string", "format": "date", "description": "End date filter"},
                        "customers": {"type": "array", "items": {"type": "integer"}, "description": "Customer IDs (for invoices)"},
                        "status": {"type": "array", "items": {"type": "string"}, "description": "Status filter (for invoices)"}
                    }
                },
                "data": {
                    "type": "object",
                    "description": "Data for create/update actions (entity-specific fields)",
                    "additionalProperties": True
                },
                "month": {
                    "type": "string",
                    "description": "Month to unlock (YYYY-MM-DD format, for unlock_month action on user entities)",
                    "pattern": "[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[1-2][0-9]|3[0-1])"
                }
            }
        }
    )


async def handle_entity(client: KimaiClient, **params) -> List[TextContent]:
    """Handle consolidated entity operations."""
    entity_type = params.get("type")
    action = params.get("action")
    entity_id = params.get("id")
    filters = params.get("filters", {})
    data = params.get("data", {})
    
    # Route to appropriate handler
    handlers = {
        "project": ProjectEntityHandler(client),
        "activity": ActivityEntityHandler(client),
        "customer": CustomerEntityHandler(client),
        "user": UserEntityHandler(client),
        "team": TeamEntityHandler(client),
        "tag": TagEntityHandler(client),
        "invoice": InvoiceEntityHandler(client),
        "holiday": HolidayEntityHandler(client)
    }
    
    handler = handlers.get(entity_type)
    if not handler:
        return [TextContent(
            type="text",
            text=f"Error: Unknown entity type '{entity_type}'. Valid types: {', '.join(handlers.keys())}"
        )]
    
    # Execute action
    try:
        if action == "list":
            return await handler.list(filters)
        elif action == "get":
            if not entity_id:
                return [TextContent(type="text", text="Error: 'id' parameter is required for get action")]
            return await handler.get(entity_id)
        elif action == "create":
            if not data:
                return [TextContent(type="text", text="Error: 'data' parameter is required for create action")]
            return await handler.create(data)
        elif action == "update":
            if not entity_id:
                return [TextContent(type="text", text="Error: 'id' parameter is required for update action")]
            if not data:
                return [TextContent(type="text", text="Error: 'data' parameter is required for update action")]
            return await handler.update(entity_id, data)
        elif action == "delete":
            if not entity_id:
                return [TextContent(type="text", text="Error: 'id' parameter is required for delete action")]
            return await handler.delete(entity_id)
        elif action == "unlock_month":
            if entity_type != "user":
                return [TextContent(type="text", text="Error: 'unlock_month' action is only available for user entities")]
            if not entity_id:
                return [TextContent(type="text", text="Error: 'id' parameter is required for unlock_month action")]
            month = params.get("month")
            if not month:
                return [TextContent(type="text", text="Error: 'month' parameter is required for unlock_month action")]
            return await handler.unlock_month(entity_id, month)
        else:
            return [TextContent(
                type="text",
                text=f"Error: Unknown action '{action}'. Valid actions: list, get, create, update, delete, unlock_month"
            )]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


class BaseEntityHandler:
    """Base class for entity-specific handlers."""
    
    def __init__(self, client: KimaiClient):
        self.client = client
    
    async def list(self, filters: Dict) -> List[TextContent]:
        raise NotImplementedError
    
    async def get(self, id: int) -> List[TextContent]:
        raise NotImplementedError
    
    async def create(self, data: Dict) -> List[TextContent]:
        raise NotImplementedError
    
    async def update(self, id: int, data: Dict) -> List[TextContent]:
        raise NotImplementedError
    
    async def delete(self, id: int) -> List[TextContent]:
        raise NotImplementedError


class ProjectEntityHandler(BaseEntityHandler):
    """Handler for project operations."""
    
    async def list(self, filters: Dict) -> List[TextContent]:
        project_filter = ProjectFilter(
            customer=filters.get("customer"),
            visible=filters.get("visible", 1),
            order=filters.get("order"),
            order_by=filters.get("order_by")
        )
        projects = await self.client.get_projects(project_filter)
        
        result = f"Found {len(projects)} projects\\n\\n"
        for project in projects:
            customer_id = project.customer if project.customer else "No customer"
            status = "Active" if project.visible else "Inactive"
            result += f"ID: {project.id} - {project.name}\\n"
            result += f"  Customer ID: {customer_id}\\n"
            result += f"  Status: {status}\\n"
            result += f"  Billable: {'Yes' if project.billable else 'No'}\\n"
            if project.comment:
                result += f"  Comment: {project.comment}\\n"
            if project.color:
                result += f"  Color: {project.color}\\n"
            result += "\\n"
        
        return [TextContent(type="text", text=result)]
    
    async def get(self, id: int) -> List[TextContent]:
        project = await self.client.get_project(id)
        
        result = f"Project: {project.name} (ID: {project.id})\\n"
        result += f"Customer ID: {project.customer if project.customer else 'None'}\\n"
        result += f"Status: {'Active' if project.visible else 'Inactive'}\\n"
        result += f"Billable: {'Yes' if project.billable else 'No'}\\n"
        result += f"Global Activities: {'Yes' if project.global_activities else 'No'}\\n"
        
        if project.number:
            result += f"Number: {project.number}\\n"
        if project.color:
            result += f"Color: {project.color}\\n"
        if project.comment:
            result += f"Comment: {project.comment}\\n"
        
        return [TextContent(type="text", text=result)]
    
    async def create(self, data: Dict) -> List[TextContent]:
        form = ProjectEditForm(**data)
        project = await self.client.create_project(form)
        return [TextContent(
            type="text", 
            text=f"Created project '{project.name}' with ID {project.id}"
        )]
    
    async def update(self, id: int, data: Dict) -> List[TextContent]:
        form = ProjectEditForm(**data)
        project = await self.client.update_project(id, form)
        return [TextContent(
            type="text",
            text=f"Updated project '{project.name}' (ID: {project.id})"
        )]
    
    async def delete(self, id: int) -> List[TextContent]:
        await self.client.delete_project(id)
        return [TextContent(type="text", text=f"Deleted project ID {id}")]


class ActivityEntityHandler(BaseEntityHandler):
    """Handler for activity operations."""
    
    async def list(self, filters: Dict) -> List[TextContent]:
        activity_filter = ActivityFilter(
            project=filters.get("project"),
            visible=filters.get("visible", 1),
            globals=filters.get("globals"),
            term=filters.get("term"),
            order=filters.get("order"),
            order_by=filters.get("order_by")
        )
        activities = await self.client.get_activities(activity_filter)
        
        result = f"Found {len(activities)} activities\\n\\n"
        for activity in activities:
            global_str = " (Global)" if getattr(activity, "global", False) else ""
            status = "Active" if activity.visible else "Inactive"
            result += f"ID: {activity.id} - {activity.name}{global_str}\\n"
            result += f"  Status: {status}\\n"
            if activity.comment:
                result += f"  Comment: {activity.comment}\\n"
            result += "\\n"
        
        return [TextContent(type="text", text=result)]
    
    async def get(self, id: int) -> List[TextContent]:
        activity = await self.client.get_activity(id)
        
        result = f"Activity: {activity.name} (ID: {activity.id})\\n"
        result += f"Status: {'Active' if activity.visible else 'Inactive'}\\n"
        result += f"Billable: {'Yes' if activity.billable else 'No'}\\n"
        if hasattr(activity, "global"):
            result += f"Global: {'Yes' if getattr(activity, 'global', False) else 'No'}\\n"
        if activity.comment:
            result += f"Comment: {activity.comment}\\n"
        
        return [TextContent(type="text", text=result)]
    
    async def create(self, data: Dict) -> List[TextContent]:
        form = ActivityEditForm(**data)
        activity = await self.client.create_activity(form)
        return [TextContent(
            type="text",
            text=f"Created activity '{activity.name}' with ID {activity.id}"
        )]
    
    async def update(self, id: int, data: Dict) -> List[TextContent]:
        form = ActivityEditForm(**data)
        activity = await self.client.update_activity(id, form)
        return [TextContent(
            type="text",
            text=f"Updated activity '{activity.name}' (ID: {activity.id})"
        )]
    
    async def delete(self, id: int) -> List[TextContent]:
        await self.client.delete_activity(id)
        return [TextContent(type="text", text=f"Deleted activity ID {id}")]


class CustomerEntityHandler(BaseEntityHandler):
    """Handler for customer operations."""
    
    async def list(self, filters: Dict) -> List[TextContent]:
        customer_filter = CustomerFilter(
            visible=filters.get("visible", 1),
            term=filters.get("term"),
            order=filters.get("order"),
            order_by=filters.get("order_by")
        )
        customers = await self.client.get_customers(customer_filter)
        
        result = f"Found {len(customers)} customers\\n\\n"
        for customer in customers:
            status = "Active" if customer.visible else "Inactive"
            result += f"ID: {customer.id} - {customer.name}\\n"
            result += f"  Status: {status}\\n"
            result += f"  Billable: {'Yes' if customer.billable else 'No'}\\n"
            if customer.number:
                result += f"  Number: {customer.number}\\n"
            if customer.color:
                result += f"  Color: {customer.color}\\n"
            if customer.comment:
                result += f"  Comment: {customer.comment}\\n"
            result += "\\n"
        
        return [TextContent(type="text", text=result)]
    
    async def get(self, id: int) -> List[TextContent]:
        customer = await self.client.get_customer(id)
        
        result = f"Customer: {customer.name} (ID: {customer.id})\\n"
        result += f"Status: {'Active' if customer.visible else 'Inactive'}\\n"
        result += f"Billable: {'Yes' if customer.billable else 'No'}\\n"
        
        if customer.number:
            result += f"Number: {customer.number}\\n"
        if customer.color:
            result += f"Color: {customer.color}\\n"
        if customer.comment:
            result += f"Comment: {customer.comment}\\n"
        
        return [TextContent(type="text", text=result)]
    
    async def create(self, data: Dict) -> List[TextContent]:
        form = CustomerEditForm(**data)
        customer = await self.client.create_customer(form)
        return [TextContent(
            type="text",
            text=f"Created customer '{customer.name}' with ID {customer.id}"
        )]
    
    async def update(self, id: int, data: Dict) -> List[TextContent]:
        form = CustomerEditForm(**data)
        customer = await self.client.update_customer(id, form)
        return [TextContent(
            type="text",
            text=f"Updated customer '{customer.name}' (ID: {customer.id})"
        )]
    
    async def delete(self, id: int) -> List[TextContent]:
        await self.client.delete_customer(id)
        return [TextContent(type="text", text=f"Deleted customer ID {id}")]


class UserEntityHandler(BaseEntityHandler):
    """Handler for user operations."""
    
    async def list(self, filters: Dict) -> List[TextContent]:
        users = await self.client.get_users(
            visible=filters.get("visible", 1),
            term=filters.get("term")
        )
        
        result = f"Found {len(users)} users\\n\\n"
        for user in users:
            status = "Active" if user.enabled else "Inactive"
            result += f"ID: {user.id} - {user.username}\\n"
            result += f"  Name: {user.alias or 'Not set'}\\n"
            result += f"  Title: {user.title or 'Not set'}\\n"
            result += f"  Status: {status}\\n"
            if user.color:
                result += f"  Color: {user.color}\\n"
            result += "\\n"
        
        return [TextContent(type="text", text=result)]
    
    async def get(self, id: int) -> List[TextContent]:
        user = await self.client.get_user(id)
        
        result = f"User: {user.username} (ID: {user.id})\\n"
        result += f"Name: {user.alias or 'Not set'}\\n"
        result += f"Title: {user.title or 'Not set'}\\n"
        result += f"Status: {'Active' if user.enabled else 'Inactive'}\\n"
        
        if user.color:
            result += f"Color: {user.color}\\n"
        
        return [TextContent(type="text", text=result)]
    
    async def create(self, data: Dict) -> List[TextContent]:
        form = UserCreateForm(**data)
        user = await self.client.create_user(form)
        return [TextContent(
            type="text",
            text=f"Created user '{user.username}' with ID {user.id}"
        )]
    
    async def update(self, id: int, data: Dict) -> List[TextContent]:
        form = UserEditForm(**data)
        user = await self.client.update_user(id, form)
        return [TextContent(
            type="text",
            text=f"Updated user '{user.username}' (ID: {user.id})"
        )]
    
    async def delete(self, id: int) -> List[TextContent]:
        return [TextContent(
            type="text",
            text="Error: Users cannot be deleted. Use update with enabled=false to deactivate."
        )]
    
    async def unlock_month(self, user_id: int, month: str) -> List[TextContent]:
        """Unlock working time months for a user."""
        await self.client.unlock_work_contract_month(user_id, month)
        return [TextContent(
            type="text",
            text=f"Unlocked working time months from {month} onwards for user ID {user_id}"
        )]


class TeamEntityHandler(BaseEntityHandler):
    """Handler for team operations."""
    
    async def list(self, filters: Dict) -> List[TextContent]:
        teams = await self.client.get_teams()
        
        result = f"Found {len(teams)} teams\\n\\n"
        for team in teams:
            result += f"ID: {team.id} - {team.name}\\n"
            if hasattr(team, "color") and team.color:
                result += f"  Color: {team.color}\\n"
            if hasattr(team, "members") and team.members:
                result += f"  Members: {len(team.members)}\\n"
            result += "\\n"
        
        return [TextContent(type="text", text=result)]
    
    async def get(self, id: int) -> List[TextContent]:
        team = await self.client.get_team(id)
        
        result = f"Team: {team.name} (ID: {team.id})\\n"
        if hasattr(team, "color") and team.color:
            result += f"Color: {team.color}\\n"
        
        if hasattr(team, "members") and team.members:
            result += f"\\nMembers ({len(team.members)}):\\n"
            for member in team.members:
                teamlead = " (Team Lead)" if member.teamlead else ""
                result += f"  - {member.user.username}{teamlead}\\n"
        
        return [TextContent(type="text", text=result)]
    
    async def create(self, data: Dict) -> List[TextContent]:
        form = TeamEditForm(**data)
        team = await self.client.create_team(form)
        return [TextContent(
            type="text",
            text=f"Created team '{team.name}' with ID {team.id}"
        )]
    
    async def update(self, id: int, data: Dict) -> List[TextContent]:
        form = TeamEditForm(**data)
        team = await self.client.update_team(id, form)
        return [TextContent(
            type="text",
            text=f"Updated team '{team.name}' (ID: {team.id})"
        )]
    
    async def delete(self, id: int) -> List[TextContent]:
        await self.client.delete_team(id)
        return [TextContent(type="text", text=f"Deleted team ID {id}")]


class TagEntityHandler(BaseEntityHandler):
    """Handler for tag operations."""
    
    async def list(self, filters: Dict) -> List[TextContent]:
        tags = await self.client.get_tags(name=filters.get("name"))
        
        result = f"Found {len(tags)} tags\\n\\n"
        for tag in tags:
            visible_str = "Visible" if tag.visible else "Hidden"
            result += f"ID: {tag.id} - {tag.name}\\n"
            result += f"  Status: {visible_str}\\n"
            if hasattr(tag, "color") and tag.color:
                result += f"  Color: {tag.color}\\n"
            result += "\\n"
        
        return [TextContent(type="text", text=result)]
    
    async def get(self, id: int) -> List[TextContent]:
        return [TextContent(
            type="text",
            text="Error: Tags don't support individual retrieval. Use list instead."
        )]
    
    async def create(self, data: Dict) -> List[TextContent]:
        form = TagEditForm(**data)
        tag = await self.client.create_tag(form)
        return [TextContent(
            type="text",
            text=f"Created tag '{tag.name}' with ID {tag.id}"
        )]
    
    async def update(self, id: int, data: Dict) -> List[TextContent]:
        return [TextContent(
            type="text",
            text="Error: Tags cannot be updated. Delete and recreate if needed."
        )]
    
    async def delete(self, id: int) -> List[TextContent]:
        await self.client.delete_tag(id)
        return [TextContent(type="text", text=f"Deleted tag ID {id}")]


class InvoiceEntityHandler(BaseEntityHandler):
    """Handler for invoice operations."""
    
    async def list(self, filters: Dict) -> List[TextContent]:
        invoices = await self.client.get_invoices(
            begin=filters.get("begin"),
            end=filters.get("end"),
            customers=filters.get("customers"),
            status=filters.get("status"),
            page=filters.get("page", 1),
            size=filters.get("size", 50)
        )
        
        result = f"Found {len(invoices)} invoices\\n\\n"
        for invoice in invoices:
            result += f"ID: {invoice.id} - {invoice.invoiceNumber}\\n"
            result += f"  Customer: {invoice.customer.name if invoice.customer else 'Unknown'}\\n"
            result += f"  Status: {invoice.status}\\n"
            result += f"  Total: {invoice.total}\\n"
            result += f"  Date: {invoice.createdAt}\\n"
            result += "\\n"
        
        return [TextContent(type="text", text=result)]
    
    async def get(self, id: int) -> List[TextContent]:
        invoice = await self.client.get_invoice(id)
        
        result = f"Invoice: {invoice.invoiceNumber} (ID: {invoice.id})\\n"
        result += f"Customer: {invoice.customer.name if invoice.customer else 'Unknown'}\\n"
        result += f"Status: {invoice.status}\\n"
        result += f"Total: {invoice.total}\\n"
        result += f"Subtotal: {invoice.subtotal}\\n"
        result += f"Tax: {invoice.tax}\\n"
        result += f"Created: {invoice.createdAt}\\n"
        
        if hasattr(invoice, "dueDate") and invoice.dueDate:
            result += f"Due Date: {invoice.dueDate}\\n"
        if hasattr(invoice, "comment") and invoice.comment:
            result += f"Comment: {invoice.comment}\\n"
        
        return [TextContent(type="text", text=result)]
    
    async def create(self, data: Dict) -> List[TextContent]:
        return [TextContent(
            type="text",
            text="Error: Invoice creation is not supported through this API."
        )]
    
    async def update(self, id: int, data: Dict) -> List[TextContent]:
        return [TextContent(
            type="text",
            text="Error: Invoice updates are not supported through this API."
        )]
    
    async def delete(self, id: int) -> List[TextContent]:
        return [TextContent(
            type="text",
            text="Error: Invoice deletion is not supported through this API."
        )]


class HolidayEntityHandler(BaseEntityHandler):
    """Handler for holiday operations."""
    
    async def list(self, filters: Dict) -> List[TextContent]:
        holidays = await self.client.get_holidays(
            year=filters.get("year"),
            month=filters.get("month")
        )
        
        result = f"Found {len(holidays)} holidays\\n\\n"
        for holiday in holidays:
            result += f"ID: {holiday.id} - {holiday.name}\\n"
            result += f"  Date: {holiday.date}\\n"
            if hasattr(holiday, "type") and holiday.type:
                result += f"  Type: {holiday.type}\\n"
            result += "\\n"
        
        return [TextContent(type="text", text=result)]
    
    async def get(self, id: int) -> List[TextContent]:
        return [TextContent(
            type="text",
            text="Error: Holidays don't support individual retrieval. Use list instead."
        )]
    
    async def create(self, data: Dict) -> List[TextContent]:
        return [TextContent(
            type="text",
            text="Error: Holiday creation is managed by administrators."
        )]
    
    async def update(self, id: int, data: Dict) -> List[TextContent]:
        return [TextContent(
            type="text",
            text="Error: Holiday updates are not supported through this API."
        )]
    
    async def delete(self, id: int) -> List[TextContent]:
        await self.client.delete_holiday(id)
        return [TextContent(type="text", text=f"Deleted holiday ID {id}")]