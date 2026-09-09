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
- `users.json` schema (see `src/kimai_mcp/user_config.py`): per slug `kimai_url`, `kimai_token`, optional `ssl_verify`, optional `auth_secret` (env override: `KIMAI_USER_<SLUG>_AUTH_SECRET`), optional `oidc_identity`. Slugs must match `^[a-zA-Z0-9_-]+$`; keys starting with `_` are comments. The former `kimai_user_id` field was removed and is ignored when present. With `--auto-provision`, users that are *not* in this file are added at runtime and exist only in memory unless `--provision-store` is set.

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

3a. **Automatic provisioning (`provisioning.py`)**: Optional (`--auto-provision`, off by default). Resolves a verified OIDC identity to an existing Kimai user and has Kimai mint that user's personal API token, so a user never has to be pre-declared in `users.json`. Hooks into exactly one place (the `match is None` branch of `oauth.py::handle_oidc_callback`) and returns the same `(slug, UserConfig)` shape as `get_user_by_oidc_identity()`, so every failure mode falls through to the pre-existing generic 403. Needs the `kimai-plugin/ApiTokenBundle` plugin on the Kimai server (core Kimai can only *delete* access tokens via the API) and an admin token with `api-token_other_profile`.
   - Matching runs strongest-rule-first and **aborts on ambiguity instead of guessing**, because a wrong match hands one employee another employee's token. The `/api/users/me` check on the minted token guards against a wrong *token*, not a wrong *match*, which is why the two name-based heuristics are behind `--provision-match fuzzy`.
   - Provisioned users are in-memory by default (like the OAuth tokens); `--provision-store FILE` persists them, `0600`, hand-written config always wins.
   - `UsersConfig.load(allow_empty=True)` and the softened `initialize_users()` check exist for this feature: a "sign in and nothing else" deployment has no users until someone signs in.
   - **`--provision-allowed-domains` bounds which identities may be onboarded.** Every rule except the two `exact` ones compares the address *local part* against Kimai usernames and aliases, so it is blind to the domain. With a multi-tenant issuer that makes `name@anywhere.example` match the Kimai user `name` as the single candidate, which the ambiguity guard cannot catch because there genuinely is only one. Unset keeps the old behaviour and warns at startup.
   - The admin token needs **`view_user`** as well as `api-token_other_profile`: `GET /api/users` carries its own `IsGranted`. `check_prerequisites()` probes both, because a token missing the first used to pass startup and then fail on every callback.
   - `UsersConfig.provisioned_slugs` separates runtime-created users from declared ones. Only the former may be dropped and re-minted, which is what `_handle_auth_failure` (Kimai answered 401) and the idle sweep in `_security_cleanup_loop` do. Without that split the persistent store could never recover from a revoked token, and sessions grew without bound.

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

Tracked against **Kimai 2.66.0** (2026-09-05). The server keeps working against older instances; features that need a specific version are marked as such in the tool schemas.

### Checking API compliance

Two scripts, run after every Kimai release:

```bash
# 1. Offline: models vs. Kimai's own schema definitions (needs the gh CLI only)
python scripts/audit_api_models.py 2.66.0

# 2. Online: what a real instance actually sends. GET requests only, safe
#    against production. Credentials come from the environment, never the repo.
KIMAI_URL=https://kimai.example.com KIMAI_API_TOKEN=... python scripts/verify_against_kimai.py
```

The offline audit derives each response schema from the serializer groups, so it catches "Kimai serializes a field our model drops". It also compares `models._DURATION_ALTERNATIVES` verbatim with the `$patterns` array in `src/Validator/Constraints/Duration.php`, because the client rejects duration input against that transcription before Kimai sees it. It is a lower bound: entity properties that come from PHP traits (`color`, `budget`, `timeBudget`, `budgetType`) are invisible to it, which is what the online check covers. Fields Kimai sends that are deliberately not modelled (`color-safe`, `apiToken`) are listed in both scripts with the reason; extend that list rather than weakening the check.

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

### Kimai 2.66 (implemented in v2.18.0)

Source: `gh api repos/kimai/kimai/compare/2.65.0...2.66.0`, UPGRADING.md and PRs #6103, #6131, #6139, #6140, #6141, #6143. Nothing in 2.17.x crashed against 2.66; the changes are about what a response *omits* and about new routes.

