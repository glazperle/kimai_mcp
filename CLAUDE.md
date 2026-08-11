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

There are two server types:

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

Notes:
- The SSE server (`sse_server.py`, command `kimai-mcp-server`) was **removed in v2.16.0**. It had been non-functional since v2.12.0 (broken transport wiring, and the SSE transport is no longer part of the MCP specification). The SDK still ships `mcp.server.sse`, so this was dead code in this project, not a forced removal.
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

1. **MCP Server (`server.py`)**: Local stdio server that handles MCP protocol communication and tool registration. **Uses consolidated tools (12 tools instead of the original 73)**: `entity`, `timesheet`, `timer`, `rate`, `team_access`, `absence`, `calendar`, `meta`, `user_current`, `analyze_project_team`, `config`, `comment`. Also contains the shared helpers used by both transports: `format_api_error()` (status code + validation details, permission hint on 403), `error_result()` (`CallToolResult(is_error=True)`) and `tool_result()` (wraps a handler's content list, required since SDK 2.x no longer wraps bare returns).

2. **Streamable HTTP Server (`streamable_http_server.py`)**: Multi-user remote server for Claude.ai Connectors. Routes the OAuth-protected `/mcp` endpoint (token subject = user slug) and the deprecated legacy `/mcp/{slug}` endpoints to per-user MCP sessions. Includes rate limiting, security headers, enumeration protection and trusted-proxy handling.

3. **OAuth Provider (`oauth.py`)**: Embedded OAuth 2.1 authorization server (Dynamic Client Registration, mandatory PKCE S256, HTML login form at `/oauth/login` with user slug + `auth_secret`, opaque access tokens ~1h / refresh tokens ~30 days, in-memory token store, optional client persistence via state file).

4. **User Configuration (`user_config.py`)**: Multi-user configuration (`users.json` or env vars) with slug validation and per-user `auth_secret` support.

5. **Kimai API Client (`client.py`)**: HTTP client wrapper using httpx for all Kimai API interactions. Handles authentication, request formatting, response parsing and auto-pagination for list endpoints.

6. **Data Models (`models.py`)**: Pydantic models for type-safe data structures representing Kimai entities (timesheets, projects, users, comments, etc.).

7. **Security Utilities (`security.py`)**: Rate limiting (token bucket), security headers middleware, enumeration protection, trusted-proxy-aware client IP extraction.

8. **Consolidated Tools (`tools/` directory)**:
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
   - `dates.py`: Strict `YYYY-MM-DD` parsing (`parse_iso_date`, `day_start`, `day_end`, `today`) shared by the absence and calendar tools

### Key Design Patterns

1. **Action-Based Tools**: Tools use action parameters instead of separate tools (e.g., `entity` tool with `action: "create"` vs separate `create_entity` tool).

2. **Universal Entity Handler**: Single tool handles CRUD operations for all entity types using `type` and `action` parameters.

3. **Smart User Selection**: Tools like `timesheet` and `absence` implement intelligent user scope selection with `user_scope` enum ("self", "all", "specific"). Operations with `user_scope="all"` run their per-user API calls in parallel.

4. **Consolidated Error Handling**: Unified error handling patterns across all consolidated tools. API errors returned to the MCP client include the HTTP status code and validation details; 403 responses include a permission hint (Kimai 2.57/2.58 tightened API permissions).

5. **Flexible Configuration**: Supports CLI arguments, environment variables, and .env files.

### MCP SDK 2.x contract (since v2.16.0)

The project requires `mcp>=2.0,<3` and therefore speaks protocol revision **2026-07-28** while still serving every earlier revision from the same server. What that means when touching either transport:

- Handlers are registered through the `Server(...)` **constructor** (`on_list_tools=`, `on_call_tool=`). The v1 decorators (`server.list_tools()(...)`) no longer exist.
- Handlers receive `(ctx: ServerRequestContext, params)` and must return a **result object**: `ListToolsResult(tools=...)` and `CallToolResult(...)`. A bare list is no longer wrapped, which is what `tool_result()` in `server.py` is for.
- Protocol model fields are snake_case (`input_schema`, `is_error`). camelCase still works when *constructing* a model (the SDK sets `alias_generator=to_camel`), but **attribute access** must use the snake_case name.
- Raising an exception no longer produces `is_error=true` automatically. Both transports catch `ToolError`/`KimaiAPIError`/`Exception` and return `error_result(...)` explicitly.
- `StreamableHTTPSessionManager` and the whole `mcp.server.auth.*` surface used by `oauth.py` are unchanged from 1.x, so the OAuth server needed no porting. `StreamableHTTPSessionManager` did gain `session_idle_timeout`, which defaults to `None` (sessions are then never reclaimed) and is set to 30 minutes here.
- **SDK 2.x no longer validates tool arguments server-side.** 1.x ran `jsonschema.validate(arguments, tool.inputSchema)` before the handler and answered `Input validation error: ...`; in 2.x jsonschema is client-side only. `tools/registry.py::validate_arguments` restores it, which matters because the entity `data` sub-schemas are `additionalProperties: false` while the Pydantic forms ignore extras, so an unvalidated typo would otherwise become an empty PATCH reported as success.
- `tests/test_mcp_protocol.py` drives both transports through a real in-memory `Client` session (handshake, `tools/list`, `tools/call`, `is_error`). Run it after any SDK bump: it is the test that catches a removed or renamed SDK API, which a handler-level unit test cannot (see issue #21).

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
- **Online Documentation**: https://www.kimai.org/documentation/rest-api.html
- **Schema sources** (what the audit script below reads): `config/packages/nelmio_api_doc.yaml` and `src/Entity/*.php` in [kimai/kimai](https://github.com/kimai/kimai) at the matching tag.
- A locally exported `api_documentation.json` may exist outside the repository; treat any such export as a snapshot of the version it was taken from, not as current truth. `api_documentation.json` is gitignored.

Tracked against **Kimai 2.65.0** (2026-08-11). The server keeps working against older instances; features that need a specific version are marked as such in the tool schemas.

### Checking API compliance

Two scripts, run after every Kimai release:

```bash
# 1. Offline: models vs. Kimai's own schema definitions (needs the gh CLI only)
python scripts/audit_api_models.py 2.66.0

# 2. Online: what a real instance actually sends. GET requests only, safe
#    against production. Credentials come from the environment, never the repo.
KIMAI_URL=https://kimai.example.com KIMAI_API_TOKEN=... python scripts/verify_against_kimai.py
```

The offline audit derives each response schema from the serializer groups, so it catches "Kimai serializes a field our model drops". It is a lower bound: entity properties that come from PHP traits (`color`, `budget`, `timeBudget`, `budgetType`) are invisible to it, which is what the online check covers. Fields Kimai sends that are deliberately not modelled (`color-safe`, `apiToken`) are listed in both scripts with the reason; extend that list rather than weakening the check.

### API Version Update (December 2024)

The following new API fields have been implemented:

#### New Fields Added
| Entity | Field | Type | Description |
|--------|-------|------|-------------|
| **Timesheet** | `break` | integer | Break duration in seconds. **Conditional:** Kimai only puts this field on the API form when 'Break time' is enabled (Settings > Timesheet). On an instance with it off, sending `break` fails the whole request with `This form should not contain extra fields.`; `format_api_error()` explains that. |
| **Project** | `metaFields` | array | Custom meta fields for projects |
| **Activity** | `metaFields` | array | Custom meta fields for activities |
| **Customer** | `metaFields` | array | Custom meta fields for customers |
| **Invoice** | `overdue` | boolean | Whether the invoice is overdue |

#### Removed Fields
- `TagEntity.color-safe` - no longer part of the tag schema. Note that `color-safe` still exists on customers, projects, activities, users and the embedded team stubs; it is `color` with a fallback applied and is deliberately not modelled (see `models.py` and the audit scripts).

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

### Kimai 2.62 - 2.65 (implemented in v2.16.0)

| Kimai | Change | Implementation |
|-------|--------|----------------|
| 2.63 | Customer gained `language` and `invoiceEmail` ([#5857](https://github.com/kimai/kimai/pull/5857), [#5855](https://github.com/kimai/kimai/pull/5855)) | `Customer` / `CustomerEditForm` in `models.py`, `entity` customer schema (its `data` object is `additionalProperties: false`, so an unlisted field cannot be sent), `serialize_customer()` |
| 2.62 | `GET /api/customers` accepts `full=0\|1` for the detail set | `CustomerFilter.full`, exposed as the boolean `filters.full` on `entity type=customer action=list`. Needs the `details_customer` permission; **without it Kimai silently returns the short form instead of a 403**, so absent detail fields are not necessarily a bug |

**Which customer fields come back where** (serializer groups in `src/Entity/Customer.php`, read at 2.65.0 - getting this wrong is easy and silent):

| Serializer group | Endpoint | Fields |
|---|---|---|
| `Default` | every response, plain listing included | id, name, number, comment, visible, billable, company, country, currency, timezone, phone, fax, mobile, homepage, **language**, **metaFields** |
| `Customer_Details` | listing **with `full=1`** | `vatId`, `addressLine1`-`3`, `postCode`, `city` |
| `Customer_Entity` | `get` / `create` / `update` only | the details above plus `contact`, `address`, `email`, **`invoiceEmail`**, `buyerReference`, `budget`, `timeBudget`, `budgetType` |

So `full=1` is **not** what surfaces `language` (that is `Default`) and **cannot** surface `invoiceEmail` (that is entity-only). `invoiceTemplate` and `invoiceText` are writable but never serialized back.
| 2.65 | Removing a team's customer/project/activity access additionally requires `IsGranted('permissions', ...)` on that entity | No code change; `team_access action=revoke` (handler `_handle_revoke_access`) can now return 403 where 2.64 succeeded. The permission hint in `format_api_error()` covers it |
| 2.63 | WorkContract preferences are guarded more strictly | No code change; `entity type=user action=set_preferences` can fail with 403 (not only 404) on instances where the token lacks the work-contract permission |
| 2.65 | `GET /api/tags` (plain string array) formally flagged deprecated | Already avoided: `client.get_tags_full()` uses `/tags/find`, and that is what the `entity type=tag` handler calls |
| 2.63 | POST on customer/project/activity applies Kimai defaults instead of `null` | No change needed; fields the tool omits now come back with the server default |
| 2.63 | Timesheet pagination got a stable id tie-breaker | No change needed; makes the client's auto-pagination reliable across pages |

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
- `timesheet` - Meta field update logic fixed, break field added (conditional, see above)
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

**Work Contract auto-initialization (Kimai ≥ 2.61.0):** As of Kimai server [PR #5894](https://github.com/kimai/kimai/pull/5894) (fixes issue [#5751](https://github.com/kimai/kimai/issues/5751)), the API auto-initializes work-contract preferences for users who never configured one in the UI. `set_preferences` now works out of the box — **no UI pre-configuration required**.
- On older Kimai (**< 2.61.0**), `set_preferences` returns 404 for un-configured users; configure the work contract once in the UI first (the tool returns a hint with the exact URL).
- Caveat: auto-init covers `work_contract_type`, `work_monday`..`work_sunday`, `public_holiday_group`, `holidays`, `work_start_day`, `work_last_day` — but **not** `hours_per_week`. For a week-based contract, set `work_contract_type="week"` first (separate request), then set `hours_per_week`.
- Since **Kimai 2.63** the work-contract preferences are guarded more strictly (2.63 security note "Make sure that WorkContract preferences are correctly guarded"), so a 403 here means the token lacks the work-contract permission, as opposed to the 404 that signals an un-initialized contract on Kimai < 2.61.0.

See `examples/usage_examples.md` for more detailed examples.

#### 🔧 Remaining Limitations
- `calendar` tool no longer supports `year`/`month` parameters (use `begin`/`end` instead)
- `team_access` tool no longer supports `teamlead` parameter in `add_member` action
- `meta` tool updates one field per API call for customer/project/activity/timesheet (handles multiple fields by iteration); `invoice` is the exception and sends all fields in a single request
- `team_access` revoke actions need the `permissions` permission on the customer/project/activity since **Kimai 2.65**, on top of `edit` on the team; a token that could revoke on 2.64 may get a 403 now
- `entity type=user action=set_preferences` can fail with 403 (not only 404) since **Kimai 2.63** tightened the work-contract guard
- `filters.full` for customer listings needs the `details_customer` permission; without it Kimai returns the short form silently rather than an error
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
See "Checking API compliance" above: `scripts/audit_api_models.py` (offline, models vs. schema definitions) and `scripts/verify_against_kimai.py` (online, read-only against a real instance).