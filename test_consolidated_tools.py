#!/usr/bin/env python3
"""Test script for consolidated MCP tools functionality."""

import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from kimai_mcp.client import KimaiClient
from kimai_mcp.tools.entity_manager import handle_entity
from kimai_mcp.tools.timesheet_consolidated import handle_timesheet, handle_timer
from kimai_mcp.tools.absence_manager import handle_absence


async def test_entity_tool():
    """Test the consolidated entity tool."""
    print("Testing Entity Tool...")
    
    # Initialize client
    client = KimaiClient(
        base_url=os.getenv("KIMAI_URL"),
        api_token=os.getenv("KIMAI_API_TOKEN")
    )
    
    try:
        # Test project list
        result = await handle_entity(
            client,
            type="project",
            action="list",
            filters={"visible": 1}
        )
        print("PASS Entity Tool - Project List: Found projects")
        
        # Test customer list
        result = await handle_entity(
            client,
            type="customer", 
            action="list",
            filters={"visible": 1}
        )
        print("PASS Entity Tool - Customer List: Found customers")
        
        # Test activity list
        result = await handle_entity(
            client,
            type="activity",
            action="list", 
            filters={"visible": 1}
        )
        print("PASS Entity Tool - Activity List: Found activities")
        
        return True
        
    except Exception as e:
        print(f"FAIL Entity Tool Error: {e}")
        return False


async def test_timesheet_tool():
    """Test the consolidated timesheet tool."""
    print("\nTesting Timesheet Tool...")
    
    # Initialize client
    client = KimaiClient(
        base_url=os.getenv("KIMAI_URL"),
        api_token=os.getenv("KIMAI_API_TOKEN")
    )
    
    try:
        # Test timesheet list
        result = await handle_timesheet(
            client,
            action="list",
            filters={"user_scope": "self", "size": 5}
        )
        print(f"✅ Timesheet Tool - List: Found timesheets")
        
        # Test user guide
        result = await handle_timesheet(
            client,
            action="user_guide",
            show_users=False
        )
        print(f"✅ Timesheet Tool - User Guide: Generated guide")
        
        return True
        
    except Exception as e:
        print(f"❌ Timesheet Tool Error: {e}")
        return False


async def test_timer_tool():
    """Test the consolidated timer tool."""
    print("\n🧪 Testing Timer Tool...")
    
    # Initialize client
    client = KimaiClient(
        base_url=os.getenv("KIMAI_URL"),
        api_token=os.getenv("KIMAI_API_TOKEN")
    )
    
    try:
        # Test active timers
        result = await handle_timer(
            client,
            action="active"
        )
        print(f"✅ Timer Tool - Active: Checked active timers")
        
        # Test recent timers
        result = await handle_timer(
            client,
            action="recent",
            size=5
        )
        print(f"✅ Timer Tool - Recent: Retrieved recent timesheets")
        
        return True
        
    except Exception as e:
        print(f"❌ Timer Tool Error: {e}")
        return False


async def test_absence_tool():
    """Test the consolidated absence tool."""
    print("\n🧪 Testing Absence Tool...")
    
    # Initialize client
    client = KimaiClient(
        base_url=os.getenv("KIMAI_URL"),
        api_token=os.getenv("KIMAI_API_TOKEN")
    )
    
    try:
        # Test absence types
        result = await handle_absence(
            client,
            action="types",
            language="en"
        )
        print(f"✅ Absence Tool - Types: Retrieved absence types")
        
        # Test absence list
        result = await handle_absence(
            client,
            action="list",
            filters={"user_scope": "self", "status": "all"}
        )
        print(f"✅ Absence Tool - List: Found absences")
        
        return True
        
    except Exception as e:
        print(f"❌ Absence Tool Error: {e}")
        return False


async def main():
    """Run all tests."""
    print("🚀 Testing Consolidated MCP Tools Functionality\n")
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    if not os.getenv("KIMAI_URL") or not os.getenv("KIMAI_API_TOKEN"):
        print("❌ Error: KIMAI_URL and KIMAI_API_TOKEN must be set in .env file")
        return
    
    tests = [
        ("Entity Tool", test_entity_tool),
        ("Timesheet Tool", test_timesheet_tool), 
        ("Timer Tool", test_timer_tool),
        ("Absence Tool", test_absence_tool)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            success = await test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    # Summary
    print(f"\n📊 Test Results Summary:")
    print("=" * 50)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{test_name:20} {status}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All consolidated tools are working correctly!")
    else:
        print("⚠️  Some tools need attention.")


if __name__ == "__main__":
    asyncio.run(main())