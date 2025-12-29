"""Consolidated Entity Manager tool for all CRUD operations."""
import logging
from typing import List, Dict

from mcp.types import Tool, TextContent

from ..client import KimaiClient, KimaiAPIError
from ..models import (
    ProjectEditForm, ActivityEditForm, CustomerEditForm,
    UserCreateForm, UserEditForm, TeamEditForm, TagEditForm,
    ProjectFilter, ActivityFilter, CustomerFilter, Customer
)
from .batch_utils import execute_batch, format_batch_result

logger = logging.getLogger(__name__)


def entity_tool() -> Tool:
    """Define the consolidated entity management tool."""
    return Tool(
        name="entity",
        description="Universal entity management tool for CRUD operations on projects, activities, customers, users, teams, tags, invoices, and holidays.",
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
                    "enum": ["list", "get", "create", "update", "delete", "lock_month", "unlock_month", "batch_delete"],
                    "description": """The action to perform:
                    - list: List entities matching the given filters
                    - create: Create a new entity
                    - get: Get a single entity by ID
                    - update: Update an existing entity by ID
                    - delete: Delete an existing entity by ID
                    - lock_month: Lock working time months for a user (type=user only)
                    - unlock_month: Unlock working time months for a user (type=user only)
                    - batch_delete: Delete multiple entities by IDs (requires 'ids' parameter)
                    """
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
                        "term": {"type": "string",
                                 "description": "Search exact term. For entity types other then invoice and holiday you can just list all if you don't find it on first try."},
                        "customer": {"type": "integer", "description": "Customer ID filter (for projects)"},
                        "project": {"type": "integer", "description": "Project ID filter (for activities)"},
                        "globals": {"type": "string", "enum": ["0", "1"], "description": "Global activities filter"},
                        "page": {"type": "integer", "description": "Page number"},
                        "size": {"type": "integer", "description": "Page size"},
                        "order_by": {"type": "string", "description": "Sort field"},
                        "order": {"type": "string", "enum": ["ASC", "DESC"], "description": "Sort order"},
                        "begin": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Start date and time filter (format: YYYY-MM-DDThh:mm:ss, e.g., 2023-10-27T09:30:00) Only records after this date will be included."
                        },
                        "end": {
                            "type": "string",
                            "format": "date-time",
                            "description": "End date and time filter (format: YYYY-MM-DDThh:mm:ss, e.g., 2023-10-27T17:00:00). Only records before this date will be included."
                        },
                        "customers": {"type": "array", "items": {"type": "integer"},
                                      "description": "Customer IDs (for invoices)"},
                        "status": {"type": "array", "items": {"type": "string"},
                                   "description": "Status filter (for invoices)"}
                    }
                },
                "data": {
                    "type": "object",
                    "description": "Data for create/update actions (entity-specific fields)",
                    "additionalProperties": True
                },
                "month": {
                    "type": "string",
                    "description": "Month for lock_month/unlock_month actions (YYYY-MM-DD format). For lock: all months before and including this one will be locked. For unlock: all months from this one to end of year will be unlocked.",
                    "pattern": "[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[1-2][0-9]|3[0-1])"
                },
                "ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of entity IDs for batch operations (batch_delete, bulk lock_month/unlock_month)."
                },
                "user_scope": {
                    "type": "string",
                    "enum": ["all"],
                    "description": "Set to 'all' to apply lock_month/unlock_month to all active users. Use instead of 'id' or 'ids'."
                }
            },
            "allOff": [
                {
                    "if": {
                        "properties": {
                            "type": {"const": "customer"},
                            "action": {"enum": ["create", "update"]}
                        }
                    },
                    "then": {
                        "properties": {
                            "data": {
                                "type": "object",
                                "description": "Schema for creating/editing customer entities.",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "minLength": 2,
                                        "maxLength": 150,
                                        "description": "Customer name, required for create action."
                                    },
                                    "number": {
                                        "type": "string",
                                        "maxLength": 50,
                                        "description": "Customer number (internal identifier)"
                                    },
                                    "comment": {
                                        "type": "string",
                                        "description": "Any additional comments for the customer"
                                    },
                                    "visible": {
                                        "type": "boolean",
                                        "default": True,
                                        "description": "Whether the customer is visible"
                                    },
                                    "billable": {
                                        "type": "boolean",
                                        "default": True,
                                        "description": "Whether the customer is billable"
                                    },
                                    "company": {
                                        "type": "string",
                                        "maxLength": 100,
                                        "description": "Customer's company name"
                                    },
                                    "vatId": {
                                        "type": "string",
                                        "maxLength": 50,
                                        "description": "VAT ID of the customer"
                                    },
                                    "contact": {
                                        "type": "string",
                                        "maxLength": 100,
                                        "description": "Contact person's name"
                                    },
                                    "address": {
                                        "type": "string",
                                        "description": "Customer's physical address"
                                    },
                                    "country": {
                                        "type": "string",
                                        "maxLength": 2,
                                        "description": "Two-letter ISO country code (e.g., 'US', 'DE'), required for create action.",
                                        "pattern": "^[A-Z]{2}$"
                                    },
                                    "currency": {
                                        "type": "string",
                                        "maxLength": 3,
                                        "default": "EUR",
                                        "description": "Three-letter ISO currency code (e.g., 'EUR', 'USD'), required for create action. Default: 'EUR'.",
                                        "pattern": "^[A-Z]{3}$"
                                    },
                                    "phone": {
                                        "type": "string",
                                        "maxLength": 30,
                                        "description": "Customer's phone number"
                                    },
                                    "fax": {
                                        "type": "string",
                                        "maxLength": 30,
                                        "description": "Customer's fax number"
                                    },
                                    "mobile": {
                                        "type": "string",
                                        "maxLength": 30,
                                        "description": "Customer's mobile number"
                                    },
                                    "email": {
                                        "type": "string",
                                        "maxLength": 75,
                                        "format": "email",
                                        "description": "Customer's email address"
                                    },
                                    "homepage": {
                                        "type": "string",
                                        "maxLength": 100,
                                        "format": "uri",
                                        "description": "Customer's website URL"
                                    },
                                    "timezone": {
                                        "type": "string",
                                        "maxLength": 64,
                                        "description": "Timezone identifier (e.g., 'Europe/Berlin', 'America/New_York'), required for create action."
                                    },
                                    "invoiceText": {
                                        "type": "string",
                                        "description": "Custom text to appear on invoices for this customer"
                                    },
                                    "invoiceTemplate": {
                                        "type": "string",
                                        "format": "App\\Entity\\InvoiceTemplate id",
                                        "description": "ID of the invoice template to use for this customer"
                                    },
                                    "metaFields": {
                                        "type": "array",
                                        "description": "Custom meta fields for this customer",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "name": {"type": "string"},
                                                "value": {"type": "string"}
                                            },
                                            "required": ["name", "value"]
                                        }
                                    }
                                },
                                "additionalProperties": False
                            }
                        },
                        "required": ["data"]
                    }
                },
                {
                    "if": {
                        "properties": {
                            "type": {"const": "project"},
                            "action": {"enum": ["create", "update"]}
                        }
                    },
                    "then": {
                        "properties": {
                            "data": {
                                "type": "object",
                                "description": "Data structure required for creating or updating a 'project' entity.",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "The official or internal name of the project, required for create action.",
                                        "minLength": 2,
                                        "maxLength": 150
                                    },
                                    "number": {
                                        "type": "string",
                                        "maxLength": 10,
                                        "description": "An internal tracking number or code for the project."
                                    },
                                    "comment": {
                                        "type": "string",
                                        "description": "Any additional notes or descriptive comments regarding the project."
                                    },
                                    "invoiceText": {
                                        "type": "string",
                                        "description": "Custom text that should appear on invoices generated for this project."
                                    },
                                    "orderNumber": {
                                        "type": "string",
                                        "maxLength": 50,
                                        "description": "The client's purchase order number or internal order reference for the project."
                                    },
                                    "orderDate": {
                                        "type": "string",
                                        "format": "date",
                                        "description": "The date when the project was ordered or officially started (YYYY-MM-DD format). Note: Times are not included."
                                    },
                                    "start": {
                                        "type": "string",
                                        "format": "date",
                                        "description": "The official start date of the project (YYYY-MM-DD). Timesheets cannot be recorded before this date."
                                    },
                                    "end": {
                                        "type": "string",
                                        "format": "date",
                                        "description": "The projected or actual end date of the project (YYYY-MM-DD). Timesheets cannot be recorded after this date."
                                    },
                                    "customer": {
                                        "description": "The unique ID of the customer to whom this project belongs, required for create action.",
                                        "type": "integer"
                                    },
                                    "color": {
                                        "description": "The assigned display color for the project in HTML hex format (e.g., #dd1d00). If left empty, a color might be auto-calculated.",
                                        "type": "string"
                                    },
                                    "globalActivities": {
                                        "type": "boolean",
                                        "description": "Indicates whether this project allows the booking of globally defined activities.",
                                        "default": True
                                    },
                                    "visible": {
                                        "type": "boolean",
                                        "description": "Controls the visibility of the project. If False, timesheets usually cannot be recorded against it.",
                                        "default": True
                                    },
                                    "billable": {
                                        "type": "boolean",
                                        "default": True,
                                        "description": "Determines if time and expenses recorded against this project are considered billable to the customer."
                                    },
                                    "metaFields": {
                                        "type": "array",
                                        "description": "Custom meta fields for this project",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "name": {"type": "string"},
                                                "value": {"type": "string"}
                                            },
                                            "required": ["name", "value"]
                                        }
                                    }
                                },
                                "additionalProperties": False
                            }
                        },
                        "required": ["data"]
                    },
                },
                {
                    "if": {
                        "properties": {
                            "action": {"enum": ["create", "update"]}
                        }
                    },
                    "else": {
                        "properties": {
                            "data": {"not": {}}  # `data` should not be present / empty if action is not create / update
                        }
                    }
                },
                {
                    "if": {
                        "properties": {
                            "action": {"enum": ["get", "update", "delete"]}
                        }
                    },
                    "then": {
                        "required": ["id"]
                    }
                }
            ]

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
        elif action == "lock_month":
            if entity_type != "user":
                return [
                    TextContent(type="text", text="Error: 'lock_month' action is only available for user entities")]
            month = params.get("month")
            if not month:
                return [TextContent(type="text", text="Error: 'month' parameter is required for lock_month action")]

            # Determine user IDs to process
            user_ids = params.get("ids", [])
            user_scope = params.get("user_scope")

            if user_scope == "all":
                return await handler.lock_month_bulk(None, month, all_users=True)
            elif user_ids:
                return await handler.lock_month_bulk(user_ids, month)
            elif entity_id:
                return await handler.lock_month(entity_id, month)
            else:
                return [TextContent(type="text", text="Error: 'id', 'ids', or 'user_scope=all' is required for lock_month action")]
        elif action == "unlock_month":
            if entity_type != "user":
                return [
                    TextContent(type="text", text="Error: 'unlock_month' action is only available for user entities")]
            month = params.get("month")
            if not month:
                return [TextContent(type="text", text="Error: 'month' parameter is required for unlock_month action")]

            # Determine user IDs to process
            user_ids = params.get("ids", [])
            user_scope = params.get("user_scope")

            if user_scope == "all":
                return await handler.unlock_month_bulk(None, month, all_users=True)
            elif user_ids:
                return await handler.unlock_month_bulk(user_ids, month)
            elif entity_id:
                return await handler.unlock_month(entity_id, month)
            else:
                return [TextContent(type="text", text="Error: 'id', 'ids', or 'user_scope=all' is required for unlock_month action")]
        elif action == "batch_delete":
            ids = params.get("ids", [])
            if not ids:
                return [TextContent(type="text", text="Error: 'ids' parameter is required for batch_delete action")]
            return await _handle_batch_delete(handler, entity_type, ids)
        else:
            return [TextContent(
                type="text",
                text=f"Error: Unknown action '{action}'. Valid actions: list, get, create, update, delete, lock_month, unlock_month, batch_delete"
            )]
    except KimaiAPIError as e:
        logger.error(f"Kimai API Error in tool entity: {e.message} (Status: {e.status_code})")
        logger.error(f"Arguments were: {params}")
        if e.details:
            logger.error(f"Details: {e.details}")

        return [TextContent(
            type="text",
            text=f"Kimai API Error: {e.message} (Status: {e.status_code})" + (
                f" (Details: {e.details})" if e.details else "")
        )]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def _handle_batch_delete(handler: 'BaseEntityHandler', entity_type: str, ids: List[int]) -> List[TextContent]:
    """Batch delete multiple entities."""
    # Check if entity type supports deletion
    non_deletable = ["user", "invoice"]
    if entity_type in non_deletable:
        return [TextContent(
            type="text",
            text=f"Error: batch_delete is not supported for {entity_type} entities"
        )]

    # Map entity types to client delete methods
    delete_methods = {
        "project": handler.client.delete_project,
        "activity": handler.client.delete_activity,
        "customer": handler.client.delete_customer,
        "team": handler.client.delete_team,
        "tag": handler.client.delete_tag,
        "holiday": handler.client.delete_public_holiday,
    }

    delete_method = delete_methods.get(entity_type)
    if not delete_method:
        return [TextContent(
            type="text",
            text=f"Error: batch_delete is not supported for {entity_type} entities"
        )]

    async def delete_one(id: int) -> int:
        await delete_method(id)
        return id

    success, failed = await execute_batch(ids, delete_one)
    result = format_batch_result("Delete", success, failed, f"{entity_type}s")
    return [TextContent(type="text", text=result)]


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

    def serialize_project(self, project) -> str:
        result = f"Project: {project.name} (ID: {project.id})\\n"
        result += f"Customer ID: {project.customer if project.customer else 'None'}\\n"
        result += f"Status: {'Active' if project.visible else 'Inactive'}\\n"
        result += f"Billable: {'Yes' if project.billable else 'No'}\\n"
        if hasattr(project, 'global_activities'):
            result += f"Global Activities: {'Yes' if project.global_activities else 'No'}\\n"
        if getattr(project, 'number', None):
            result += f"Number: {project.number}\\n"
        if getattr(project, 'color', None):
            result += f"Color: {project.color}\\n"
        if getattr(project, 'comment', None):
            result += f"Comment: {project.comment}\\n"
        if getattr(project, 'meta_fields', None):
            result += "Meta Fields:\\n"
            for mf in project.meta_fields:
                name = mf.get('name', mf.name) if hasattr(mf, 'name') else mf.get('name', 'Unknown')
                value = mf.get('value', mf.value) if hasattr(mf, 'value') else mf.get('value', '')
                result += f"  - {name}: {value}\\n"
        result += "\\n"
        return result

    async def list(self, filters: Dict) -> List[TextContent]:
        project_filter = ProjectFilter(
            customer=filters.get("customer"),
            visible=filters.get("visible", 1),
            order=filters.get("order"),
            order_by=filters.get("order_by")
        )
        projects = await self.client.get_projects(project_filter)

        result = f"Found {len(projects)} projects\\n\\\n"
        for project in projects:
            result += self.serialize_project(project)

        return [TextContent(type="text", text=result)]

    async def get(self, id: int) -> List[TextContent]:
        project = await self.client.get_project(id)

        result = self.serialize_project(project)

        return [TextContent(type="text", text=result)]

    async def create(self, data: Dict) -> List[TextContent]:
        # Validate required fields explicitly to provide a clear error before calling the API
        required_fields = ["name", "customer"]
        missing = [field for field in required_fields if not data.get(field)]
        if missing:
            return [TextContent(
                type="text",
                text=f"Error: Missing required project fields: {', '.join(missing)}"
            )]
        form = ProjectEditForm(**data)
        project = await self.client.create_project(form)
        return [TextContent(
            type="text",
            text="Created " + self.serialize_project(project)
        )]

    async def update(self, id: int, data: Dict) -> List[TextContent]:
        form = ProjectEditForm(**data)
        project = await self.client.update_project(id, form)
        return [TextContent(
            type="text",
            text="Updated " + self.serialize_project(project)
        )]

    async def delete(self, id: int) -> List[TextContent]:
        await self.client.delete_project(id)
        return [TextContent(type="text", text=f"Deleted project ID {id}")]


