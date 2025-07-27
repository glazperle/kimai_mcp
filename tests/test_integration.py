#!/usr/bin/env python3
"""Integration tests for Kimai MCP server."""

import pytest
import asyncio
import os
import sys
from unittest.mock import patch, AsyncMock

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from kimai_mcp.server import KimaiMCPServer


class TestKimaiMCPIntegration:
    """Integration tests for the complete MCP server."""

    @pytest.mark.asyncio
    async def test_full_tool_registration_and_execution(self):
        """Test that all tools are registered and can be called."""
        server = KimaiMCPServer()
        
        # Get all registered tools
        tools = await server._list_tools()
        
        # Verify we have tools from all categories
        tool_names = {tool.name for tool in tools}
        
        expected_categories = {
            'timesheet_', 'project_', 'activity_', 'customer_',
            'user_', 'team_', 'absence_', 'tag_', 'invoice_',
            'calendar_', 'holiday_'
        }
        
        for category in expected_categories:
            category_tools = [name for name in tool_names if name.startswith(category)]
            assert len(category_tools) > 0, f"No tools found for category: {category}"
        
        # Test that tools have proper schemas
        for tool in tools:
            assert hasattr(tool, 'name')
            assert hasattr(tool, 'description')
            assert hasattr(tool, 'inputSchema')
            assert tool.name
            assert tool.description
            assert isinstance(tool.inputSchema, dict)

    @pytest.mark.asyncio
    async def test_tool_call_with_mock_client(self):
        """Test tool calling with mocked client to avoid real API calls."""
        server = KimaiMCPServer()
        
        # Mock the client
        mock_client = AsyncMock()
        mock_client.get_timesheets.return_value = []
        server.client = mock_client
        
        # Test calling a tool
        result = await server._call_tool("timesheet_list", {})
        
        assert len(result) == 1
        assert result[0].type == "text"
        assert "No timesheets found" in result[0].text
        mock_client.get_timesheets.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_handling_in_tool_calls(self):
        """Test error handling during tool execution."""
        server = KimaiMCPServer()
        
        # Mock the client to raise an error
        mock_client = AsyncMock()
        from kimai_mcp.client import KimaiAPIError
        mock_client.get_timesheets.side_effect = KimaiAPIError("Test error", 500)
        server.client = mock_client
        
        # Test calling a tool that will error
        result = await server._call_tool("timesheet_list", {})
        
        assert len(result) == 1
        assert result[0].type == "text"
        assert "Kimai API Error" in result[0].text
        assert "Test error" in result[0].text

    @pytest.mark.asyncio
    async def test_unknown_tool_handling(self):
        """Test handling of unknown tool calls."""
        server = KimaiMCPServer()
        
        result = await server._call_tool("unknown_tool", {})
        
        assert len(result) == 1
        assert result[0].type == "text"
        assert "Unknown tool: unknown_tool" in result[0].text

    def test_configuration_validation(self):
        """Test configuration validation."""
        # Test missing URL
        with pytest.raises(ValueError, match="Kimai URL is required"):
            KimaiMCPServer(base_url=None, api_token="test-token")
        
        # Test missing token
        with pytest.raises(ValueError, match="Kimai API token is required"):
            KimaiMCPServer(base_url="https://test.com", api_token=None)

    @pytest.mark.asyncio
    async def test_client_initialization(self):
        """Test client initialization."""
        server = KimaiMCPServer()
        
        # Client should be None initially
        assert server.client is None
        
        # After ensuring client, it should be initialized
        await server._ensure_client()
        assert server.client is not None
        
        # Should not create a new client if one exists
        original_client = server.client
        await server._ensure_client()
        assert server.client is original_client

    @pytest.mark.asyncio
    async def test_comprehensive_tool_coverage(self):
        """Test that we have comprehensive tool coverage."""
        server = KimaiMCPServer()
        tools = await server._list_tools()
        tool_names = {tool.name for tool in tools}
        
        # Check for all major tool categories with expected counts
        expected_tools = {
            # Timesheet tools
            'timesheet_list', 'timesheet_get', 'timesheet_create', 'timesheet_update',
            'timesheet_delete', 'timesheet_start', 'timesheet_stop', 'timesheet_active',
            'timesheet_recent', 'timesheet_restart', 'timesheet_duplicate',
            'timesheet_export_toggle', 'timesheet_meta_update',
            
            # Project tools (including new CRUD)
            'project_list', 'project_get', 'project_create', 'project_update',
            'project_delete', 'project_rates_list', 'project_rate_add',
            'project_rate_delete', 'project_meta_update',
            
            # Activity tools (including new CRUD)
            'activity_list', 'activity_get', 'activity_create', 'activity_update',
            'activity_delete', 'activity_rates_list', 'activity_rate_add',
            'activity_rate_delete', 'activity_meta_update',
            
            # Customer tools
            'customer_list', 'customer_get', 'customer_create', 'customer_update',
            'customer_delete', 'customer_rates_list', 'customer_rate_add',
            'customer_rate_delete', 'customer_meta_update',
            
            # User tools
            'user_list', 'user_get', 'user_current', 'user_create', 'user_update',
            
            # Team tools (including access control)
            'team_list', 'team_get', 'team_create', 'team_update', 'team_delete',
            'team_add_member', 'team_remove_member',
            'team_grant_customer_access', 'team_revoke_customer_access',
            'team_grant_project_access', 'team_revoke_project_access',
            'team_grant_activity_access', 'team_revoke_activity_access',
            
            # Absence tools
            'absence_list', 'absence_types', 'absence_create', 'absence_delete',
            'absence_approve', 'absence_reject',
            
            # Tag tools
            'tag_list', 'tag_create', 'tag_delete',
            
            # Invoice tools
            'invoice_list', 'invoice_get',
            
            # Calendar tools
            'calendar_absences', 'calendar_holidays',
            
            # Holiday tools
            'holiday_list', 'holiday_delete',
        }
        
        missing_tools = expected_tools - tool_names
        assert not missing_tools, f"Missing expected tools: {missing_tools}"
        
        # Verify we have a substantial number of tools
        assert len(tool_names) >= 75, f"Expected at least 75 tools, got {len(tool_names)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])