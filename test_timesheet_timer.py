#!/usr/bin/env python3
"""Test timesheet and timer consolidated tools."""

import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from kimai_mcp.client import KimaiClient
from kimai_mcp.tools.timesheet_consolidated import handle_timesheet, handle_timer


async def test_timesheet_timer_tools():
    """Test timesheet and timer consolidated tools."""
    print("Testing Timesheet and Timer Tools...")
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    client = KimaiClient(
        base_url=os.getenv("KIMAI_URL"),
        api_token=os.getenv("KIMAI_API_TOKEN")
    )
    
    try:
        print("\n1. Testing Timesheet Tool - List...")
        result = await handle_timesheet(
            client,
            action="list",
            filters={"user_scope": "self", "size": 3}
        )
        print(f"   Result: {len(result)} content blocks returned")
        if result and result[0].text:
            lines = result[0].text.split('\n')
            print(f"   First line: {lines[0]}")
        
        print("\n2. Testing Timesheet Tool - User Guide...")
        result = await handle_timesheet(
            client,
            action="user_guide",
            show_users=False
        )
        print(f"   Result: {len(result)} content blocks returned")
        if result and result[0].text:
            lines = result[0].text.split('\n')
            print(f"   First line: {lines[0]}")
        
        print("\n3. Testing Timer Tool - Active...")
        result = await handle_timer(
            client,
            action="active"
        )
        print(f"   Result: {len(result)} content blocks returned")
        if result and result[0].text:
            lines = result[0].text.split('\n')
            print(f"   First line: {lines[0]}")
        
        print("\n4. Testing Timer Tool - Recent...")
        result = await handle_timer(
            client,
            action="recent",
            size=3
        )
        print(f"   Result: {len(result)} content blocks returned")
        if result and result[0].text:
            lines = result[0].text.split('\n')
            print(f"   First line: {lines[0]}")
        
        print("\nSUCCESS: Timesheet and Timer tools working correctly!")
        return True
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_timesheet_timer_tools())
    sys.exit(0 if success else 1)