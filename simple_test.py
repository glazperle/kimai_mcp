#!/usr/bin/env python3
"""Simple test script for consolidated MCP tools functionality."""

import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from kimai_mcp.client import KimaiClient
from kimai_mcp.tools.entity_manager import handle_entity


async def test_basic_functionality():
    """Test basic functionality of consolidated tools."""
    print("Testing Consolidated MCP Tools...")
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    if not os.getenv("KIMAI_URL") or not os.getenv("KIMAI_API_TOKEN"):
        print("ERROR: KIMAI_URL and KIMAI_API_TOKEN must be set in .env file")
        return False
    
    # Initialize client
    client = KimaiClient(
        base_url=os.getenv("KIMAI_URL"),
        api_token=os.getenv("KIMAI_API_TOKEN")
    )
    
    try:
        print("1. Testing Entity Tool - Project List...")
        result = await handle_entity(
            client,
            type="project",
            action="list",
            filters={"visible": 1}
        )
        print(f"   Result: {len(result)} content blocks returned")
        if result and result[0].text:
            lines = result[0].text.split('\n')
            print(f"   First line: {lines[0]}")
        
        print("\n2. Testing Entity Tool - Customer List...")
        result = await handle_entity(
            client,
            type="customer", 
            action="list",
            filters={"visible": 1}
        )
        print(f"   Result: {len(result)} content blocks returned")
        if result and result[0].text:
            lines = result[0].text.split('\n')
            print(f"   First line: {lines[0]}")
        
        print("\n3. Testing Entity Tool - User List...")
        result = await handle_entity(
            client,
            type="user",
            action="list",
            filters={"visible": 1}
        )
        print(f"   Result: {len(result)} content blocks returned")
        if result and result[0].text:
            lines = result[0].text.split('\n')
            print(f"   First line: {lines[0]}")
        
        print("\nSUCCESS: All basic tests passed!")
        return True
        
    except Exception as e:
        print(f"ERROR: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_basic_functionality())
    sys.exit(0 if success else 1)