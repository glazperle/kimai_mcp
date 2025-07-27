"""Customer-related MCP tools."""

from typing import Any, Dict, List, Optional

from mcp.types import Tool, TextContent

from ..client import KimaiClient
from ..models import CustomerFilter, CustomerEditForm, RateForm, MetaFieldForm


# Tool definitions

def list_customers_tool() -> Tool:
    """Define the list customers tool."""
    return Tool(
        name="customer_list",
        description="List customers with optional filters",
        inputSchema={
            "type": "object",
            "properties": {
                "visible": {"type": "integer", "enum": [1, 2, 3], "description": "Visibility: 1=visible, 2=hidden, 3=both"},
                "order": {"type": "string", "enum": ["ASC", "DESC"], "description": "Sort order"},
                "orderBy": {"type": "string", "enum": ["id", "name"], "description": "Sort field"},
                "term": {"type": "string", "description": "Search term"}
            }
        }
    )


def get_customer_tool() -> Tool:
    """Define the get customer tool."""
    return Tool(
        name="customer_get",
        description="Get detailed information about a specific customer",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Customer ID"}
            }
        }
    )


def create_customer_tool() -> Tool:
    """Define the create customer tool."""
    return Tool(
        name="customer_create",
        description="Create a new customer",
        inputSchema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "description": "Customer name"},
                "number": {"type": "string", "description": "Customer number"},
                "comment": {"type": "string", "description": "Customer comment"},
                "visible": {"type": "boolean", "description": "Whether customer is visible"},
                "billable": {"type": "boolean", "description": "Whether customer is billable"},
                "budget": {"type": "number", "description": "Customer budget"},
                "timeBudget": {"type": "integer", "description": "Time budget in seconds"},
                "color": {"type": "string", "description": "Customer color (hex format)"},
                "country": {"type": "string", "description": "Country code"},
                "currency": {"type": "string", "description": "Currency code"},
                "phone": {"type": "string", "description": "Phone number"},
                "fax": {"type": "string", "description": "Fax number"},
                "mobile": {"type": "string", "description": "Mobile number"},
                "email": {"type": "string", "format": "email", "description": "Email address"},
                "homepage": {"type": "string", "description": "Homepage URL"},
                "address": {"type": "string", "description": "Address"},
                "contact": {"type": "string", "description": "Contact person"},
                "company": {"type": "string", "description": "Company name"},
                "vatId": {"type": "string", "description": "VAT ID"}
            }
        }
    )


def update_customer_tool() -> Tool:
    """Define the update customer tool."""
    return Tool(
        name="customer_update",
        description="Update an existing customer",
        inputSchema={
            "type": "object",
            "required": ["id", "name"],
            "properties": {
                "id": {"type": "integer", "description": "Customer ID to update"},
                "name": {"type": "string", "description": "Customer name"},
                "number": {"type": "string", "description": "Customer number"},
                "comment": {"type": "string", "description": "Customer comment"},
                "visible": {"type": "boolean", "description": "Whether customer is visible"},
                "billable": {"type": "boolean", "description": "Whether customer is billable"},
                "budget": {"type": "number", "description": "Customer budget"},
                "timeBudget": {"type": "integer", "description": "Time budget in seconds"},
                "color": {"type": "string", "description": "Customer color (hex format)"},
                "country": {"type": "string", "description": "Country code"},
                "currency": {"type": "string", "description": "Currency code"},
                "phone": {"type": "string", "description": "Phone number"},
                "fax": {"type": "string", "description": "Fax number"},
                "mobile": {"type": "string", "description": "Mobile number"},
                "email": {"type": "string", "format": "email", "description": "Email address"},
                "homepage": {"type": "string", "description": "Homepage URL"},
                "address": {"type": "string", "description": "Address"},
                "contact": {"type": "string", "description": "Contact person"},
                "company": {"type": "string", "description": "Company name"},
                "vatId": {"type": "string", "description": "VAT ID"}
            }
        }
    )


def delete_customer_tool() -> Tool:
    """Define the delete customer tool."""
    return Tool(
        name="customer_delete",
        description="Delete a customer (WARNING: Deletes ALL linked projects, activities, and timesheets)",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Customer ID to delete"}
            }
        }
    )


def get_customer_rates_tool() -> Tool:
    """Define the get customer rates tool."""
    return Tool(
        name="customer_rates_list",
        description="Get rates for a customer",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Customer ID"}
            }
        }
    )


