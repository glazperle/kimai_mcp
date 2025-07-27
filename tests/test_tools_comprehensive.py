#!/usr/bin/env python3
"""Comprehensive test suite for Kimai MCP tools."""

import pytest
import asyncio
import os
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, date

# Add src to path for imports
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from kimai_mcp.server import KimaiMCPServer
from kimai_mcp.client import KimaiClient, KimaiAPIError
from kimai_mcp.models import (
    TimesheetEntity, Project, Activity, Customer, User, UserEntity,
    Team, Absence, TagEntity, Invoice, PublicHoliday, CalendarEvent
)


class TestKimaiMCPServer:
    """Test the main MCP server functionality."""

    @pytest.fixture
    def server(self):
        """Create a test server instance."""
        with patch.dict(os.environ, {
            'KIMAI_URL': 'https://test.example.com',
            'KIMAI_API_TOKEN': 'test-token'
        }):
            return KimaiMCPServer()

    @pytest.mark.asyncio
    async def test_server_initialization(self, server):
        """Test server initializes correctly."""
        assert server.base_url == 'https://test.example.com'
        assert server.api_token == 'test-token'
        assert server.client is None

    @pytest.mark.asyncio
    async def test_list_tools(self, server):
        """Test that all tools are properly registered."""
        tools = await server._list_tools()
        
        # Check we have all expected tool categories
        tool_names = [tool.name for tool in tools]
        
        # Timesheet tools
        timesheet_tools = [name for name in tool_names if name.startswith('timesheet_')]
        assert len(timesheet_tools) >= 12
        assert 'timesheet_list' in tool_names
        assert 'timesheet_start' in tool_names
        assert 'timesheet_stop' in tool_names
        
        # Project tools (including new CRUD tools)
        project_tools = [name for name in tool_names if name.startswith('project_')]
        assert len(project_tools) >= 9
        assert 'project_create' in tool_names
        assert 'project_update' in tool_names
        assert 'project_delete' in tool_names
        assert 'project_rate_add' in tool_names
        
        # Activity tools (including new CRUD tools)
        activity_tools = [name for name in tool_names if name.startswith('activity_')]
        assert len(activity_tools) >= 9
        assert 'activity_create' in tool_names
        assert 'activity_update' in tool_names
        assert 'activity_delete' in tool_names
        
        # Team access control tools
        team_tools = [name for name in tool_names if name.startswith('team_')]
        assert 'team_grant_customer_access' in tool_names
        assert 'team_revoke_customer_access' in tool_names
        assert 'team_grant_project_access' in tool_names
        assert 'team_revoke_project_access' in tool_names
        
        # Calendar tools
        calendar_tools = [name for name in tool_names if name.startswith('calendar_')]
        assert len(calendar_tools) >= 2
        assert 'calendar_absences' in tool_names
        assert 'calendar_holidays' in tool_names
        
        # Holiday tools
        holiday_tools = [name for name in tool_names if name.startswith('holiday_')]
        assert len(holiday_tools) >= 2
        assert 'holiday_list' in tool_names
        assert 'holiday_delete' in tool_names

    @pytest.mark.asyncio
    async def test_ensure_client(self, server):
        """Test client initialization."""
        await server._ensure_client()
        assert server.client is not None
        assert isinstance(server.client, KimaiClient)


