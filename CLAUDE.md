# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Install Dependencies
```bash
# Install package in development mode
pip install -e .

# Install with dev dependencies for testing and linting
pip install -e ".[dev]"
```

### Testing
```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_integration.py -v

# Run with coverage (if pytest-cov installed)
pytest tests/ -v --cov=kimai_mcp
```

### Code Formatting and Linting
```bash
# Format code with black
black src/ tests/

# Run linting with ruff
ruff check src/ tests/

# Fix linting issues automatically
ruff check --fix src/ tests/
```

### Running the Server

There are three server types for different use cases:

```bash
# 1. LOCAL MCP SERVER (for Claude Desktop)
python -m kimai_mcp --kimai-url=https://your-kimai.com --kimai-token=your-token
# or: kimai-mcp --kimai-url=... --kimai-token=...

# 2. SSE REMOTE SERVER (for Claude Desktop remote connections)
python -m kimai_mcp.sse_server --host 0.0.0.0 --port 8000
# or: kimai-mcp-server --host 0.0.0.0 --port 8000

# 3. STREAMABLE HTTP SERVER (for Claude.ai Connectors - NEW v2.8.0)
python -m kimai_mcp.streamable_http_server --users-config=./config/users.json
# or: kimai-mcp-streamable --users-config=./config/users.json
```

| Server | Command | Protocol | Use Case |
|--------|---------|----------|----------|
| Local | `kimai-mcp` | MCP Stdio | Claude Desktop local |
| SSE | `kimai-mcp-server` | HTTP/SSE | Claude Desktop remote |
| Streamable | `kimai-mcp-streamable` | HTTP Streamable | Claude.ai Connectors |

## Releasing a New Version

**CRITICAL: Always update version numbers in BOTH files before creating a release tag!**

### Version Files

| File                         | Line | Example                 |
|------------------------------|------|-------------------------|
| `pyproject.toml`             | 7    | `version = "2.11.2"`    |
| `src/kimai_mcp/__init__.py`  | 3    | `__version__ = "2.11.2"`|

### Release Steps

```bash
# 1. Update version in BOTH files (must match!)
# Edit pyproject.toml: version = "X.Y.Z"
# Edit src/kimai_mcp/__init__.py: __version__ = "X.Y.Z"

# 2. Commit version bump
git add pyproject.toml src/kimai_mcp/__init__.py
git commit -m "chore: Bump version to X.Y.Z"
git push origin main

# 3. Create and push tag
git tag vX.Y.Z
git push origin vX.Y.Z

# 4. Create GitHub Release from tag
# PyPI deployment triggers automatically via .github/workflows/publish.yml
```

### Common Pitfall
If PyPI deployment fails with "version already exists", the version numbers in the code files were not updated before tagging. Fix by updating both files, committing, and re-creating the release.

## Architecture Overview

### Core Components

1. **MCP Server (`server.py`)**: Main server implementation that handles MCP protocol communication and tool registration. **Now uses consolidated tools (10 tools instead of 73)** - 87% reduction while maintaining all functionality.

2. **Kimai API Client (`client.py`)**: HTTP client wrapper using httpx for all Kimai API interactions. Handles authentication, request formatting, and response parsing.

3. **Data Models (`models.py`)**: Pydantic models for type-safe data structures representing Kimai entities (timesheets, projects, users, etc.).

4. **Consolidated Tools (`tools/` directory)**: New consolidated tool implementations that replace 73 individual tools:
   - `entity_manager.py`: Universal CRUD operations for all entities (35 tools → 1)
   - `timesheet_consolidated.py`: All timesheet operations (9 tools → 1)
   - `timer_tool.py`: Timer management (4 tools → 1)
   - `rate_manager.py`: Rate management across entities (9 tools → 1)
   - `team_access_manager.py`: Team member and permission management (8 tools → 1)
   - `absence_manager.py`: Complete absence workflow (6 tools → 1)
   - `calendar_meta.py`: Calendar and meta field operations (6 tools → 3)
   - `project_analysis.py`: Advanced project analytics (kept as specialized tool)

### Key Design Patterns

1. **Action-Based Tools**: Tools use action parameters instead of separate tools (e.g., `entity` tool with `action: "create"` vs separate `create_entity` tool).

2. **Universal Entity Handler**: Single tool handles CRUD operations for all entity types using `type` and `action` parameters.

3. **Smart User Selection**: Tools like `timesheet` and `absence` implement intelligent user scope selection with `user_scope` enum ("self", "all", "specific").

4. **Consolidated Error Handling**: Unified error handling patterns across all consolidated tools.

5. **Flexible Configuration**: Supports CLI arguments, environment variables, and .env files.

### Authentication Flow
- API token passed via configuration
- Token included in all HTTP requests as X-AUTH-TOKEN header
- Optional default user ID for operations requiring user context

