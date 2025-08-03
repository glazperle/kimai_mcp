# Tool Consolidation Implementation Plan

## Overview
Reduce MCP tools from 73 to ~10 while maintaining full functionality through parameterized, multi-action tools.

## Phase 1: Create Base Infrastructure

### 1.1 Create Generic Tool Handler Framework
```python
# src/kimai_mcp/tools/base.py
class UniversalToolHandler:
    def __init__(self, client: KimaiClient):
        self.client = client
        self.handlers = {
            'list': self._handle_list,
            'get': self._handle_get,
            'create': self._handle_create,
            'update': self._handle_update,
            'delete': self._handle_delete
        }
    
    async def execute(self, entity_type: str, action: str, **kwargs):
        handler = self.handlers.get(action)
        if not handler:
            raise ValueError(f"Unknown action: {action}")
        return await handler(entity_type, **kwargs)
```

### 1.2 Update Tool Registration
Modify server.py to register consolidated tools instead of individual ones.

## Phase 2: Implement Consolidated Tools

### 2.1 Universal Entity Manager
**File**: `src/kimai_mcp/tools/entity_manager.py`
- Combines: project_*, activity_*, customer_*, user_*, team_*, tag_*, invoice_*, holiday_*
- Actions: list, get, create, update, delete
- Entity-specific validation and routing

### 2.2 Timesheet Tools (3 tools)
**File**: `src/kimai_mcp/tools/timesheet_consolidated.py`
- `timesheet`: list, get, create, update, delete, duplicate, export_toggle
- `timer`: start, stop, restart, active
- `timesheet_meta`: meta_update, user_guide

### 2.3 Rate Manager
**File**: `src/kimai_mcp/tools/rate_manager.py`
- Entities: customer, project, activity
- Actions: list, add, delete
- Unified rate handling across entity types

### 2.4 Team Access Manager
**File**: `src/kimai_mcp/tools/team_access_manager.py`
- Member management: add_member, remove_member
- Access control: grant/revoke for customer/project/activity
- Single tool for all team access operations

### 2.5 Absence Manager
**File**: `src/kimai_mcp/tools/absence_manager.py`
- Actions: list, types, create, delete, approve, reject
- Maintains all absence functionality in one tool

### 2.6 Calendar Tool
**File**: `src/kimai_mcp/tools/calendar_consolidated.py`
- Types: absences, holidays
- Unified calendar data access

## Phase 3: Migration Strategy

### 3.1 Backward Compatibility Layer (Optional)
```python
# src/kimai_mcp/tools/compatibility.py
def create_legacy_tool_mapping():
    """Map old tool names to new consolidated tools"""
    return {
        'project_list': ('entity', {'type': 'project', 'action': 'list'}),
        'project_get': ('entity', {'type': 'project', 'action': 'get'}),
        # ... mapping for all 73 tools
    }
```

### 3.2 Testing Migration
1. Create comprehensive test suite for new tools
2. Verify feature parity with old tools
3. Performance testing for consolidated operations

## Phase 4: Implementation Steps

### Step 1: Create Base Classes (Week 1)
- [ ] Implement UniversalToolHandler base class
- [ ] Create entity routing system
- [ ] Build validation framework

### Step 2: Implement Core Tools (Week 2-3)
- [ ] Entity Manager (handles ~35 tools)
- [ ] Timesheet consolidation (14 → 3 tools)
- [ ] Rate Manager (9 → 1 tool)

### Step 3: Implement Specialized Tools (Week 3-4)
- [ ] Team Access Manager (8 → 1 tool)
- [ ] Absence Manager (6 → 1 tool)
- [ ] Calendar Tool (2 → 1 tool)

### Step 4: Testing & Documentation (Week 4-5)
- [ ] Update all tests for new tool structure
- [ ] Create migration guide
- [ ] Update README and examples

### Step 5: Deprecation & Cleanup (Week 5-6)
- [ ] Mark old tools as deprecated
- [ ] Provide migration warnings
- [ ] Final cleanup after transition period

## Benefits

1. **Reduced Complexity**: 86% fewer tools to maintain
2. **Better Discoverability**: Users find functionality easier
3. **Consistent Interface**: Similar operations use same patterns
4. **Easier Maintenance**: Less code duplication
5. **Future-Proof**: Easy to add new actions without new tools

## Example Usage Comparison

### Before (73 tools):
```json
{"tool": "project_list", "parameters": {"customer": 1}}
{"tool": "project_get", "parameters": {"id": 123}}
{"tool": "project_create", "parameters": {"name": "New Project"}}
```

### After (1 tool):
```json
{
  "tool": "entity",
  "parameters": {
    "type": "project",
    "action": "list",
    "filters": {"customer": 1}
  }
}
```

## Risk Mitigation

1. **Breaking Changes**: Provide compatibility layer
2. **Performance**: Benchmark consolidated vs individual tools
3. **Complexity**: Keep action handlers simple and focused
4. **Documentation**: Comprehensive migration guide

## Success Metrics

- Tool count: 73 → ≤10
- Code reduction: ~40% less code to maintain
- Test coverage: Maintain 100% feature parity
- Performance: No degradation in response times