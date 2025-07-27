"""Kimai MCP Server implementation."""

import os
import sys
import asyncio
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.types import (
    Tool, TextContent, ImageContent, EmbeddedResource,
    LoggingLevel
)
from pydantic import BaseModel, Field
from .client import KimaiClient, KimaiAPIError
from .models import (
    TimesheetEditForm, TimesheetFilter,
    ProjectFilter, ActivityFilter, CustomerFilter
)
from .tools import timesheet, project, activity, customer, absence, user, team, tag, invoice, calendar, holiday

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KimaiMCPServer:
    """Kimai MCP Server."""
    
    def __init__(self, base_url: Optional[str] = None, api_token: Optional[str] = None, default_user_id: Optional[str] = None):
        """Initialize the Kimai MCP server.
        
        Args:
            base_url: Kimai server URL (can also be set via KIMAI_URL env var)
            api_token: API authentication token (can also be set via KIMAI_API_TOKEN env var)
            default_user_id: Default user ID for operations (can also be set via KIMAI_DEFAULT_USER env var)
        """
        self.server = Server("kimai-mcp")
        self.client: Optional[KimaiClient] = None
        
        # Register handlers
        self.server.list_tools()(self._list_tools)
        self.server.call_tool()(self._call_tool)
        
        # Configuration - prefer arguments, fallback to environment variables
        self.base_url = (base_url or os.getenv("KIMAI_URL", "")).rstrip('/')
        self.api_token = api_token or os.getenv("KIMAI_API_TOKEN", "")
        self.default_user_id = default_user_id or os.getenv("KIMAI_DEFAULT_USER")
        
        # Validate configuration
        if not self.base_url:
            raise ValueError("Kimai URL is required (provide via constructor argument or KIMAI_URL environment variable)")
        if not self.api_token:
            raise ValueError("Kimai API token is required (provide via constructor argument or KIMAI_API_TOKEN environment variable)")
    
    async def _ensure_client(self):
        """Ensure the Kimai client is initialized."""
        if not self.client:
            self.client = KimaiClient(self.base_url, self.api_token)
    
    async def _list_tools(self) -> List[Tool]:
        """List available MCP tools."""
        tools = []
        
        # Timesheet tools
        tools.extend([
            timesheet.list_timesheets_tool(),
            timesheet.get_timesheet_tool(),
            timesheet.create_timesheet_tool(),
            timesheet.update_timesheet_tool(),
            timesheet.delete_timesheet_tool(),
            timesheet.start_timer_tool(),
            timesheet.stop_timer_tool(),
            timesheet.get_active_timers_tool(),
            timesheet.get_recent_activities_tool(),
            timesheet.restart_timesheet_tool(),
            timesheet.duplicate_timesheet_tool(),
            timesheet.toggle_timesheet_export_tool(),
            timesheet.update_timesheet_meta_tool(),
        ])
        
        # Project tools
        tools.extend([
            project.list_projects_tool(),
            project.get_project_tool(),
            project.create_project_tool(),
            project.update_project_tool(),
            project.delete_project_tool(),
            project.get_project_rates_tool(),
            project.add_project_rate_tool(),
            project.delete_project_rate_tool(),
            project.update_project_meta_tool(),
        ])
        
        # Activity tools
        tools.extend([
            activity.list_activities_tool(),
            activity.get_activity_tool(),
            activity.create_activity_tool(),
            activity.update_activity_tool(),
            activity.delete_activity_tool(),
            activity.get_activity_rates_tool(),
            activity.add_activity_rate_tool(),
            activity.delete_activity_rate_tool(),
            activity.update_activity_meta_tool(),
        ])
        
        # Customer tools
        tools.extend([
            customer.list_customers_tool(),
            customer.get_customer_tool(),
            customer.create_customer_tool(),
            customer.update_customer_tool(),
            customer.delete_customer_tool(),
            customer.get_customer_rates_tool(),
            customer.add_customer_rate_tool(),
            customer.delete_customer_rate_tool(),
            customer.update_customer_meta_tool(),
        ])
        
        # Absence tools
        tools.extend([
            absence.list_absences_tool(),
            absence.get_absence_types_tool(),
            absence.create_absence_tool(),
            absence.delete_absence_tool(),
            absence.approve_absence_tool(),
            absence.reject_absence_tool(),
        ])
        
        # User tools
        tools.extend([
            user.list_users_tool(),
            user.get_user_tool(),
            user.get_current_user_tool(),
            user.create_user_tool(),
            user.update_user_tool(),
        ])
        
        # Team tools
        tools.extend([
            team.list_teams_tool(),
            team.get_team_tool(),
            team.create_team_tool(),
            team.update_team_tool(),
            team.delete_team_tool(),
            team.add_team_member_tool(),
            team.remove_team_member_tool(),
            team.grant_team_customer_access_tool(),
            team.revoke_team_customer_access_tool(),
            team.grant_team_project_access_tool(),
            team.revoke_team_project_access_tool(),
            team.grant_team_activity_access_tool(),
            team.revoke_team_activity_access_tool(),
        ])
        
        # Tag tools
        tools.extend([
            tag.list_tags_tool(),
            tag.create_tag_tool(),
            tag.delete_tag_tool(),
        ])
        
        # Invoice tools
        tools.extend([
            invoice.list_invoices_tool(),
            invoice.get_invoice_tool(),
        ])
        
        # Calendar tools
        tools.extend([
            calendar.get_absences_calendar_tool(),
            calendar.get_public_holidays_calendar_tool(),
        ])
        
        # Public holiday tools
        tools.extend([
            holiday.list_public_holidays_tool(),
            holiday.delete_public_holiday_tool(),
        ])
        
        return tools
    
    async def _call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
        """Handle tool calls."""
        await self._ensure_client()
        
        try:
            # Timesheet tools
            if name == "timesheet_list":
                return await timesheet.handle_list_timesheets(self.client, arguments)
            elif name == "timesheet_get":
                return await timesheet.handle_get_timesheet(self.client, arguments)
            elif name == "timesheet_create":
                return await timesheet.handle_create_timesheet(self.client, arguments, self.default_user_id)
            elif name == "timesheet_update":
                return await timesheet.handle_update_timesheet(self.client, arguments)
            elif name == "timesheet_delete":
                return await timesheet.handle_delete_timesheet(self.client, arguments)
            elif name == "timesheet_start":
                return await timesheet.handle_start_timer(self.client, arguments, self.default_user_id)
            elif name == "timesheet_stop":
                return await timesheet.handle_stop_timer(self.client, arguments)
            elif name == "timesheet_active":
                return await timesheet.handle_get_active_timers(self.client)
            elif name == "timesheet_recent":
                return await timesheet.handle_get_recent_activities(self.client, arguments)
            elif name == "timesheet_restart":
                return await timesheet.handle_restart_timesheet(self.client, arguments)
            elif name == "timesheet_duplicate":
                return await timesheet.handle_duplicate_timesheet(self.client, arguments)
            elif name == "timesheet_export_toggle":
                return await timesheet.handle_toggle_timesheet_export(self.client, arguments)
            elif name == "timesheet_meta_update":
                return await timesheet.handle_update_timesheet_meta(self.client, arguments)
            
            # Project tools
            elif name == "project_list":
                return await project.handle_list_projects(self.client, arguments)
            elif name == "project_get":
                return await project.handle_get_project(self.client, arguments)
            elif name == "project_create":
                return await project.handle_create_project(self.client, arguments)
            elif name == "project_update":
                return await project.handle_update_project(self.client, arguments)
            elif name == "project_delete":
                return await project.handle_delete_project(self.client, arguments)
            elif name == "project_rates_list":
                return await project.handle_get_project_rates(self.client, arguments)
            elif name == "project_rate_add":
                return await project.handle_add_project_rate(self.client, arguments)
            elif name == "project_rate_delete":
                return await project.handle_delete_project_rate(self.client, arguments)
            elif name == "project_meta_update":
                return await project.handle_update_project_meta(self.client, arguments)
            
            # Activity tools
            elif name == "activity_list":
                return await activity.handle_list_activities(self.client, arguments)
            elif name == "activity_get":
                return await activity.handle_get_activity(self.client, arguments)
            elif name == "activity_create":
                return await activity.handle_create_activity(self.client, arguments)
            elif name == "activity_update":
                return await activity.handle_update_activity(self.client, arguments)
            elif name == "activity_delete":
                return await activity.handle_delete_activity(self.client, arguments)
            elif name == "activity_rates_list":
                return await activity.handle_get_activity_rates(self.client, arguments)
            elif name == "activity_rate_add":
                return await activity.handle_add_activity_rate(self.client, arguments)
            elif name == "activity_rate_delete":
                return await activity.handle_delete_activity_rate(self.client, arguments)
            elif name == "activity_meta_update":
                return await activity.handle_update_activity_meta(self.client, arguments)
            
            # Customer tools
            elif name == "customer_list":
                return await customer.handle_list_customers(self.client, arguments)
            elif name == "customer_get":
                return await customer.handle_get_customer(self.client, arguments)
            elif name == "customer_create":
                return await customer.handle_create_customer(self.client, arguments)
            elif name == "customer_update":
                return await customer.handle_update_customer(self.client, arguments)
            elif name == "customer_delete":
                return await customer.handle_delete_customer(self.client, arguments)
            elif name == "customer_rates_list":
                return await customer.handle_get_customer_rates(self.client, arguments)
            elif name == "customer_rate_add":
                return await customer.handle_add_customer_rate(self.client, arguments)
            elif name == "customer_rate_delete":
                return await customer.handle_delete_customer_rate(self.client, arguments)
            elif name == "customer_meta_update":
                return await customer.handle_update_customer_meta(self.client, arguments)
            
            # Absence tools
            elif name == "absence_list":
                return await absence.handle_list_absences(self.client, arguments)
            elif name == "absence_types":
                return await absence.handle_get_absence_types(self.client, arguments)
            elif name == "absence_create":
                return await absence.handle_create_absence(self.client, arguments, self.default_user_id)
            elif name == "absence_delete":
                return await absence.handle_delete_absence(self.client, arguments)
            elif name == "absence_approve":
                return await absence.handle_approve_absence(self.client, arguments)
            elif name == "absence_reject":
                return await absence.handle_reject_absence(self.client, arguments)
            
            # User tools
            elif name == "user_list":
                return await user.handle_list_users(self.client, arguments)
            elif name == "user_get":
                return await user.handle_get_user(self.client, arguments)
            elif name == "user_current":
                return await user.handle_get_current_user(self.client)
            elif name == "user_create":
                return await user.handle_create_user(self.client, arguments)
            elif name == "user_update":
                return await user.handle_update_user(self.client, arguments)
            
            # Team tools
            elif name == "team_list":
                return await team.handle_list_teams(self.client)
            elif name == "team_get":
                return await team.handle_get_team(self.client, arguments)
            elif name == "team_create":
                return await team.handle_create_team(self.client, arguments)
            elif name == "team_update":
                return await team.handle_update_team(self.client, arguments)
            elif name == "team_delete":
                return await team.handle_delete_team(self.client, arguments)
            elif name == "team_add_member":
                return await team.handle_add_team_member(self.client, arguments)
            elif name == "team_remove_member":
                return await team.handle_remove_team_member(self.client, arguments)
            elif name == "team_grant_customer_access":
                return await team.handle_grant_team_customer_access(self.client, arguments)
            elif name == "team_revoke_customer_access":
                return await team.handle_revoke_team_customer_access(self.client, arguments)
            elif name == "team_grant_project_access":
                return await team.handle_grant_team_project_access(self.client, arguments)
            elif name == "team_revoke_project_access":
                return await team.handle_revoke_team_project_access(self.client, arguments)
            elif name == "team_grant_activity_access":
                return await team.handle_grant_team_activity_access(self.client, arguments)
            elif name == "team_revoke_activity_access":
                return await team.handle_revoke_team_activity_access(self.client, arguments)
            
            # Tag tools
            elif name == "tag_list":
                return await tag.handle_list_tags(self.client, arguments)
            elif name == "tag_create":
                return await tag.handle_create_tag(self.client, arguments)
            elif name == "tag_delete":
                return await tag.handle_delete_tag(self.client, arguments)
            
            # Invoice tools
            elif name == "invoice_list":
                return await invoice.handle_list_invoices(self.client, arguments)
            elif name == "invoice_get":
                return await invoice.handle_get_invoice(self.client, arguments)
            
            # Calendar tools
            elif name == "calendar_absences":
                return await calendar.handle_get_absences_calendar(self.client, arguments)
            elif name == "calendar_holidays":
                return await calendar.handle_get_public_holidays_calendar(self.client, arguments)
            
            # Public holiday tools
            elif name == "holiday_list":
                return await holiday.handle_list_public_holidays(self.client, arguments)
            elif name == "holiday_delete":
                return await holiday.handle_delete_public_holiday(self.client, arguments)
            
            else:
                return [TextContent(
                    type="text",
                    text=f"Unknown tool: {name}"
                )]
                
        except KimaiAPIError as e:
            return [TextContent(
                type="text",
                text=f"Kimai API Error: {e.message} (Status: {e.status_code})"
            )]
        except Exception as e:
            logger.error(f"Error calling tool {name}: {str(e)}", exc_info=True)
            return [TextContent(
                type="text",
                text=f"Error: {str(e)}"
            )]
    
    async def run(self):
        """Run the MCP server."""
        # Initialize client
        await self._ensure_client()
        
        # Verify connection
        try:
            version = await self.client.get_version()
            logger.info(f"Connected to Kimai {version.version}")
        except Exception as e:
            logger.error(f"Failed to connect to Kimai: {str(e)}")
            raise
        
        # Configure server options
        options = InitializationOptions(
            server_name="kimai-mcp",
            server_version="0.1.0",
            capabilities=self.server.get_capabilities(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            ),
        )
        
        # Run the server
        from mcp.server.stdio import stdio_server
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                options
            )
    
    async def cleanup(self):
        """Clean up resources."""
        if self.client:
            await self.client.close()


async def main():
    """Main entry point."""
    # Get configuration from command line arguments if provided
    # This allows configuration to be passed from MCP client (like Claude Desktop)
    base_url = None
    api_token = None
    default_user_id = None
    
    # Parse command line arguments for configuration
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.startswith("--kimai-url="):
                base_url = arg.split("=", 1)[1]
            elif arg.startswith("--kimai-token="):
                api_token = arg.split("=", 1)[1]
            elif arg.startswith("--kimai-user="):
                default_user_id = arg.split("=", 1)[1]
    
    server = KimaiMCPServer(
        base_url=base_url,
        api_token=api_token,
        default_user_id=default_user_id
    )
    try:
        await server.run()
    finally:
        await server.cleanup()


if __name__ == "__main__":
    asyncio.run(main())