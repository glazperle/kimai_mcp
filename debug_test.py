#!/usr/bin/env python3
"""Debug test to see actual API responses."""

import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from kimai_mcp.client import KimaiClient
from kimai_mcp.models import ProjectFilter


async def debug_api_responses():
    """Debug what the API actually returns."""
    print("Debugging API responses...")
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    client = KimaiClient(
        base_url=os.getenv("KIMAI_URL"),
        api_token=os.getenv("KIMAI_API_TOKEN")
    )
    
    try:
        print("\n1. Testing Project List...")
        project_filter = ProjectFilter(visible=1)
        projects = await client.get_projects(project_filter)
        
        if projects:
            print(f"First project type: {type(projects[0])}")
            print(f"First project attributes: {dir(projects[0])}")
            print(f"First project data: {projects[0]}")
        
        print(f"\n2. Testing Customer List...")
        customers = await client.get_customers()
        
        if customers:
            print(f"First customer type: {type(customers[0])}")
            print(f"First customer attributes: {dir(customers[0])}")
            print(f"First customer data: {customers[0]}")
        
        print(f"\n3. Testing User List...")
        users = await client.get_users(visible=1)
        
        if users:
            print(f"First user type: {type(users[0])}")
            print(f"First user attributes: {dir(users[0])}")
            print(f"First user data: {users[0]}")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(debug_api_responses())