def add_customer_rate_tool() -> Tool:
    """Define the add customer rate tool."""
    return Tool(
        name="customer_rate_add",
        description="Add a rate for a customer",
        inputSchema={
            "type": "object",
            "required": ["id", "rate"],
            "properties": {
                "id": {"type": "integer", "description": "Customer ID"},
                "user": {"type": "integer", "description": "User ID (optional, for user-specific rates)"},
                "rate": {"type": "number", "description": "Rate amount"},
                "internalRate": {"type": "number", "description": "Internal rate amount"},
                "isFixed": {"type": "boolean", "description": "Whether this is a fixed rate"}
            }
        }
    )


def delete_customer_rate_tool() -> Tool:
    """Define the delete customer rate tool."""
    return Tool(
        name="customer_rate_delete",
        description="Delete a rate for a customer",
        inputSchema={
            "type": "object",
            "required": ["id", "rate_id"],
            "properties": {
                "id": {"type": "integer", "description": "Customer ID"},
                "rate_id": {"type": "integer", "description": "Rate ID to delete"}
            }
        }
    )


def update_customer_meta_tool() -> Tool:
    """Define the update customer meta field tool."""
    return Tool(
        name="customer_meta_update",
        description="Update a customer's custom field",
        inputSchema={
            "type": "object",
            "required": ["id", "name", "value"],
            "properties": {
                "id": {"type": "integer", "description": "Customer ID"},
                "name": {"type": "string", "description": "Custom field name"},
                "value": {"type": "string", "description": "Custom field value"}
            }
        }
    )


# Tool handlers

