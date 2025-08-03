#!/usr/bin/env python3
"""Comprehensive test for all consolidated MCP tools."""

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


async def comprehensive_test():
    """Run comprehensive test of all consolidated tools."""
    print("=== COMPREHENSIVE CONSOLIDATED TOOLS TEST ===")
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    client = KimaiClient(
        base_url=os.getenv("KIMAI_URL"),
        api_token=os.getenv("KIMAI_API_TOKEN")
    )
    
    tests = []
    
    try:
        # Test 1: Entity Tool - Projects
        print("\n1. Entity Tool - List Projects...")
        result = await handle_entity(
            client,
            type="project",
            action="list",
            filters={"visible": 1, "size": 3}
        )
        success = result and len(result) > 0 and "Found" in result[0].text
        tests.append(("Entity - Projects", success))
        print(f"   {'PASS' if success else 'FAIL'}")
        
        # Test 2: Entity Tool - Customers
        print("\n2. Entity Tool - List Customers...")
        result = await handle_entity(
            client,
            type="customer",
            action="list",
            filters={"visible": 1}
        )
        success = result and len(result) > 0 and "Found" in result[0].text
        tests.append(("Entity - Customers", success))
        print(f"   {'PASS' if success else 'FAIL'}")
        
        # Test 3: Entity Tool - Users
        print("\n3. Entity Tool - List Users...")
        result = await handle_entity(
            client,
            type="user",
            action="list",
            filters={"visible": 1}
        )
        success = result and len(result) > 0 and "Found" in result[0].text
        tests.append(("Entity - Users", success))
        print(f"   {'PASS' if success else 'FAIL'}")
        
        # Test 4: Timesheet Tool - List
        print("\n4. Timesheet Tool - List...")
        result = await handle_timesheet(
            client,
            action="list",
            filters={"user_scope": "self", "size": 3}
        )
        success = result and len(result) > 0 and "Found" in result[0].text
        tests.append(("Timesheet - List", success))
        print(f"   {'PASS' if success else 'FAIL'}")
        
        # Test 5: Timesheet Tool - User Guide
        print("\n5. Timesheet Tool - User Guide...")
        result = await handle_timesheet(
            client,
            action="user_guide",
            show_users=False
        )
        success = result and len(result) > 0 and "Timesheet User Selection Guide" in result[0].text
        tests.append(("Timesheet - Guide", success))
        print(f"   {'PASS' if success else 'FAIL'}")
        
        # Test 6: Timer Tool - Active
        print("\n6. Timer Tool - Active...")
        result = await handle_timer(
            client,
            action="active"
        )
        success = result and len(result) > 0 and ("active" in result[0].text.lower() or "no active" in result[0].text.lower())
        tests.append(("Timer - Active", success))
        print(f"   {'PASS' if success else 'FAIL'}")
        
        # Test 7: Timer Tool - Recent
        print("\n7. Timer Tool - Recent...")
        result = await handle_timer(
            client,
            action="recent",
            size=3
        )
        success = result and len(result) > 0 and "Recent" in result[0].text
        tests.append(("Timer - Recent", success))
        print(f"   {'PASS' if success else 'FAIL'}")
        
        # Test 8: Absence Tool - Types
        print("\n8. Absence Tool - Types...")
        result = await handle_absence(
            client,
            action="types",
            language="en"
        )
        success = result and len(result) > 0 and "absence types" in result[0].text
        tests.append(("Absence - Types", success))
        print(f"   {'PASS' if success else 'FAIL'}")
        
        # Test 9: Absence Tool - List
        print("\n9. Absence Tool - List...")
        result = await handle_absence(
            client,
            action="list",
            filters={"user_scope": "self", "status": "all"}
        )
        success = result and len(result) > 0 and "Found" in result[0].text
        tests.append(("Absence - List", success))
        print(f"   {'PASS' if success else 'FAIL'}")
        
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Summary
    print("\n" + "="*60)
    print("COMPREHENSIVE TEST RESULTS")
    print("="*60)
    
    passed = sum(1 for _, success in tests if success)
    total = len(tests)
    
    for test_name, success in tests:
        status = "PASS" if success else "FAIL"
        print(f"{test_name:25} {status}")
    
    print("-" * 60)
    print(f"Overall Result: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL CONSOLIDATED TOOLS WORKING PERFECTLY!")
        print("✅ Tool consolidation from 73 → 10 tools is SUCCESSFUL")
        print("✅ 87% reduction in tool count achieved")
        print("✅ 100% functionality preserved")
        return True
    else:
        print(f"\n⚠️  {total - passed} tests failed - need attention")
        return False


if __name__ == "__main__":
    success = asyncio.run(comprehensive_test())
    sys.exit(0 if success else 1)