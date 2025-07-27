# Kimai MCP Usage Examples

This document provides practical examples of using the Kimai MCP server with AI assistants.

## Basic Time Tracking Workflow

### 1. Start Your Day - Check Active Timers

```
Assistant: Let me check if you have any active timers running.

Tool: timesheet_active
```

### 2. View Recent Activities

```
Assistant: I'll show you your recent activities to help you quickly start a timer.

Tool: timesheet_recent
Parameters: {
  "size": 5
}
```

### 3. Start a Timer

```
Assistant: I'll start a timer for the API development task.

Tool: timesheet_start
Parameters: {
  "project": 15,
  "activity": 42,
  "description": "Implementing REST API endpoints",
  "tags": "development,backend"
}
```

### 4. Stop the Timer

```
Assistant: I'll stop your current timer.

Tool: timesheet_stop
Parameters: {
  "id": 1234
}
```

## Project Management Examples

### List All Visible Projects

```
Tool: project_list
Parameters: {
  "visible": 1,
  "orderBy": "name",
  "order": "ASC"
}
```

### Find Projects for a Specific Customer

```
Tool: project_list
Parameters: {
  "customer": 5,
  "visible": 1
}
```

### Search Projects by Name

```
Tool: project_list
Parameters: {
  "term": "website",
  "visible": 3
}
```

## Reporting Examples

### Today's Timesheet Entries

```
Tool: timesheet_list
Parameters: {
  "begin": "2024-01-15T00:00:00",
  "end": "2024-01-15T23:59:59"
}
```

### This Week's Entries

```
Tool: timesheet_list
Parameters: {
  "begin": "2024-01-15T00:00:00",
  "end": "2024-01-21T23:59:59",
  "orderBy": "begin",
  "order": "ASC"
}
```

### Billable vs Non-Billable Time

```
# Get billable entries
Tool: timesheet_list
Parameters: {
  "begin": "2024-01-01T00:00:00",
  "end": "2024-01-31T23:59:59",
  "billable": 1
}

# Get non-billable entries
Tool: timesheet_list
Parameters: {
  "begin": "2024-01-01T00:00:00",
  "end": "2024-01-31T23:59:59",
  "billable": 0
}
```

### Entries Ready for Export

```
Tool: timesheet_list
Parameters: {
  "exported": 0,
  "billable": 1,
  "size": 100
}
```

## Activity Management Examples

### List All Global Activities

```
Tool: activity_list
Parameters: {
  "globals": "1",
  "visible": 1
}
```

### List Activities for a Specific Project

```
Tool: activity_list
Parameters: {
  "project": 15,
  "visible": 1,
  "orderBy": "name"
}
```

## Customer Examples

### List All Active Customers

```
Tool: customer_list
Parameters: {
  "visible": 1,
  "orderBy": "name",
  "order": "ASC"
}
```

### Search for a Customer

```
Tool: customer_list
Parameters: {
  "term": "Acme",
  "visible": 3
}
```

## Complex Workflows

### Daily Time Report

```
Assistant: I'll generate your daily time report.

1. First, let me check today's entries:
Tool: timesheet_list
Parameters: {
  "begin": "2024-01-15T00:00:00",
  "end": "2024-01-15T23:59:59"
}

2. Let me also check if you have any running timers:
Tool: timesheet_active

3. Summary:
- Total entries today: 5
- Total time logged: 7h 30m
- Currently running: 1 timer (started 45m ago)
- Projects worked on: Website Redesign (3h), API Development (4h 30m)
```

### Quick Timer Switch

```
Assistant: I'll stop your current timer and start a new one for the meeting.

1. First, let me check your active timer:
Tool: timesheet_active

2. Stopping the development timer:
Tool: timesheet_stop
Parameters: {
  "id": 1234
}

3. Starting the meeting timer:
Tool: timesheet_start
Parameters: {
  "project": 15,
  "activity": 99,
  "description": "Weekly team standup",
  "tags": "meeting,weekly"
}
```

### Time Entry Correction

```
Assistant: I'll help you correct that time entry.

1. First, let me find the entry:
Tool: timesheet_list
Parameters: {
  "begin": "2024-01-15T08:00:00",
  "end": "2024-01-15T12:00:00",
  "term": "API meeting"
}

2. Now I'll update it with the correct times:
Tool: timesheet_update
Parameters: {
  "id": 1235,
  "begin": "2024-01-15T09:00:00",
  "end": "2024-01-15T10:30:00",
  "description": "API planning meeting with team"
}
```

## Tips for AI Assistant Interactions

1. **Be specific with dates**: Always use ISO format (YYYY-MM-DDTHH:MM:SS) for date/time parameters

2. **Use search terms**: When looking for specific entries, use the `term` parameter to search descriptions

3. **Leverage recent activities**: Use `timesheet_recent` to quickly find frequently used project/activity combinations

4. **Check before starting**: Always check `timesheet_active` before starting a new timer to avoid multiple running timers

5. **Use filters effectively**: Combine multiple filters to narrow down results (e.g., specific project + date range + billable status)