class ActivityEntityHandler(BaseEntityHandler):
    """Handler for activity operations."""

    def serialize_activity(self, activity) -> str:
        result = f"Activity: {activity.name} (ID: {activity.id})\\n"
        result += f"Status: {'Active' if activity.visible else 'Inactive'}\\n"
        result += f"Billable: {'Yes' if activity.billable else 'No'}\\n"
        if hasattr(activity, 'global'):
            result += f"Global: {'Yes' if getattr(activity, 'global', False) else 'No'}\\n"
        if getattr(activity, 'comment', None):
            result += f"Comment: {activity.comment}\\n"
        if getattr(activity, 'meta_fields', None):
            result += "Meta Fields:\\n"
            for mf in activity.meta_fields:
                name = mf.get('name', mf.name) if hasattr(mf, 'name') else mf.get('name', 'Unknown')
                value = mf.get('value', mf.value) if hasattr(mf, 'value') else mf.get('value', '')
                result += f"  - {name}: {value}\\n"
        result += "\\n"
        return result

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

        result = f"Found {len(activities)} activities\\n\\\n"
        for activity in activities:
            result += self.serialize_activity(activity)

        return [TextContent(type="text", text=result)]

    async def get(self, id: int) -> List[TextContent]:
        activity = await self.client.get_activity(id)

        result = self.serialize_activity(activity)

        return [TextContent(type="text", text=result)]

    async def create(self, data: Dict) -> List[TextContent]:
        form = ActivityEditForm(**data)
        activity = await self.client.create_activity(form)
        return [TextContent(
            type="text",
            text="Created " + self.serialize_activity(activity)
        )]

    async def update(self, id: int, data: Dict) -> List[TextContent]:
        form = ActivityEditForm(**data)
        activity = await self.client.update_activity(id, form)
        return [TextContent(
            type="text",
            text="Updated " + self.serialize_activity(activity)
        )]

    async def delete(self, id: int) -> List[TextContent]:
        await self.client.delete_activity(id)
        return [TextContent(type="text", text=f"Deleted activity ID {id}")]


