"""Invoice query MCP tools."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from mcp.types import Tool, TextContent

from ..client import KimaiClient
from ..models import InvoiceFilter


# Tool definitions

def list_invoices_tool() -> Tool:
    """Define the list invoices tool."""
    return Tool(
        name="invoice_list",
        description="List invoices with optional filters",
        inputSchema={
            "type": "object",
            "properties": {
                "begin": {"type": "string", "format": "date", "description": "Start date filter (YYYY-MM-DD)"},
                "end": {"type": "string", "format": "date", "description": "End date filter (YYYY-MM-DD)"},
                "customers": {"type": "array", "items": {"type": "integer"}, "description": "Customer IDs to filter by"},
                "status": {"type": "array", "items": {"type": "string", "enum": ["new", "pending", "paid", "canceled"]}, "description": "Invoice status filter"},
                "page": {"type": "integer", "description": "Page number for pagination"},
                "size": {"type": "integer", "description": "Number of items per page"}
            }
        }
    )


def get_invoice_tool() -> Tool:
    """Define the get invoice tool."""
    return Tool(
        name="invoice_get",
        description="Get detailed information about a specific invoice",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Invoice ID to retrieve"}
            }
        }
    )


# Tool handlers

async def handle_list_invoices(client: KimaiClient, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
    """Handle listing invoices."""
    filters = InvoiceFilter()
    
    if arguments:
        if 'begin' in arguments:
            filters.begin = datetime.fromisoformat(arguments['begin'])
        if 'end' in arguments:
            filters.end = datetime.fromisoformat(arguments['end'])
        if 'customers' in arguments:
            filters.customers = arguments['customers']
        if 'status' in arguments:
            filters.status = arguments['status']
        if 'page' in arguments:
            filters.page = arguments['page']
        if 'size' in arguments:
            filters.size = arguments['size']
    
    invoices = await client.get_invoices(filters)
    
    if not invoices:
        return [TextContent(type="text", text="No invoices found matching the criteria.")]
    
    # Format results
    results = []
    for invoice in invoices:
        status_icons = {
            "new": "🆕",
            "pending": "⏳", 
            "paid": "✅",
            "canceled": "❌"
        }
        status_icon = status_icons.get(invoice.status, "❓")
        
        # Format payment date
        payment_info = ""
        if invoice.payment_date:
            payment_info = f"\nPaid: {invoice.payment_date.strftime('%Y-%m-%d')}"
        elif invoice.status == "pending":
            due_date = invoice.created_at.date() if invoice.due_days == 0 else None
            if due_date:
                payment_info = f"\nDue: Immediately"
            else:
                payment_info = f"\nDue: {invoice.due_days} days from creation"
        
        # Format tax info
        tax_info = ""
        if invoice.tax > 0:
            tax_info = f" (Tax: {invoice.tax:.2f} {invoice.currency})"
        if invoice.vat > 0:
            vat_percentage = (invoice.vat * 100) if invoice.vat <= 1 else invoice.vat
            tax_info += f" (VAT: {vat_percentage:.1f}%)"
        
        result = f"""ID: {invoice.id} {status_icon}
Number: {invoice.invoice_number}
Customer: {invoice.customer.name} (ID: {invoice.customer.id})
Created: {invoice.created_at.strftime('%Y-%m-%d')}
Total: {invoice.total:.2f} {invoice.currency}{tax_info}
Status: {invoice.status.title()}{payment_info}
---"""
        results.append(result)
    
    summary = f"Found {len(invoices)} invoice(s):\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_get_invoice(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle getting a specific invoice."""
    invoice_id = arguments['id']
    invoice = await client.get_invoice(invoice_id)
    
    status_icons = {
        "new": "🆕",
        "pending": "⏳", 
        "paid": "✅",
        "canceled": "❌"
    }
    status_icon = status_icons.get(invoice.status, "❓")
    
    # Format payment information
    payment_info = ""
    if invoice.payment_date:
        payment_info = f"Payment Date: {invoice.payment_date.strftime('%Y-%m-%d')}"
    elif invoice.status == "pending":
        if invoice.due_days == 0:
            payment_info = "Due: Immediately"
        else:
            payment_info = f"Due: {invoice.due_days} days from creation"
    else:
        payment_info = f"Payment Terms: {invoice.due_days} days"
    
    # Format tax information
    tax_details = []
    if invoice.tax > 0:
        tax_details.append(f"Tax Amount: {invoice.tax:.2f} {invoice.currency}")
    if invoice.vat > 0:
        vat_percentage = (invoice.vat * 100) if invoice.vat <= 1 else invoice.vat
        tax_details.append(f"VAT Rate: {vat_percentage:.1f}%")
    
    tax_info = "\n".join(tax_details) if tax_details else "No tax applied"
    
    # Format meta fields if present
    meta_info = ""
    if invoice.meta_fields:
        meta_details = []
        for field in invoice.meta_fields:
            if isinstance(field, dict) and 'name' in field and 'value' in field:
                meta_details.append(f"  • {field['name']}: {field['value']}")
        if meta_details:
            meta_info = f"\nCustom Fields:\n" + "\n".join(meta_details)
    
    result = f"""Invoice Details {status_icon}

ID: {invoice.id}
Invoice Number: {invoice.invoice_number}
Status: {invoice.status.title()}

Customer: {invoice.customer.name} (ID: {invoice.customer.id})
Created By: {invoice.user.username} (ID: {invoice.user.id})
Created Date: {invoice.created_at.strftime('%Y-%m-%d %H:%M')}

Financial Details:
Total Amount: {invoice.total:.2f} {invoice.currency}
{tax_info}
{payment_info}

Comment: {invoice.comment or 'No comment'}{meta_info}"""
    
    return [TextContent(type="text", text=result)]