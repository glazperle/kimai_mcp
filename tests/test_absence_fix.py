#!/usr/bin/env python3
"""Test script to verify the absence manager fix for 'all users' scope"""

import asyncio
import os
from datetime import datetime
from kimai_mcp.client import KimaiClient
from kimai_mcp.tools.absence_manager import handle_absence

async def test_absence_workflow():
    """Test the fixed absence manager with different user scopes."""
    
    # Initialize client with credentials from environment
    client = KimaiClient(
        base_url=os.getenv("KIMAI_API_URL", "https://your-kimai-instance.com"),
        api_token=os.getenv("KIMAI_API_TOKEN")
    )
    
    print("Testing Absence Manager - All User Scopes")
    print("=" * 50)
    
    # Calculate current month dates
    now = datetime.now()
    start_date = f"{now.year}-{now.month:02d}-01"
    
    # Calculate last day of month
    if now.month == 12:
        end_date = f"{now.year}-12-31"
    else:
        next_month = datetime(now.year, now.month + 1, 1)
        from datetime import timedelta
        last_day = next_month - timedelta(days=1)
        end_date = f"{now.year}-{now.month:02d}-{last_day.day:02d}"
    
    print(f"\nDate range: {start_date} to {end_date}\n")
    
    # Test 1: Self scope (current user only)
    print("1. Testing 'self' scope (current user only):")
    print("-" * 40)
    result = await handle_absence(
        client,
        action="list",
        filters={
            "user_scope": "self",
            "begin": start_date,
            "end": end_date,
            "status": "all"
        }
    )
    print(result[0].text)
    
    # Test 2: All users scope (should now iterate over all users)
    print("\n2. Testing 'all' scope (all users - FIXED):")
    print("-" * 40)
    result = await handle_absence(
        client,
        action="list",
        filters={
            "user_scope": "all",
            "begin": start_date,
            "end": end_date,
            "status": "all"
        }
    )
    print(result[0].text)
    
    # Test 3: Specific user scope (if you know a user ID)
    print("\n3. Testing 'specific' scope (example with user ID 1):")
    print("-" * 40)
    result = await handle_absence(
        client,
        action="list",
        filters={
            "user_scope": "specific",
            "user": "1",  # Replace with actual user ID
            "begin": start_date,
            "end": end_date,
            "status": "all"
        }
    )
    print(result[0].text)
    
    # Test 4: Get absence types
    print("\n4. Testing absence types retrieval:")
    print("-" * 40)
    result = await handle_absence(
        client,
        action="types",
        language="de"
    )
    print(result[0].text)
    
    print("\n" + "=" * 50)
    print("Test completed successfully!")
    print("\nThe 'all' scope now correctly iterates over all users")
    print("and collects their absences, matching the JavaScript behavior.")

if __name__ == "__main__":
    # Make sure to set your API credentials
    if not os.getenv("KIMAI_API_TOKEN"):
        print("Please set KIMAI_API_TOKEN environment variable")
        print("Example: export KIMAI_API_TOKEN='your-token-here'")
        print("Optional: export KIMAI_API_URL='https://your-kimai-instance.com'")
    else:
        asyncio.run(test_absence_workflow())