### Consolidated Tool Pattern
Each consolidated tool follows this structure:
1. Action routing based on `action` parameter
2. Input validation using Pydantic models
3. Entity-specific handler delegation (for entity tool)
4. API call through the Kimai client
5. Response transformation to MCP-compatible format
6. Unified error handling with descriptive messages

### Tool Migration
- **Original**: 73 individual tools with separate functions
- **Consolidated**: 10 multi-action tools with parameterized operations
- **Compatibility**: server_original.py available for rollback if needed

## API Documentation & Compliance

### API Reference
The Kimai API documentation is available at:
- **Local Documentation**: `C:\Users\MaximilianvonHeyden\Nextcloud\00_Professionell\10_Software\Kimai\api_documentation.json`
- **Online Documentation**: https://www.kimai.org/documentation/rest-api.html

### API Version Update (December 2024)

The following new API fields have been implemented:

#### New Fields Added
| Entity | Field | Type | Description |
|--------|-------|------|-------------|
| **Timesheet** | `break` | integer | Break duration in seconds |
| **Project** | `metaFields` | array | Custom meta fields for projects |
| **Activity** | `metaFields` | array | Custom meta fields for activities |
| **Customer** | `metaFields` | array | Custom meta fields for customers |
| **Invoice** | `overdue` | boolean | Whether the invoice is overdue |

#### Removed Fields
- `TagEntity.color-safe` - No longer in API schema

#### Endpoint Changes (Work Contract)
| Old Endpoint | New Endpoint | Description |
|--------------|--------------|-------------|
| `DELETE /api/work-contract/approval/{user}/{month}` | `DELETE /api/work-contract/unlock/{user}/{month}` | Renamed endpoint |
| - | `DELETE /api/work-contract/lock/{user}/{month}` | **NEW:** Lock months for user |

The `entity` tool now supports both `lock_month` and `unlock_month` actions for user entities.

### Compliance Status
All consolidated tools have been analyzed for API compliance. Key findings:

#### ✅ Fully Compliant Tools
- `rate` - Rate management (all entities)
- `user_current` - Current user operations
- `absence` - Absence management (date format issues fixed)
- `timesheet` - Break field support added
- `entity` - metaFields support for Projects, Activities, Customers

#### ✅ Tools with Issues (Now Fixed)
- `calendar` - CalendarEvent model added, method calls corrected
- `entity` - Method name mismatches resolved, metaFields support added
- `timesheet` - Meta field update logic fixed, break field added
- `team_access` - Invalid teamlead parameter handling corrected
- `timer` - Timezone and tags handling improved
- `analyze_project_team` - DateTime parameter conversion fixed

#### ✅ User Preferences / Work Contract (v2.10.0)
The `entity` tool now supports `set_preferences` action for user entities, enabling work contract configuration:

| Preference | Description | Format |
|------------|-------------|--------|
| `work_contract_type` | Contract type | `"week"` or `"day"` |
| `hours_per_week` | Weekly hours (type=week) | Seconds (144000 = 40h) |
| `work_monday`..`work_sunday` | Daily hours (type=day) | Seconds (28800 = 8h) |
| `work_days_week` | Work days | `"1,2,3,4,5"` (1=Mon) |
| `holidays` | Vacation days/year | `"30"` |
| `public_holiday_group` | Holiday group ID | `"1"` |
| `work_start_day` / `work_last_day` | Contract period | `YYYY-MM-DD` |

**Example usage:**
```
entity type=user action=set_preferences id=5 preferences=[
  {"name": "work_contract_type", "value": "week"},
  {"name": "hours_per_week", "value": "144000"},
  {"name": "holidays", "value": "30"}
]
```

See `examples/usage_examples.md` for more detailed examples.

#### 🔧 Remaining Limitations
- `calendar` tool no longer supports `year`/`month` parameters (use `begin`/`end` instead)
- `team_access` tool no longer supports `teamlead` parameter in `add_member` action
- `meta` tool updates one field per API call (handles multiple fields by iteration)
- Some advanced API parameters not yet implemented (see individual tool schemas)

### API Compliance Guidelines
When modifying tools:

1. **Date Formats**: Use ISO 8601 format with time components for date parameters
2. **Meta Fields**: API accepts one meta field per request - iterate for multiple fields
3. **Method Names**: Ensure client method names match actual API endpoints
4. **Data Models**: Verify Pydantic models match API schemas with proper aliases
5. **Parameter Validation**: Check API documentation for supported parameters

### Common API Patterns
- **Filtering**: Most list endpoints support begin/end date filters in ISO format
- **Pagination**: Use size/page parameters for large datasets
- **Meta Fields**: PATCH endpoints for single name/value pairs
- **Permissions**: Many operations require specific permissions (noted in API docs)

### Testing API Compliance
```bash
# Test individual tools with real API
python -c "import asyncio; from kimai_mcp.client import KimaiClient; from kimai_mcp.tools.absence_manager import handle_absence; asyncio.run(test_tool())"
```