class CustomerEntityHandler(BaseEntityHandler):
    """Handler for customer operations."""

    def serialize_customer(self, customer: Customer) -> str:
        result = f"Customer: {customer.name} (ID: {customer.id})\\n"
        result += f"Status: {'Active' if customer.visible else 'Inactive'}\\n"
        result += f"Billable: {'Yes' if customer.billable else 'No'}\\n"

        # Optional core fields
        if getattr(customer, 'country', None):
            result += f"Country: {customer.country}\\n"
        if getattr(customer, 'currency', None):
            result += f"Currency: {customer.currency}\\n"
        if getattr(customer, 'timezone', None):
            result += f"Timezone: {customer.timezone}\\n"

        # Optional identifiers and visuals
        if getattr(customer, 'number', None):
            result += f"Number: {customer.number}\\n"
        if getattr(customer, 'color', None):
            result += f"Color: {customer.color}\\n"

        # Optional contact/company details
        if getattr(customer, 'phone', None):
            result += f"Phone: {customer.phone}\\n"
        if getattr(customer, 'fax', None):
            result += f"Fax: {customer.fax}\\n"
        if getattr(customer, 'mobile', None):
            result += f"Mobile: {customer.mobile}\\n"
        if getattr(customer, 'homepage', None):
            result += f"Homepage: {customer.homepage}\\n"
        if getattr(customer, 'company', None):
            result += f"Company: {customer.company}\\n"

        if getattr(customer, 'comment', None):
            result += f"Comment: {customer.comment}\\n"
        if getattr(customer, 'meta_fields', None):
            result += "Meta Fields:\\n"
            for mf in customer.meta_fields:
                name = mf.get('name', mf.name) if hasattr(mf, 'name') else mf.get('name', 'Unknown')
                value = mf.get('value', mf.value) if hasattr(mf, 'value') else mf.get('value', '')
                result += f"  - {name}: {value}\\n"
        result += "\\n"

        return result

    async def list(self, filters: Dict) -> List[TextContent]:
        customer_filter = CustomerFilter(
            visible=filters.get("visible", 1),
            term=filters.get("term"),
            order=filters.get("order"),
            order_by=filters.get("order_by")
        )
        customers = await self.client.get_customers(customer_filter)

        result = f"Found {len(customers)} customers\\n\\\n"
        for customer in customers:
            result += self.serialize_customer(customer)

        return [TextContent(type="text", text=result)]

    async def get(self, id: int) -> List[TextContent]:
        customer = await self.client.get_customer(id)

        result = self.serialize_customer(customer)

        return [TextContent(type="text", text=result)]

    async def create(self, data: Dict) -> List[TextContent]:
        # Validate required fields explicitly to provide a clear error before calling the API
        required_fields = ["name", "country", "currency", "timezone"]
        missing = [field for field in required_fields if not data.get(field)]
        if missing:
            return [TextContent(
                type="text",
                text=f"Error: Missing required customer fields: {', '.join(missing)}"
            )]

        form = CustomerEditForm(**data)
        customer = await self.client.create_customer(form)
        return [TextContent(
            type="text",
            text="Created " + self.serialize_customer(customer)
        )]

    async def update(self, id: int, data: Dict) -> List[TextContent]:
        form = CustomerEditForm(**data)
        customer = await self.client.update_customer(id, form)
        return [TextContent(
            type="text",
            text="Updated " + self.serialize_customer(customer)
        )]

    async def delete(self, id: int) -> List[TextContent]:
        await self.client.delete_customer(id)
        return [TextContent(type="text", text=f"Deleted customer ID {id}")]


