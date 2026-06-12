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

# Run specific test file (available: test_oauth.py, test_security.py, test_timesheet_list.py)
pytest tests/test_oauth.py -v

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

There are two supported server types (plus a deprecated SSE server):

```bash
# 1. LOCAL MCP SERVER (for Claude Desktop)
python -m kimai_mcp --kimai-url=https://your-kimai.com --kimai-token=your-token
# or: kimai-mcp --kimai-url=... --kimai-token=...

# 2. STREAMABLE HTTP SERVER (for Claude.ai Connectors, OAuth 2.1 since v2.12.0)
python -m kimai_mcp.streamable_http_server --users-config=./config/users.json
# or: kimai-mcp-streamable --users-config=./config/users.json
# Production (behind HTTPS reverse proxy):
kimai-mcp-streamable --users-config ./config/users.json \
  --public-url https://mcp.example.com --trusted-proxy 127.0.0.1 \
  --oauth-state-file ./config/oauth_clients.json --disable-legacy-slugs
```

| Server | Command | Protocol | Use Case |
|--------|---------|----------|----------|
| Local | `kimai-mcp` | MCP Stdio | Claude Desktop local |
| Streamable | `kimai-mcp-streamable` | HTTP Streamable + OAuth 2.1 | Claude.ai Connectors |
| SSE | `kimai-mcp-server` | HTTP/SSE | **DEPRECATED, non-functional** (prints startup warning; use Streamable instead) |

Notes:
- `--kimai-user` / `KIMAI_DEFAULT_USER` is deprecated: accepted but ignored (warning is logged). Use the `user_scope` parameter of the tools instead.
- The streamable server serves an OAuth-protected `/mcp` endpoint (DCR + PKCE, login form at `/oauth/login` with user slug + `auth_secret`). The legacy `/mcp/{slug}` endpoints still work but are deprecated and can be disabled with `--disable-legacy-slugs`.
- `users.json` schema (see `src/kimai_mcp/user_config.py`): per slug `kimai_url`, `kimai_token`, optional `ssl_verify`, optional `auth_secret` (env override: `KIMAI_USER_<SLUG>_AUTH_SECRET`). Slugs must match `^[a-zA-Z0-9_-]+$`; keys starting with `_` are comments. The former `kimai_user_id` field was removed and is ignored when present.

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

1. **MCP Server (`server.py`)**: Local stdio server that handles MCP protocol communication and tool registration. **Uses consolidated tools (12 tools instead of the original 73)**: `entity`, `timesheet`, `timer`, `rate`, `team_access`, `absence`, `calendar`, `meta`, `user_current`, `analyze_project_team`, `config`, `comment`. Also contains the shared `format_api_error()` helper (status code + validation details, permission hint on 403).

2. **Streamable HTTP Server (`streamable_http_server.py`)**: Multi-user remote server for Claude.ai Connectors. Routes the OAuth-protected `/mcp` endpoint (token subject = user slug) and the deprecated legacy `/mcp/{slug}` endpoints to per-user MCP sessions. Includes rate limiting, security headers, enumeration protection and trusted-proxy handling.

3. **OAuth Provider (`oauth.py`)**: Embedded OAuth 2.1 authorization server (Dynamic Client Registration, mandatory PKCE S256, HTML login form at `/oauth/login` with user slug + `auth_secret`, opaque access tokens ~1h / refresh tokens ~30 days, in-memory token store, optional client persistence via state file).

4. **User Configuration (`user_config.py`)**: Multi-user configuration (`users.json` or env vars) with slug validation and per-user `auth_secret` support.

5. **SSE Server (`sse_server.py`)**: DEPRECATED and non-functional; kept only for backward compatibility, prints a startup warning.

6. **Kimai API Client (`client.py`)**: HTTP client wrapper using httpx for all Kimai API interactions. Handles authentication, request formatting, response parsing and auto-pagination for list endpoints.

7. **Data Models (`models.py`)**: Pydantic models for type-safe data structures representing Kimai entities (timesheets, projects, users, comments, etc.).

8. **Security Utilities (`security.py`)**: Rate limiting (token bucket), security headers middleware, enumeration protection, trusted-proxy-aware client IP extraction.

9. **Consolidated Tools (`tools/` directory)**:
   - `entity_manager.py`: Universal CRUD operations for all entities (`entity` tool)
   - `timesheet_consolidated.py`: All timesheet operations AND timer management (`timesheet` + `timer` tools)
   - `rate_manager.py`: Rate management across entities (`rate` tool)
   - `team_access_manager.py`: Team member and permission management (`team_access` tool)
   - `absence_manager.py`: Complete absence workflow (`absence` tool)
   - `calendar_meta.py`: Calendar, meta field and current-user operations (`calendar`, `meta`, `user_current` tools)
   - `comment_tool.py`: Project/customer comments - list/create/delete/pin (`comment` tool, Kimai 2.57+)
   - `config_info.py`: Server configuration info (`config` tool)
   - `project_analysis.py`: Advanced project analytics (`analyze_project_team` tool)
   - `user_discovery.py`: Shared helper to resolve accessible users (teams-first, parallel fetching)
   - `batch_utils.py`: Parallel batch operation utilities (asyncio.gather)
   - `absence_analytics.py` / `timesheet_analytics.py`: Calculation helpers for absence/timesheet statistics

### Key Design Patterns

1. **Action-Based Tools**: Tools use action parameters instead of separate tools (e.g., `entity` tool with `action: "create"` vs separate `create_entity` tool).

2. **Universal Entity Handler**: Single tool handles CRUD operations for all entity types using `type` and `action` parameters.

3. **Smart User Selection**: Tools like `timesheet` and `absence` implement intelligent user scope selection with `user_scope` enum ("self", "all", "specific"). Operations with `user_scope="all"` run their per-user API calls in parallel.

4. **Consolidated Error Handling**: Unified error handling patterns across all consolidated tools. API errors returned to the MCP client include the HTTP status code and validation details; 403 responses include a permission hint (Kimai 2.57/2.58 tightened API permissions).

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
- **Consolidated**: 12 multi-action tools with parameterized operations (entity, timesheet, timer, rate, team_access, absence, calendar, meta, user_current, analyze_project_team, config, comment)

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

### v2.12.0 Additions

- **`comment` tool** (12th tool, `tools/comment_tool.py`): Comments on projects and customers - actions `list`, `create`, `delete`, `pin` (toggle). Requires **Kimai 2.57+**. Markdown is supported in messages; pinned comments are listed first.
- **`meta` tool supports `invoice`** (requires **Kimai 2.56+**). Special case: invoice meta fields are sent in a SINGLE request containing all fields (`update_invoice_meta`); all other entity types still use one request per field.
- **OAuth 2.1** for the streamable HTTP server (see `oauth.py` and the server section above).

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
- `meta` tool updates one field per API call for customer/project/activity/timesheet (handles multiple fields by iteration); `invoice` is the exception and sends all fields in a single request
- Some advanced API parameters not yet implemented (see individual tool schemas)

### API Compliance Guidelines
When modifying tools:

1. **Date Formats**: Use ISO 8601 format with time components for date parameters
2. **Meta Fields**: API accepts one meta field per request (iterate for multiple fields) - except invoice meta, which takes all fields in a single request
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