| Kimai | Change | Implementation |
|-------|--------|----------------|
| 2.66 | Timesheet `rate`, `internalRate` (group `Timesheet_Rate`) and, on entity responses, `fixedRate`, `hourlyRate` (`Timesheet_Entity_Rate`) are **omitted per record** unless the token holds `view_rate_own_timesheet` resp. `view_rate_other_timesheet` (`src/API/Serializer/RateExclusionStrategy.php`). The default `ROLE_USER` has neither. Applies to every timesheet endpoint incl. `/active`, `/recent`, stop/restart/duplicate and the new favorites | `TimesheetEntity.rate` defaults to `None` (was `0.0`) so "stripped" and "zero" stay distinguishable; `_handle_timesheet_get` prints `Rates: not visible to this token (...)` when all four are absent. The `Rate` model of the `/rates` endpoints is a different class and untouched |
| 2.66 | `budget`, `timeBudget`, `budgetType` moved from `*_Entity` to `Budget_Money` / `Budget_Time` (`src/Entity/BudgetTrait.php`) and are now in the **collection** responses of customers, projects and activities too, per record, only where the token holds the `budget` resp. `time` permission (`BudgetExclusionStrategy.php`) | No parse change (all three were Optional). `entity ... list` output now includes the budget lines. Stale "entity only" comments in `models.py`, the `filters.full` schema text and `test_customer_fields.py` corrected. **Absence is a permission signal, not a bug**, and the offline audit cannot see it: the fields come from a PHP trait, which `audit_api_models.py` does not parse |
| 2.66 | Project `lockedUntil` (`DateTimeImmutable<'Y-m-d'>`, group `Default`, so in listings too). Timesheets whose `begin` is on or before that calendar day are refused: `TimesheetVoter` (create/start/stop/duplicate/edit/delete -> **403**, admins included; a *running* record stays editable so its begin can be moved) and `TimesheetProjectLockedValidator` (**400** `The project is locked until %date%, please choose a later date.`, code `kimai-timesheet-project-locked-01`, path `begin_date`). Compared by `Ymd` integer, timezone-independent. `ProjectQuery` gained orderBy `project_locked_until` | `Project.locked_until` (`date`), `ProjectEditForm.locked_until` (`str`, verbatim), `lockedUntil` in the project `data` schema, `Locked Until:` line in `serialize_project`. `format_api_error()` hints on the 400 text and on every 403. **Same per-action date format as `start`/`end`**: `ProjectEditForm.php` copies the controller's `date_format` option into the `lockedUntil` field, and `ProjectController` passes `DATE_ONLY_FORMAT` on POST but `DATE_FORMAT` on PATCH |
| 2.66 | `DELETE /api/invoices/{id}` (`delete_invoice`, 204) ([#6141](https://github.com/kimai/kimai/pull/6141)) | `client.delete_invoice()`, `InvoiceEntityHandler.delete()` (was a hard error), `invoice` removed from `non_deletable` and added to the `batch_delete` map |
| 2.66 | `GET /api/favorites/timesheets` (`TimesheetCollectionExpanded`), `POST` / `DELETE /api/favorites/timesheets/{id}` (204; idempotent). Need `start_own_timesheet` and ownership ([#6143](https://github.com/kimai/kimai/pull/6143)) | `timer` actions `favorites`, `favorite`, `unfavorite`; client `get_favorite_timesheets()`, `add_favorite_timesheet()`, `remove_favorite_timesheet()`. Rows are Expanded like `/timesheets/active` (issue #24 pattern) |
| 2.66 | Invalid forms on customer/project/activity POST/PATCH and on rate POST answer **400** instead of 200-with-form | No change; `KimaiAPIError` already carried the details either way |
| 2.66 | Routes flagged `x: internal`: `POST /api/projects/{id}/duplicate`, `POST/DELETE /api/dashboard/widgets[/{widget}]`, `DELETE /api/users/roles/{id}`, `DELETE /api/invoices/documents/{id}`, `DELETE /api/invoices/templates/{id}` | **Deliberately not implemented.** Internal routes back the Kimai UI and may change without notice |

`scripts/verify_against_kimai.py` gained read-only probes for `/timesheets` (rate presence, `None` when stripped), `/projects` (`lockedUntil` on every row) and `/favorites/timesheets`, and version-gates the "budget stays out of listings" assertion that 2.66 made false.

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
| `Customer_Entity` | `get` / `create` / `update` only | the details above plus `contact`, `address`, `email`, **`invoiceEmail`**, `buyerReference` (and up to 2.65: `budget`, `timeBudget`, `budgetType`) |
| `Budget_Money` / `Budget_Time` (2.66+) | every response incl. listings, **per record** | `budget`, `timeBudget`, `budgetType`, only where the token holds the `budget` resp. `time` permission for that customer; missing means "not permitted", not "not set" |

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

**Work Contract auto-initialization (Kimai ≥ 2.61.0):** As of Kimai server [PR #5894](https://github.com/kimai/kimai/pull/5894) (fixes issue [#5751](https://github.com/kimai/kimai/issues/5751)), the API auto-initializes work-contract preferences for users who never configured one in the UI. `set_preferences` now works out of the box, **no UI pre-configuration required**.
- On older Kimai (**< 2.61.0**), `set_preferences` returns 404 for un-configured users; configure the work contract once in the UI first (the tool returns a hint with the exact URL).
- Caveat: auto-init covers `work_contract_type`, `work_monday`..`work_sunday`, `public_holiday_group`, `holidays`, `work_start_day`, `work_last_day`, but **not** `hours_per_week`. For a week-based contract, set `work_contract_type="week"` first (separate request), then set `hours_per_week`.
- Since **Kimai 2.63** the work-contract preferences are guarded more strictly (2.63 security note "Make sure that WorkContract preferences are correctly guarded"), so a 403 here means the token lacks the work-contract permission, as opposed to the 404 that signals an un-initialized contract on Kimai < 2.61.0.

See `examples/usage_examples.md` for more detailed examples.

#### `timeBudget`: seconds on the way out, a duration string on the way in

`budget` / `timeBudget` / `budgetType` exist on customers, projects and activities. Kimai only puts them on the API form when the token holds the `budget` resp. `time` permission for that entity (`budget_project`, `time_project`, ...); without it the request fails with `This form should not contain extra fields.`, which `format_api_error()` explains. `timeBudget` means two different things depending on direction; getting it wrong is a factor of **3600**:

| Direction | Type | Unit |
|---|---|---|
| Response (`Customer_Entity` / `Project_Entity` / `Activity_Entity`) | integer | **seconds** |
| Request (`DurationType` in `src/Form/EntityFormTrait.php`) | duration string | a bare number is **decimal hours** |

The write path is `DurationType` → `DurationStringToSecondsTransformer` → `Duration::parseDurationString()` (`src/Utils/Duration.php`, read at 2.65.0). Any bare number takes the `is_numeric()` branch into `parseDecimalFormat()`, which multiplies by 3600. So `"2"`, `"2.0"`, `"2h"` and `"2:00"` all mean **two hours**, while `"7200"` means **7200 hours**, not the two hours a `get` reported as `7200`. Sending JSON `7200` instead of `"7200"` changes nothing (Symfony's `Form::submit()` casts every scalar to a string before any transformer runs), which is why only an explicit duration form (`H:MM:SS`) is unambiguous.

`models._normalize_duration` (a `BeforeValidator` on the three `*EditForm.time_budget` fields and on `TimesheetEditForm.break_duration`, which Kimai binds to the same `DurationType`) resolves this:

- an **int is seconds**, matching the read models, and is rendered as an unambiguous `H:MM:SS` colon duration before it goes on the wire, so a value from `action=get` can be written straight back;
- a **str keeps Kimai's duration format** unchanged, validated locally against the alternatives in `src/Validator/Constraints/Duration.php` so a malformed value says what is wrong instead of drawing a bare 400. A bare-digit string (`"7200"`) is rejected as ambiguous: Kimai would read it as hours, but it is what a caller produces by copying the seconds from a `get`. `""` passes through and clears the value, as it does in Kimai.

`_serialize_budget` prints both units (`Time Budget: 2.00 hours (7200 seconds)`) for the same reason.

#### 🔧 Remaining Limitations
- `calendar` tool no longer supports `year`/`month` parameters (use `begin`/`end` instead)
- `team_access` tool no longer supports `teamlead` parameter in `add_member` action
- `meta` tool updates one field per API call for customer/project/activity/timesheet (handles multiple fields by iteration); `invoice` is the exception and sends all fields in a single request
- `team_access` revoke actions need the `permissions` permission on the customer/project/activity since **Kimai 2.65**, on top of `edit` on the team; a token that could revoke on 2.64 may get a 403 now
- `entity type=user action=set_preferences` can fail with 403 (not only 404) since **Kimai 2.63** tightened the work-contract guard
- `filters.full` for customer listings needs the `details_customer` permission; without it Kimai returns the short form silently rather than an error
- A project's `start` / `end` / `orderDate` / `lockedUntil` (2.66+) take **a different format per action**: `YYYY-MM-DD` on create, but the full `YYYY-MM-DDTHH:MM:SS` on update, which answers `"Please enter a valid date."` to a date-only value. `ProjectController` binds the same form with `DATE_ONLY_FORMAT` on POST and the HTML5 `DATE_FORMAT` on PATCH; projects are the only entity where the two differ. Stated in the `entity` project schema
- `budgetType` cannot be reverted from `month` to a lifetime budget through the tool: Kimai's PATCH keeps missing fields (`clearMissing=false`), and the client drops `None` values, so `null` never reaches the form. Use the Kimai UI
- Since **Kimai 2.66** timesheet rate fields and the customer/project/activity budget fields are **optional per record** (permission-gated serializer groups). A tool output without them is expected for a plain-user token; do not "fix" the models by defaulting them to zero
- Timesheets in a project's locked period (`lockedUntil`, 2.66+) cannot be changed by anyone, the API included. The tool surfaces the 403/400 with a hint; the only way past it is to move the begin or change the project's lock date
- `timer` favorites need `start_own_timesheet` and work on the user's own records only; Kimai returns 403 otherwise
- In **punch-in/out tracking mode** the timesheet API form has no `begin` / `end` field unless the token holds `view_other_timesheet` (`PunchInOutMode::canUpdateTimesWithAPI`). The tool therefore never sends a client-side `begin`; omitted means "now" on the server. A caller who passes `begin` explicitly on such an instance gets the extra-fields 400 with a hint
- Some advanced API parameters not yet implemented (see individual tool schemas)

### API Compliance Guidelines
When modifying tools:

1. **Date Formats**: Use ISO 8601 format with time components for date parameters
2. **Meta Fields**: API accepts one meta field per request (iterate for multiple fields) - except invoice meta, which takes all fields in a single request
3. **Method Names**: Ensure client method names match actual API endpoints
4. **Data Models**: Verify Pydantic models match API schemas with proper aliases
5. **Parameter Validation**: Check API documentation for supported parameters
6. **Write schemas are closed**: the customer, project and activity `data` sub-schemas are `additionalProperties: false` and `tools/registry.py::validate_arguments` enforces them, so a field missing from the schema is not merely undocumented: it cannot be sent at all. Adding a field to an `*EditForm` without adding it to the schema leaves it unreachable (this is how `budget`/`timeBudget`/`budgetType` were unwritable before #27)
7. **Never manufacture a write field.** Kimai builds every API form per token and per instance setting; a field on the wire that is not on the form fails the whole request with `This form should not contain extra fields.` The client drops only `None` (`model_dump(exclude_none=True)`), so a handler default such as `data.get("billable", True)` or a model default such as `= False` is sent on every request. Omitted means "Kimai default", nothing else. `tests/test_write_payloads.py` pins this from both ends: every write action driven with its minimal input must produce a payload whose keys are a subset of the caller's keys, and no `*Form` model may have a non-`None` default. PR #29 (`billable=True`) and the punch-mode `begin` were the two instances that motivated it

   Fields Kimai 2.66 only puts on the API form conditionally (from `src/API/*Controller.php`, `src/Form/**`):

   | Form | Field(s) | Present only when |
   |---|---|---|
   | Timesheet create/update | `begin`, `end` | tracking mode allows API times (punch-in/out: token has `view_other_timesheet`) |
   | | `billable` | `edit_billable_own/other_timesheet` |
   | | `fixedRate`, `hourlyRate` | `edit_rate_own/other_timesheet` |
   | | `exported` | `edit_export_own/other_timesheet` |
   | | `user` | `create_other_timesheet` (create) / `edit` (update) |
   | | `break` | Settings > Timesheet > Break time |
   | Customer / Project / Activity | `budget`, `budgetType` | `budget_*` permission on that entity |
   | | `timeBudget` | `time_*` permission |
   | | `teams` | create only |
   | Activity | `project` | create, or the activity is not global |
   | User create | `roles` | `roles` permission |
   | User update | `roles`; `enabled` (not on self); `language`, `locale`, `timezone` (`preferences`); `supervisor`; `systemAccount`, `requiresPasswordReset` (`password`) | respective permission |
   | Rates, Teams, Tags, Comments | none | always the full form |

### Common API Patterns
- **Filtering**: Most list endpoints support begin/end date filters in ISO format
- **Pagination**: Use size/page parameters for large datasets
- **Meta Fields**: PATCH endpoints for single name/value pairs
- **Permissions**: Many operations require specific permissions (noted in API docs)

### Testing API Compliance
See "Checking API compliance" above: `scripts/audit_api_models.py` (offline, models vs. schema definitions) and `scripts/verify_against_kimai.py` (online, read-only against a real instance).