class UserEntityHandler(BaseEntityHandler):
    """Handler for user operations."""

    def serialize_user(self, user) -> str:
        result = f"User: {user.username} (ID: {user.id})\\n"
        result += f"Name: {user.alias or 'Not set'}\\n"
        result += f"Title: {user.title or 'Not set'}\\n"
        result += f"Status: {'Active' if user.enabled else 'Inactive'}\\n"
        if getattr(user, 'color', None):
            result += f"Color: {user.color}\\n"
        result += "\\n"
        return result

    async def list(self, filters: Dict) -> List[TextContent]:
        users = await self.client.get_users(
            visible=filters.get("visible", 1),
            term=filters.get("term")
        )

        result = f"Found {len(users)} users\\n\\\n"
        for user in users:
            result += self.serialize_user(user)

        return [TextContent(type="text", text=result)]

    async def get(self, id: int) -> List[TextContent]:
        user = await self.client.get_user_extended(id)

        result = self.serialize_user(user)

        return [TextContent(type="text", text=result)]

    async def create(self, data: Dict) -> List[TextContent]:
        form = UserCreateForm(**data)
        user = await self.client.create_user(form)
        return [TextContent(
            type="text",
            text="Created " + self.serialize_user(user)
        )]

    async def update(self, id: int, data: Dict) -> List[TextContent]:
        form = UserEditForm(**data)
        user = await self.client.update_user(id, form)
        return [TextContent(
            type="text",
            text="Updated " + self.serialize_user(user)
        )]

    async def delete(self, id: int) -> List[TextContent]:
        return [TextContent(
            type="text",
            text="Error: Users cannot be deleted. Use update with enabled=false to deactivate."
        )]

    async def lock_month(self, user_id: int, month: str) -> List[TextContent]:
        """Lock working time months for a user."""
        await self.client.lock_work_contract_month(user_id, month)
        return [TextContent(
            type="text",
            text=f"Locked working time months up to and including {month} for user ID {user_id}"
        )]

    async def lock_month_bulk(self, user_ids: List[int], month: str, all_users: bool = False) -> List[TextContent]:
        """Lock working time months for multiple users."""
        if all_users:
            # Try to get users from teams first (works for team leads and admins)
            accessible_user_ids = set()
            try:
                teams = await self.client.get_teams()
                for team in teams:
                    try:
                        team_detail = await self.client.get_team(team.id)
                        if team_detail.members:
                            for member in team_detail.members:
                                accessible_user_ids.add(member.user.id)
                    except Exception:
                        continue
            except Exception:
                pass

            # Fallback to get_users (requires higher permissions)
            if not accessible_user_ids:
                try:
                    users = await self.client.get_users(visible=1)
                    accessible_user_ids = {u.id for u in users if u.enabled}
                except Exception as e:
                    error_msg = str(e).lower()
                    if "forbidden" in error_msg or "403" in error_msg:
                        return [TextContent(
                            type="text",
                            text="Error: You don't have permission to access all users.\n\n"
                                 "This requires either:\n"
                                 "- System Administrator role, or\n"
                                 "- Being a team lead (to access team members)\n\n"
                                 "Use 'ids' parameter to specify specific user IDs instead."
                        )]
                    raise

            user_ids = list(accessible_user_ids)

        success = []
        failed = []

        for uid in user_ids:
            try:
                await self.client.lock_work_contract_month(uid, month)
                success.append(uid)
            except Exception as e:
                failed.append((uid, str(e)))

        result = f"Locked month {month} for {len(success)} users"
        if failed:
            result += f", {len(failed)} failed:\n"
            for uid, error in failed:
                result += f"  - User {uid}: {error}\n"

        return [TextContent(type="text", text=result)]

    async def unlock_month(self, user_id: int, month: str) -> List[TextContent]:
        """Unlock working time months for a user."""
        await self.client.unlock_work_contract_month(user_id, month)
        return [TextContent(
            type="text",
            text=f"Unlocked working time months from {month} onwards for user ID {user_id}"
        )]

    async def unlock_month_bulk(self, user_ids: List[int], month: str, all_users: bool = False) -> List[TextContent]:
        """Unlock working time months for multiple users."""
        if all_users:
            # Try to get users from teams first (works for team leads and admins)
            accessible_user_ids = set()
            try:
                teams = await self.client.get_teams()
                for team in teams:
                    try:
                        team_detail = await self.client.get_team(team.id)
                        if team_detail.members:
                            for member in team_detail.members:
                                accessible_user_ids.add(member.user.id)
                    except Exception:
                        continue
            except Exception:
                pass

            # Fallback to get_users (requires higher permissions)
            if not accessible_user_ids:
                try:
                    users = await self.client.get_users(visible=1)
                    accessible_user_ids = {u.id for u in users if u.enabled}
                except Exception as e:
                    error_msg = str(e).lower()
                    if "forbidden" in error_msg or "403" in error_msg:
                        return [TextContent(
                            type="text",
                            text="Error: You don't have permission to access all users.\n\n"
                                 "This requires either:\n"
                                 "- System Administrator role, or\n"
                                 "- Being a team lead (to access team members)\n\n"
                                 "Use 'ids' parameter to specify specific user IDs instead."
                        )]
                    raise

            user_ids = list(accessible_user_ids)

        success = []
        failed = []

        for uid in user_ids:
            try:
                await self.client.unlock_work_contract_month(uid, month)
                success.append(uid)
            except Exception as e:
                failed.append((uid, str(e)))

        result = f"Unlocked month {month} for {len(success)} users"
        if failed:
            result += f", {len(failed)} failed:\n"
            for uid, error in failed:
                result += f"  - User {uid}: {error}\n"

        return [TextContent(type="text", text=result)]


