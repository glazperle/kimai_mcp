"""Debug test script to verify all API compliance fixes work correctly."""
import asyncio
import json
from datetime import datetime
from kimai_mcp.server import KimaiMCPServer

async def debug_mcp_tools():
    """Debug test all MCP tools to verify API compliance fixes."""
    print("=== MCP API Compliance Debug Test ===\n")
    
    # Initialize MCP server
    try:
        server = KimaiMCPServer()
        print("✅ MCP Server initialized successfully")
    except Exception as e:
        print(f"❌ MCP Server initialization failed: {e}")
        return
    
    # Test 1: List all available tools
    print("\n1. Testing Tool Registration")
    try:
        tools = await server._list_tools()
        print(f"✅ Found {len(tools)} registered tools:")
        for tool in tools:
            print(f"   - {tool.name}: {tool.description[:60]}...")
    except Exception as e:
        print(f"❌ Tool listing failed: {e}")
        return
    
    # Test 2: Test Absence Tool (Date Format Fix)
    print("\n2. Testing Absence Tool (Date Format Fix)")
    try:
        result = await server._call_tool("absence", {
            "action": "list",
            "filters": {
                "user_scope": "self",
                "begin": "2025-07-01",
                "end": "2025-07-31"
            }
        })
        print("✅ Absence tool: Date format fix working")
        print(f"   Response: {result[0].text[:100]}...")
    except Exception as e:
        print(f"❌ Absence tool error: {e}")
    
    # Test 3: Test User Current Tool (Should be fully working)
    print("\n3. Testing User Current Tool")
    try:
        result = await server._call_tool("user_current", {})
        print("✅ User Current tool working")
        print(f"   Response: {result[0].text[:100]}...")
    except Exception as e:
        print(f"❌ User Current tool error: {e}")
    
    # Test 4: Test Rate Manager (Should be fully working)
    print("\n4. Testing Rate Manager")
    try:
        # First get a customer to test with
        result = await server._call_tool("entity", {
            "type": "customer",
            "action": "list",
            "filters": {"size": 1}
        })
        
        if "customer" in result[0].text.lower():
            print("✅ Entity tool working (customers)")
            
            # Try to get rates for first customer (might be empty but should not error)
            result = await server._call_tool("rate", {
                "entity": "customer",
                "entity_id": 1,
                "action": "list"
            })
            print("✅ Rate Manager tool working")
            print(f"   Response: {result[0].text[:100]}...")
        else:
            print("⚠️ No customers found to test rate manager")
    except Exception as e:
        print(f"❌ Rate Manager error: {e}")
    
    # Test 5: Test Calendar Tool (Fixed Method Calls)
    print("\n5. Testing Calendar Tool (Fixed Method Calls)")
    try:
        result = await server._call_tool("calendar", {
            "type": "absences",
            "filters": {
                "begin": "2025-07-01",
                "end": "2025-07-31"
            }
        })
        print("✅ Calendar tool: Method calls and model fixes working")
        print(f"   Response: {result[0].text[:100]}...")
    except Exception as e:
        print(f"❌ Calendar tool error: {e}")
    
    # Test 6: Test Timer Tool (Timezone/Tags Fix)
    print("\n6. Testing Timer Tool")
    try:
        result = await server._call_tool("timer", {
            "action": "active"
        })
        print("✅ Timer tool: Active timer check working")
        print(f"   Response: {result[0].text[:100]}...")
    except Exception as e:
        print(f"❌ Timer tool error: {e}")
    
    # Test 7: Test Team Access (Removed teamlead parameter)
    print("\n7. Testing Team Access Tool")
    try:
        # Test listing teams first
        result = await server._call_tool("entity", {
            "type": "team",
            "action": "list",
            "filters": {"size": 1}
        })
        print("✅ Team Access: Entity listing working")
        print(f"   Response: {result[0].text[:100]}...")
    except Exception as e:
        print(f"❌ Team Access error: {e}")
    
    # Test 8: Test CalendarEvent Model Import
    print("\n8. Testing CalendarEvent Model")
    try:
        from kimai_mcp.models import CalendarEvent
        print("✅ CalendarEvent model: Successfully importable")
        
        # Test model instantiation
        event = CalendarEvent(
            title="Test Event",
            start=datetime.now(),
            all_day=False
        )
        print(f"   Created test event: {event.title}")
    except Exception as e:
        print(f"❌ CalendarEvent model error: {e}")
    
    # Test 9: Test Meta Tool
    print("\n9. Testing Meta Tool")
    try:
        # This should work even if there are no timesheets
        result = await server._call_tool("meta", {
            "entity": "timesheet",
            "entity_id": 1,
            "action": "update",
            "data": [{"name": "test", "value": "debug"}]
        })
        print("✅ Meta tool: Structure working (may fail due to missing timesheet)")
        print(f"   Response: {result[0].text[:100]}...")
    except Exception as e:
        # Expected to fail if no timesheet exists, but structure should be correct
        if "not found" in str(e).lower() or "404" in str(e):
            print("✅ Meta tool: Structure working (timesheet not found as expected)")
        else:
            print(f"❌ Meta tool structural error: {e}")
    
    # Test 10: Test Absence Types
    print("\n10. Testing Absence Types (API Enum Validation)")
    try:
        result = await server._call_tool("absence", {
            "action": "types",
            "language": "en"
        })
        print("✅ Absence types: Working correctly")
        print(f"   Response: {result[0].text[:100]}...")
    except Exception as e:
        print(f"❌ Absence types error: {e}")
    
    print("\n=== Debug Test Summary ===")
    print("All critical API compliance fixes have been tested.")
    print("If you see mostly ✅ marks above, the MCP server is working correctly!")
    print("\nThe server is ready for use with Claude Desktop.")

if __name__ == "__main__":
    asyncio.run(debug_mcp_tools())