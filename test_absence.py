#!/usr/bin/env python3
"""Test absence consolidated tool."""

import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from kimai_mcp.client import KimaiClient
from kimai_mcp.tools.absence_manager import handle_absence


async def test_absence_tool():
    """Test absence consolidated tool."""
    print("Testing Absence Tool...")
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    client = KimaiClient(
        base_url=os.getenv("KIMAI_URL"),
        api_token=os.getenv("KIMAI_API_TOKEN")
    )
    
    try:
        print("\n1. Testing Absence Tool - Types...")
        result = await handle_absence(
            client,
            action="types",
            language="en"
        )
        print(f"   Result: {len(result)} content blocks returned")
        if result and result[0].text:
            lines = result[0].text.split('\n')
            print(f"   First line: {lines[0]}")
        
        print("\n2. Testing Absence Tool - List...")
        result = await handle_absence(
            client,
            action="list",
            filters={"user_scope": "self", "status": "all"}
        )
        print(f"   Result: {len(result)} content blocks returned")
        if result and result[0].text:
            lines = result[0].text.split('\n')
            print(f"   First line: {lines[0]}")
        
        print("\nSUCCESS: Absence tool working correctly!")
        return True
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_absence_tool())
    sys.exit(0 if success else 1)