async def handle_list_customers(client: KimaiClient, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
    """Handle listing customers."""
    filters = CustomerFilter()
    
    if arguments:
        # Parse filters
        if 'visible' in arguments:
            filters.visible = arguments['visible']
        if 'order' in arguments:
            filters.order = arguments['order']
        if 'orderBy' in arguments:
            filters.order_by = arguments['orderBy']
        if 'term' in arguments:
            filters.term = arguments['term']
    
    customers = await client.get_customers(filters)
    
    if not customers:
        return [TextContent(type="text", text="No customers found matching the criteria.")]
    
    # Format results
    results = []
    for cust in customers:
        visibility = "👁️ Visible" if cust.visible else "🚫 Hidden"
        billable = "💰 Billable" if cust.billable else "🆓 Non-billable"
        
        result = f"""ID: {cust.id} - {cust.name} {visibility}
Number: {cust.number or '(none)'}
{billable}
Comment: {cust.comment or '(no comment)'}
Color: {cust.color or '(default)'}
---"""
        results.append(result)
    
    summary = f"Found {len(customers)} customer(s):\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_get_customer(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle getting a specific customer."""
    customer_id = arguments['id']
    cust = await client.get_customer(customer_id)
    
    visibility = "👁️ Visible" if cust.visible else "🚫 Hidden"
    billable = "💰 Billable" if cust.billable else "🆓 Non-billable"
    
    result = f"""Customer #{cust.id}: {cust.name} {visibility}
Number: {cust.number or '(none)'}
Status: {billable}
Comment: {cust.comment or '(no comment)'}
Color: {cust.color or '(default)'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_create_customer(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle creating a new customer."""
    customer_data = {"name": arguments["name"]}
    
    # Optional fields
    optional_fields = [
        'number', 'comment', 'visible', 'billable', 'budget', 'timeBudget', 
        'color', 'country', 'currency', 'phone', 'fax', 'mobile', 
        'email', 'homepage', 'address', 'contact', 'company', 'vatId'
    ]
    
    for field in optional_fields:
        if field in arguments:
            if field == 'timeBudget':
                customer_data['time_budget'] = arguments[field]
            elif field == 'vatId':
                customer_data['vat_id'] = arguments[field]
            else:
                customer_data[field] = arguments[field]
    
    customer_form = CustomerEditForm(**customer_data)
    customer = await client.create_customer(customer_form)
    
    visibility = "👁️ Visible" if customer.visible else "🚫 Hidden"
    billable = "💰 Billable" if customer.billable else "🆓 Non-billable"
    
    result = f"""Customer created successfully! {visibility}

ID: {customer.id}
Name: {customer.name}
Number: {customer.number or '(none)'}
Status: {billable}
Comment: {customer.comment or '(no comment)'}
Color: {customer.color or '(default)'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_update_customer(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle updating an existing customer."""
    customer_id = arguments.pop('id')
    customer_data = {"name": arguments["name"]}
    
    # Optional fields
    optional_fields = [
        'number', 'comment', 'visible', 'billable', 'budget', 'timeBudget', 
        'color', 'country', 'currency', 'phone', 'fax', 'mobile', 
        'email', 'homepage', 'address', 'contact', 'company', 'vatId'
    ]
    
    for field in optional_fields:
        if field in arguments:
            if field == 'timeBudget':
                customer_data['time_budget'] = arguments[field]
            elif field == 'vatId':
                customer_data['vat_id'] = arguments[field]
            else:
                customer_data[field] = arguments[field]
    
    customer_form = CustomerEditForm(**customer_data)
    customer = await client.update_customer(customer_id, customer_form)
    
    visibility = "👁️ Visible" if customer.visible else "🚫 Hidden"
    billable = "💰 Billable" if customer.billable else "🆓 Non-billable"
    
    result = f"""Customer updated successfully! {visibility}

ID: {customer.id}
Name: {customer.name}
Number: {customer.number or '(none)'}
Status: {billable}
Comment: {customer.comment or '(no comment)'}
Color: {customer.color or '(default)'}"""
    
    return [TextContent(type="text", text=result)]


async def handle_delete_customer(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle deleting a customer."""
    customer_id = arguments['id']
    await client.delete_customer(customer_id)
    
    return [TextContent(type="text", text=f"Customer #{customer_id} deleted successfully. WARNING: All linked projects, activities, and timesheets have been deleted.")]


async def handle_get_customer_rates(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle getting customer rates."""
    customer_id = arguments['id']
    rates = await client.get_customer_rates(customer_id)
    
    if not rates:
        return [TextContent(type="text", text=f"No rates found for customer #{customer_id}.")]
    
    results = []
    for rate in rates:
        user_info = f" (User: {rate.user.username})" if rate.user else " (Default)"
        fixed_info = " [Fixed Rate]" if rate.is_fixed else ""
        internal_info = f" | Internal: {rate.internal_rate:.2f}" if rate.internal_rate else ""
        
        result = f"""Rate ID: {rate.id}{user_info}{fixed_info}
Amount: {rate.rate:.2f}{internal_info}
---"""
        results.append(result)
    
    summary = f"Found {len(rates)} rate(s) for customer #{customer_id}:\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_add_customer_rate(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle adding a customer rate."""
    customer_id = arguments.pop('id')
    
    rate_data = {"rate": arguments["rate"]}
    
    # Optional fields
    if 'user' in arguments:
        rate_data['user'] = arguments['user']
    if 'internalRate' in arguments:
        rate_data['internal_rate'] = arguments['internalRate']
    if 'isFixed' in arguments:
        rate_data['is_fixed'] = arguments['isFixed']
    
    rate_form = RateForm(**rate_data)
    rate = await client.add_customer_rate(customer_id, rate_form)
    
    user_info = f" for user {rate.user.username}" if rate.user else " (default rate)"
    fixed_info = " [Fixed Rate]" if rate.is_fixed else ""
    internal_info = f" | Internal: {rate.internal_rate:.2f}" if rate.internal_rate else ""
    
    result = f"""Rate added successfully!{fixed_info}

Rate ID: {rate.id}
Customer ID: {customer_id}{user_info}
Amount: {rate.rate:.2f}{internal_info}"""
    
    return [TextContent(type="text", text=result)]


async def handle_delete_customer_rate(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle deleting a customer rate."""
    customer_id = arguments['id']
    rate_id = arguments['rate_id']
    
    await client.delete_customer_rate(customer_id, rate_id)
    
    return [TextContent(type="text", text=f"Rate #{rate_id} deleted successfully from customer #{customer_id}.")]


async def handle_update_customer_meta(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle updating a customer's custom field."""
    customer_id = arguments['id']
    
    meta_field = MetaFieldForm(
        name=arguments['name'],
        value=arguments['value']
    )
    
    customer = await client.update_customer_meta(customer_id, meta_field)
    
    result = f"""Custom field updated successfully!

Customer: {customer.name} (ID: {customer.id})
Field: {arguments['name']} = {arguments['value']}"""
    
    return [TextContent(type="text", text=result)]