class TeamEntityHandler(BaseEntityHandler):
    """Handler for team operations."""

    def serialize_team(self, team) -> str:
        result = f"Team: {team.name} (ID: {team.id})\\n"
        if hasattr(team, 'color') and team.color:
            result += f"Color: {team.color}\\n"
        if hasattr(team, 'members') and team.members:
            result += f"\nMembers ({len(team.members)}):\\n"
            for member in team.members:
                teamlead = " (Team Lead)" if getattr(member, 'teamlead', False) else ""
                username = getattr(getattr(member, 'user', None), 'username', None) or getattr(member, 'username',
                                                                                               'Unknown')
                result += f"  - {username}{teamlead}\\n"
        result += "\\n"
        return result

    async def list(self, filters: Dict) -> List[TextContent]:
        teams = await self.client.get_teams()

        result = f"Found {len(teams)} teams\\n\\\n"
        for team in teams:
            result += self.serialize_team(team)

        return [TextContent(type="text", text=result)]

    async def get(self, id: int) -> List[TextContent]:
        team = await self.client.get_team(id)

        result = self.serialize_team(team)

        return [TextContent(type="text", text=result)]

    async def create(self, data: Dict) -> List[TextContent]:
        form = TeamEditForm(**data)
        team = await self.client.create_team(form)
        return [TextContent(
            type="text",
            text="Created " + self.serialize_team(team)
        )]

    async def update(self, id: int, data: Dict) -> List[TextContent]:
        form = TeamEditForm(**data)
        team = await self.client.update_team(id, form)
        return [TextContent(
            type="text",
            text="Updated " + self.serialize_team(team)
        )]

    async def delete(self, id: int) -> List[TextContent]:
        await self.client.delete_team(id)
        return [TextContent(type="text", text=f"Deleted team ID {id}")]


