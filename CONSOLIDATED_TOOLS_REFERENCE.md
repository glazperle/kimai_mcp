# Consolidated Tools Reference Guide

## Tool Consolidation: 73 → 10 Tools

This guide shows the new consolidated tool structure that reduces 73 individual tools to just 10 powerful, multi-action tools while maintaining 100% functionality.

---

## 1. Entity Tool
**Replaces 35 tools** for CRUD operations across all entity types.

### Usage:
```json
{
  "tool": "entity",
  "parameters": {
    "type": "project|activity|customer|user|team|tag|invoice|holiday",
    "action": "list|get|create|update|delete",
    "id": 123,                    // Required for: get, update, delete
    "filters": {                  // Optional for: list
      "visible": 1,
      "term": "search",
      "page": 1,
      "size": 50
    },
    "data": {                     // Required for: create, update
      "name": "New Entity",
      // ... entity-specific fields
    }
  }
}
```

### Replaces:
- `project_list`, `project_get`, `project_create`, `project_update`, `project_delete`
- `activity_list`, `activity_get`, `activity_create`, `activity_update`, `activity_delete`
- `customer_list`, `customer_get`, `customer_create`, `customer_update`, `customer_delete`
- `user_list`, `user_get`, `user_create`, `user_update`
- `team_list`, `team_get`, `team_create`, `team_update`, `team_delete`
- `tag_list`, `tag_create`, `tag_delete`
- `invoice_list`, `invoice_get`
- `holiday_list`, `holiday_delete`

---

## 2. Timesheet Tool
**Replaces 9 timesheet tools** for all timesheet operations.

### Usage:
```json
{
  "tool": "timesheet",
  "parameters": {
    "action": "list|get|create|update|delete|duplicate|export_toggle",
    "id": 123,                    // Required for: get, update, delete, duplicate, export_toggle
    "filters": {                  // Optional for: list
      "user_scope": "self|all|specific",
      "user": "5",
      "project": 17,
      "begin": "2024-01-01T00:00:00",
      "end": "2024-01-31T23:59:59"
    },
    "data": {                     // Required for: create, update
      "project": 1,
      "activity": 5,
      "description": "Work description"
    }
  }
}
```

### Replaces:
- `timesheet_list`, `timesheet_get`, `timesheet_create`, `timesheet_update`, `timesheet_delete`
- `timesheet_duplicate`, `timesheet_export_toggle`, `timesheet_meta_update`, `timesheet_user_guide`

---

## 3. Timer Tool
**Replaces 4 timer tools** for active timer management.

### Usage:
```json
{
  "tool": "timer",
  "parameters": {
    "action": "start|stop|restart|active",
    "id": 123,                    // Required for: stop, restart
    "data": {                     // Required for: start
      "project": 1,
      "activity": 5,
      "description": "Starting work"
    }
  }
}
```

### Replaces:
- `timesheet_start`, `timesheet_stop`, `timesheet_restart`, `timesheet_active`

---

## 4. Rate Tool
**Replaces 9 rate tools** for managing rates across entities.

### Usage:
```json
{
  "tool": "rate",
  "parameters": {
    "entity": "customer|project|activity",
    "entity_id": 123,
    "action": "list|add|delete",
    "rate_id": 456,               // Required for: delete
    "data": {                     // Required for: add
      "user": 1,
      "rate": 150.00,
      "internal_rate": 75.00
    }
  }
}
```

### Replaces:
- `customer_rates_list`, `customer_rate_add`, `customer_rate_delete`
- `project_rates_list`, `project_rate_add`, `project_rate_delete`
- `activity_rates_list`, `activity_rate_add`, `activity_rate_delete`

---

## 5. Team Access Tool
**Replaces 8 team access tools** for team member and permission management.

### Usage:
```json
{
  "tool": "team_access",
  "parameters": {
    "team_id": 123,
    "action": "add_member|remove_member|grant|revoke",
    "target": "customer|project|activity",     // Required for: grant, revoke
    "user_id": 456,                           // Required for: add_member, remove_member
    "target_id": 789,                         // Required for: grant, revoke
    "teamlead": false                         // Optional for: add_member
  }
}
```