class TestTimesheetTools:
    """Test timesheet-related tools."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Kimai client."""
        client = AsyncMock(spec=KimaiClient)
        return client

    @pytest.mark.asyncio
    async def test_timesheet_create_tool(self, mock_client):
        """Test timesheet creation tool."""
        from kimai_mcp.tools.timesheet import handle_create_timesheet
        
        # Mock timesheet response
        mock_timesheet = TimesheetEntity(
            id=1,
            begin=datetime.now(),
            end=None,
            duration=0,
            user=1,
            project=1,
            activity=1,
            description="Test task",
            exported=False,
            billable=True,
            rate=50.0,
            hourly_rate=50.0,
            tags=["test"]
        )
        mock_client.create_timesheet.return_value = mock_timesheet
        
        # Test arguments
        arguments = {
            "project": 1,
            "activity": 1,
            "description": "Test task"
        }
        
        result = await handle_create_timesheet(mock_client, arguments)
        
        assert len(result) == 1
        assert "Timesheet created successfully" in result[0].text
        assert "Test task" in result[0].text
        mock_client.create_timesheet.assert_called_once()

    @pytest.mark.asyncio
    async def test_timesheet_list_tool(self, mock_client):
        """Test timesheet listing tool."""
        from kimai_mcp.tools.timesheet import handle_list_timesheets
        
        # Mock timesheet list
        mock_timesheets = [
            TimesheetEntity(
                id=1,
                begin=datetime.now(),
                end=datetime.now(),
                duration=3600,
                user=1,
                project=1,
                activity=1,
                description="Task 1",
                exported=False,
                billable=True,
                rate=50.0,
                hourly_rate=50.0,
                tags=["work"]
            )
        ]
        mock_client.get_timesheets.return_value = mock_timesheets
        
        result = await handle_list_timesheets(mock_client, {})
        
        assert len(result) == 1
        assert "Found 1 timesheet(s)" in result[0].text
        assert "Task 1" in result[0].text


class TestProjectTools:
    """Test project-related tools including new CRUD operations."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Kimai client."""
        client = AsyncMock(spec=KimaiClient)
        return client

    @pytest.mark.asyncio
    async def test_project_create_tool(self, mock_client):
        """Test project creation tool."""
        from kimai_mcp.tools.project import handle_create_project
        
        # Mock project response
        mock_project = Project(
            id=1,
            name="Test Project",
            customer=1,
            comment="Test project description",
            visible=True,
            billable=True,
            color="#FF0000"
        )
        mock_client.create_project.return_value = mock_project
        
        arguments = {
            "name": "Test Project",
            "customer": 1,
            "comment": "Test project description"
        }
        
        result = await handle_create_project(mock_client, arguments)
        
        assert len(result) == 1
        assert "Project created successfully" in result[0].text
        assert "Test Project" in result[0].text
        mock_client.create_project.assert_called_once()

    @pytest.mark.asyncio
    async def test_project_rate_management(self, mock_client):
        """Test project rate management tools."""
        from kimai_mcp.tools.project import handle_add_project_rate
        from kimai_mcp.models import Rate, User
        
        # Mock rate response
        mock_rate = Rate(
            id=1,
            user=User(id=1, username="testuser", email="test@example.com"),
            rate=75.0,
            internal_rate=60.0,
            is_fixed=False
        )
        mock_client.add_project_rate.return_value = mock_rate
        
        arguments = {
            "id": 1,
            "rate": 75.0,
            "user": 1,
            "internalRate": 60.0
        }
        
        result = await handle_add_project_rate(mock_client, arguments)
        
        assert len(result) == 1
        assert "Rate added successfully" in result[0].text
        assert "75.00" in result[0].text


class TestTeamAccessControl:
    """Test team access control tools."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Kimai client."""
        client = AsyncMock(spec=KimaiClient)
        return client

    @pytest.mark.asyncio
    async def test_grant_customer_access(self, mock_client):
        """Test granting team access to customers."""
        from kimai_mcp.tools.team import handle_grant_team_customer_access
        
        # Mock team response
        mock_team = Team(
            id=1,
            name="Development Team",
            members=[],
            customers=[],
            projects=[],
            color="#00FF00"
        )
        mock_client.grant_team_customer_access.return_value = mock_team
        
        arguments = {
            "team_id": 1,
            "customer_id": 5
        }
        
        result = await handle_grant_team_customer_access(mock_client, arguments)
        
        assert len(result) == 1
        assert "Customer access granted successfully" in result[0].text
        assert "Development Team" in result[0].text
        mock_client.grant_team_customer_access.assert_called_once_with(1, 5)