class TagEntityHandler(BaseEntityHandler):
    """Handler for tag operations."""

    def serialize_tag(self, tag) -> str:
        result = f"Tag: {tag.name} (ID: {tag.id})\\n"
        visible_str = "Visible" if getattr(tag, 'visible', True) else "Hidden"
        result += f"Status: {visible_str}\\n"
        if hasattr(tag, 'color') and tag.color:
            result += f"Color: {tag.color}\\n"
        result += "\\n"
        return result

    async def list(self, filters: Dict) -> List[TextContent]:
        # Get all tags and filter locally since API doesn't support name filter
        all_tags = await self.client.get_tags_full()
        if filters.get("name"):
            tags = [tag for tag in all_tags if filters["name"].lower() in tag.name.lower()]
        else:
            tags = all_tags

        result = f"Found {len(tags)} tags\\n\\\n"
        for tag in tags:
            result += self.serialize_tag(tag)

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
            text="Created " + self.serialize_tag(tag)
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

        result = f"Found {len(invoices)} invoices\\n\\\n"
        for invoice in invoices:
            result += f"ID: {invoice.id} - {invoice.invoice_number}\\\n"
            result += f"  Customer: {invoice.customer.name if invoice.customer else 'Unknown'}\\\n"
            result += f"  Status: {invoice.status}\\\n"
            if getattr(invoice, 'overdue', None) is not None:
                result += f"  Overdue: {'Yes' if invoice.overdue else 'No'}\\\n"
            result += f"  Total: {invoice.total}\\\n"
            result += f"  Date: {invoice.created_at}\\\n"
            result += "\\\n"

        return [TextContent(type="text", text=result)]

    async def get(self, id: int) -> List[TextContent]:
        invoice = await self.client.get_invoice(id)

        result = f"Invoice: {invoice.invoice_number} (ID: {invoice.id})\\\n"
        result += f"Customer: {invoice.customer.name if invoice.customer else 'Unknown'}\\\n"
        result += f"Status: {invoice.status}\\\n"
        if getattr(invoice, 'overdue', None) is not None:
            result += f"Overdue: {'Yes' if invoice.overdue else 'No'}\\\n"
        result += f"Total: {invoice.total}\\\n"
        result += f"Tax: {invoice.tax}\\\n"
        result += f"Created: {invoice.created_at}\\\n"

        if getattr(invoice, 'due_days', None):
            result += f"Due Days: {invoice.due_days}\\\n"
        if getattr(invoice, 'payment_date', None):
            result += f"Payment Date: {invoice.payment_date}\\\n"
        if getattr(invoice, 'comment', None):
            result += f"Comment: {invoice.comment}\\\n"

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
        holidays = await self.client.get_public_holidays(
            year=filters.get("year"),
            month=filters.get("month")
        )

        result = f"Found {len(holidays)} holidays\\n\\\n"
        for holiday in holidays:
            result += f"ID: {holiday.id} - {holiday.name}\\\n"
            result += f"  Date: {holiday.date}\\\n"
            if hasattr(holiday, "type") and holiday.type:
                result += f"  Type: {holiday.type}\\\n"
            result += "\\\n"

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
        await self.client.delete_public_holiday(id)
        return [TextContent(type="text", text=f"Deleted holiday ID {id}")]
