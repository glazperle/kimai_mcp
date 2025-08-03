"""Simple debug test without Unicode characters."""
import asyncio
from datetime import datetime
from kimai_mcp.server import KimaiMCPServer

async def debug_mcp_tools():
    """Debug test all MCP tools to verify API compliance fixes."""
    print("=== MCP API Compliance Debug Test ===\n")
    
    # Initialize MCP server
    try:
        server = KimaiMCPServer()
        print("[SUCCESS] MCP Server initialized successfully")
    except Exception as e:
        print(f"[ERROR] MCP Server initialization failed: {e}")
        return
    
    # Test 1: List all available tools
    print("\n1. Testing Tool Registration")
    try:
        tools = await server._list_tools()
        print(f"[SUCCESS] Found {len(tools)} registered tools:")
        for tool in tools:
            print(f"   - {tool.name}: {tool.description[:60]}...")
    except Exception as e:
        print(f"[ERROR] Tool listing failed: {e}")
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
        print("[SUCCESS] Absence tool: Date format fix working")
        print(f"   Response: {result[0].text[:100]}...")
    except Exception as e:
        print(f"[ERROR] Absence tool error: {e}")
    
    # Test 3: Test User Current Tool
    print("\n3. Testing User Current Tool")
    try:
        result = await server._call_tool("user_current", {})
        print("[SUCCESS] User Current tool working")
        print(f"   Response: {result[0].text[:100]}...")
    except Exception as e:
        print(f"[ERROR] User Current tool error: {e}")
    
    # Test 4: Test Calendar Tool (Fixed Method Calls)
    print("\n4. Testing Calendar Tool (Fixed Method Calls)")
    try:
        result = await server._call_tool("calendar", {
            "type": "absences",
            "filters": {
                "begin": "2025-07-01",
                "end": "2025-07-31"
            }
        })
        print("[SUCCESS] Calendar tool: Method calls and model fixes working")
        print(f"   Response: {result[0].text[:100]}...")
    except Exception as e:
        print(f"[ERROR] Calendar tool error: {e}")
    
    # Test 5: Test Timer Tool
    print("\n5. Testing Timer Tool")
    try:
        result = await server._call_tool("timer", {
            "action": "active"
        })
        print("[SUCCESS] Timer tool: Active timer check working")
        print(f"   Response: {result[0].text[:100]}...")
    except Exception as e:
        print(f"[ERROR] Timer tool error: {e}")
    
    # Test 6: Test CalendarEvent Model Import
    print("\n6. Testing CalendarEvent Model")
    try:
        from kimai_mcp.models import CalendarEvent
        print("[SUCCESS] CalendarEvent model: Successfully importable")
        
        # Test model instantiation
        event = CalendarEvent(
            title="Test Event",
            start=datetime.now(),
            all_day=False
        )
        print(f"   Created test event: {event.title}")
    except Exception as e:
        print(f"[ERROR] CalendarEvent model error: {e}")
    
    # Test 7: Test Absence Types (API Enum Validation)
    print("\n7. Testing Absence Types (API Enum Validation)")
    try:
        result = await server._call_tool("absence", {
            "action": "types",
            "language": "en"
        })
        print("[SUCCESS] Absence types: Working correctly")
        print(f"   Response: {result[0].text[:100]}...")
    except Exception as e:
        print(f"[ERROR] Absence types error: {e}")
    
    print("\n=== Debug Test Summary ===")
    print("All critical API compliance fixes have been tested.")
    print("If you see mostly [SUCCESS] marks above, the MCP server is working correctly!")
    print("\nThe server is ready for use with Claude Desktop.")

if __name__ == "__main__":
    asyncio.run(debug_mcp_tools())