### Replaces:
- `team_add_member`, `team_remove_member`
- `team_grant_customer_access`, `team_revoke_customer_access`
- `team_grant_project_access`, `team_revoke_project_access`
- `team_grant_activity_access`, `team_revoke_activity_access`

---

## 6. Absence Tool
**Replaces 6 absence tools** for complete absence management.

### Usage:
```json
{
  "tool": "absence",
  "parameters": {
    "action": "list|types|create|delete|approve|reject",
    "id": 123,                    // Required for: delete, approve, reject
    "filters": {                  // Optional for: list
      "user": "5",
      "begin": "2024-01-01",
      "end": "2024-01-31",
      "status": "approved|open|all"
    },
    "data": {                     // Required for: create
      "comment": "Vacation",
      "date": "2024-02-15",
      "end": "2024-02-20",
      "type": "holiday"
    }
  }
}
```

### Replaces:
- `absence_list`, `absence_types`, `absence_create`
- `absence_delete`, `absence_approve`, `absence_reject`

---

## 7. Calendar Tool
**Replaces 2 calendar tools** for unified calendar access.

### Usage:
```json
{
  "tool": "calendar",
  "parameters": {
    "type": "absences|holidays",
    "filters": {
      "user": 1,
      "year": 2024,
      "month": 2
    }
  }
}
```

### Replaces:
- `calendar_absences`, `calendar_holidays`

---

## 8. Meta Tool
**Replaces 4 meta tools** for custom field management.

### Usage:
```json
{
  "tool": "meta",
  "parameters": {
    "entity": "customer|project|activity|timesheet",
    "entity_id": 123,
    "action": "update",
    "data": [
      {
        "name": "custom_field",
        "value": "custom_value"
      }
    ]
  }
}
```

### Replaces:
- `customer_meta_update`, `project_meta_update`
- `activity_meta_update`, `timesheet_meta_update`

---

## 9. User Current Tool
**Specialized tool** for getting current authenticated user.

### Usage:
```json
{
  "tool": "user_current",
  "parameters": {}
}
```

### Note:
Kept separate as it's a special case that doesn't require parameters.

---

## 10. Project Analysis Tool
**Specialized tool** for advanced project analytics.

### Usage:
```json
{
  "tool": "project_analysis",
  "parameters": {
    "project_id": 17,
    "user_scope": "self|all|specific",
    "user": "5",
    "date_from": "2024-01-01",
    "date_to": "2024-12-31"
  }
}
```

### Note:
Kept as-is due to its specialized nature and complex analysis logic.

---

## Migration Examples

### Before: Creating a Project
```json
{
  "tool": "project_create",
  "parameters": {
    "name": "New Project",
    "customer": 1
  }
}
```

### After: Creating a Project
```json
{
  "tool": "entity",
  "parameters": {
    "type": "project",
    "action": "create",
    "data": {
      "name": "New Project",
      "customer": 1
    }
  }
}
```

### Before: Starting a Timer
```json
{
  "tool": "timesheet_start",
  "parameters": {
    "project": 1,
    "activity": 5
  }
}
```

### After: Starting a Timer
```json
{
  "tool": "timer",
  "parameters": {
    "action": "start",
    "data": {
      "project": 1,
      "activity": 5
    }
  }
}
```

---

## Benefits Summary

1. **87% Fewer Tools**: From 73 to 10 tools
2. **Consistent Interface**: All CRUD operations use the same pattern
3. **Easier Discovery**: Users can find all entity operations in one tool
4. **Reduced Complexity**: Less code duplication and maintenance
5. **Extensible**: Easy to add new actions without creating new tools

## Implementation Notes

- All existing functionality is preserved
- Parameter validation remains the same
- Error messages are consistent across actions
- Performance is optimized through shared code paths
- Backward compatibility can be maintained through a translation layer