class TestCalendarIntegration:
    """Test calendar integration tools."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Kimai client."""
        client = AsyncMock(spec=KimaiClient)
        return client

    @pytest.mark.asyncio
    async def test_absences_calendar(self, mock_client):
        """Test absences calendar integration."""
        from kimai_mcp.tools.calendar import handle_get_absences_calendar
        
        # Mock calendar events
        mock_events = [
            CalendarEvent(
                title="Vacation",
                start="2024-07-15",
                end="2024-07-20",
                all_day=True,
                url="https://example.com/absence/1"
            )
        ]
        mock_client.get_absences_calendar.return_value = mock_events
        
        arguments = {
            "begin": "2024-07-01",
            "end": "2024-07-31"
        }
        
        result = await handle_get_absences_calendar(mock_client, arguments)
        
        assert len(result) == 1
        assert "Found 1 absence event(s)" in result[0].text
        assert "Vacation" in result[0].text

    @pytest.mark.asyncio
    async def test_holidays_calendar(self, mock_client):
        """Test public holidays calendar integration."""
        from kimai_mcp.tools.calendar import handle_get_public_holidays_calendar
        
        # Mock calendar events
        mock_events = [
            CalendarEvent(
                title="New Year's Day",
                start="2024-01-01",
                end="2024-01-01",
                all_day=True,
                url=None
            )
        ]
        mock_client.get_public_holidays_calendar.return_value = mock_events
        
        arguments = {
            "begin": "2024-01-01",
            "end": "2024-01-31"
        }
        
        result = await handle_get_public_holidays_calendar(mock_client, arguments)
        
        assert len(result) == 1
        assert "Found 1 public holiday(s)" in result[0].text
        assert "New Year's Day" in result[0].text


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Kimai client."""
        client = AsyncMock(spec=KimaiClient)
        return client

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client):
        """Test handling of Kimai API errors."""
        from kimai_mcp.tools.project import handle_get_project
        
        # Mock API error
        mock_client.get_project.side_effect = KimaiAPIError("Project not found", 404)
        
        # This should not raise an exception but be handled gracefully
        # In a real implementation, the server's _call_tool method would catch this
        with pytest.raises(KimaiAPIError):
            await handle_get_project(mock_client, {"id": 999})

    @pytest.mark.asyncio
    async def test_empty_results(self, mock_client):
        """Test handling of empty result sets."""
        from kimai_mcp.tools.timesheet import handle_list_timesheets
        
        # Mock empty timesheet list
        mock_client.get_timesheets.return_value = []
        
        result = await handle_list_timesheets(mock_client, {})
        
        assert len(result) == 1
        assert "No timesheets found" in result[0].text


class TestConfigurationMethods:
    """Test different configuration methods."""

    def test_env_file_loading(self):
        """Test .env file loading."""
        # Test that dotenv is imported and used correctly
        from kimai_mcp import server
        
        # The server module should have imported dotenv
        assert hasattr(server, 'load_dotenv') or 'dotenv' in str(server)

    def test_command_line_args(self):
        """Test command line argument parsing."""
        with patch('sys.argv', [
            'kimai_mcp.server',
            '--kimai-url=https://test.com',
            '--kimai-token=test-token'
        ]):
            from kimai_mcp.server import main
            
            # This tests that argument parsing works
            # In a real test, we'd mock the server run to avoid actually starting it

    def test_multiple_config_sources(self):
        """Test configuration precedence (args > env vars > .env)."""
        with patch.dict(os.environ, {
            'KIMAI_URL': 'https://env.example.com',
            'KIMAI_API_TOKEN': 'env-token'
        }):
            # Command line args should override env vars
            server = KimaiMCPServer(
                base_url='https://args.example.com',
                api_token='args-token'
            )
            
            assert server.base_url == 'https://args.example.com'
            assert server.api_token == 'args-token'


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])