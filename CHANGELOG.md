# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.14.0] - 2026-06-30

### Fixed

- **`entity` create/update raised `'MetaField' object has no attribute 'get'`** for projects, customers, and activities with custom meta fields. `create`/`update` return the `*Extended` models, whose `meta_fields` holds `MetaField` objects rather than dicts; the `serialize_*` branch was inverted and called dict's `.get()` on them. The entity is created before serialization, so the write succeeded despite the error. `list`/`get` were unaffected. (#17)
- **Tool execution errors are now reported with `isError=true`** so programmatic MCP clients can detect failures. Both transports (`server.py` and `streamable_http_server.py`) previously caught exceptions into a plain `TextContent` and returned a successful `CallToolResult` (`isError` unset), so a proxying gateway could not distinguish a `404`/crash from a normal payload. A shared `error_result()` helper now returns `CallToolResult(isError=True)` from the caught-exception paths and the streamable "client not initialized" guard, preserving the existing `format_api_error` message. (#18)

## [2.13.1] - 2026-06-19

Build and CI maintenance only; no functional or API changes.

### Fixed

- **Dockerfile is now resilient to Python base-image bumps.** The production stage copied installed packages from a hardcoded `/usr/local/lib/python3.11/site-packages` path, so any base-image bump (e.g. the Dependabot `python:3.11-slim` → `python:3.14-slim` update) broke the build with `"/usr/local/lib/python3.11/site-packages": not found`. The stage now copies `/usr/local` wholesale, which is version-agnostic, and the base image is bumped to `python:3.14-slim`.

### Changed

- **CI/CD action versions bumped** via Dependabot (#16): `actions/checkout` v4 → v7, `actions/setup-python` v5 → v6, `actions/upload-artifact` v4 → v7, `actions/download-artifact` v4 → v8, `docker/setup-buildx-action` v3 → v4, `docker/login-action` v3 → v4, `docker/metadata-action` v5 → v6, `docker/build-push-action` v5 → v7.

## [2.13.0] - 2026-06-19

Adds an optional OIDC federated-login backend for the Streamable HTTP server (#14) and refines the Work Contract setup guidance ([kimai/kimai#5751](https://github.com/kimai/kimai/issues/5751)). No breaking changes; the default `local` login behavior is unchanged.

### Added

- **Optional OIDC federated login for the Streamable HTTP server.** The server stays the OAuth 2.1 authorization server toward Claude.ai (same opaque tokens, DCR, PKCE) but can delegate the **login step** to any standard OpenID Connect provider (Microsoft Entra ID / Azure AD, Keycloak, Auth0, Google, Okta, …): `/authorize` redirects to the provider, the returned `id_token` is verified (JWKS signature, `iss`/`aud`/`exp`/`nonce`) and mapped to a configured user.
  - Enabled with `--auth-backend oidc`; configured via `--oidc-issuer`, `--oidc-client-id`, optional `--oidc-client-secret` (prefer `KIMAI_MCP_OIDC_CLIENT_SECRET`), `--oidc-scopes` (default `openid email profile`), `--oidc-identity-claim` (default `email`), `--oidc-discovery-url`. All have `KIMAI_MCP_OIDC_*` env equivalents.
  - Map each identity to a Kimai user via the new `oidc_identity` field in `users.json` (or `KIMAI_USER_<SLUG>_OIDC_IDENTITY`), matched case-insensitively against the identity claim.
  - Redirect URI to register at the provider: `<public-url>/oauth/oidc/callback`. Requires the `[server]` extra (pulls in `PyJWT[crypto]`). While OIDC is active, the built-in slug login form is not exposed.
  - When mapping by `email`, the `id_token` must assert `email_verified: true` (override with `--oidc-allow-unverified-email` for providers that only issue verified emails).

### Changed

- **`entity` `set_preferences` 404 hint** now leads with the real fix: upgrade Kimai to the release containing the work-contract auto-init fix (**≥ 2.61.0**, [kimai/kimai#5894](https://github.com/kimai/kimai/pull/5894)), which initializes work-contract preferences automatically. The Kimai-UI workaround is kept as a fallback for older servers (< 2.61.0). When the failing request includes `hours_per_week`, the hint adds that this preference is not auto-initialized (set `work_contract_type="week"` first).
- **Docs** (`CLAUDE.md`, `examples/usage_examples.md`) note that on Kimai ≥ 2.61.0 `set_preferences` works without configuring the work contract in the UI first, including the `hours_per_week` caveat.

## [2.12.1] - 2026-06-12

Follow-up patch addressing the points left open in 2.12.0. No breaking changes.

### Fixed

- **OAuth refresh tokens** now preserve their resource/audience binding across rotations (previously dropped to `None` after the first refresh) and are rejected when presented with a mismatched `client_id` (cross-client misuse).
- **OAuth client store** is no longer unbounded: dynamically registered clients are evicted after 30 days of inactivity (last-seen renewed on use) or once their secret expires; the state file is rewritten once after pruning.
- **Streamable HTTP server** now (re)initializes a user session on demand. A configured user whose startup init failed (e.g. Kimai briefly unreachable) no longer stays in a permanent error loop until the next restart; the endpoint returns 503 (was 403) while no session can be established.

### Changed (internal, no behavior change)

- Both servers now share a single tool registry (`tools/registry.py`) for the tool list and name→handler dispatch, removing the duplicated dispatch tables that could drift apart.
- `meta` tool uses a uniform handler map; invoice is no longer a special case.
- Comment client methods consolidated (8 → 4, parameterized by entity); `user_discovery` reuses the shared `execute_batch` helper.

## [2.12.0] - 2026-06-12

### Upgrade Notes

Nothing breaks for existing setups, but please note:

- **Dependency bump**: `mcp>=1.27.0` is now required (was `>=0.9.0`). `pip install --upgrade kimai-mcp` handles this automatically.
- **Streamable HTTP server**: Your existing `/mcp/{slug}` URLs keep working, but they are now deprecated in favor of OAuth 2.1 (see below). The server logs a warning at startup if a slug has low entropy — treat slug URLs like passwords or migrate to OAuth. Use `--disable-legacy-slugs` to turn slug URLs off entirely.
- **users.json**: The `kimai_user_id` field never had any effect and has been removed. Files that still contain it keep loading (the field is ignored). Slugs must match `[a-zA-Z0-9_-]+`; anything else is now rejected at startup.
- **SSE server (`kimai-mcp-server`) is deprecated**: It was non-functional (broken transport wiring) and now prints a deprecation warning. Migrate remote setups to `kimai-mcp-streamable`.
- **`--kimai-user` / `KIMAI_DEFAULT_USER` is deprecated**: It never had any effect; it is still accepted but ignored (with a warning). Remove it from your configs.
- **Error output format changed**: API errors returned to the MCP client now include the HTTP status, validation details, and a permission hint on 403. Only relevant if you parse error strings.
- **Kimai server version requirements for new features**: the `comment` tool requires Kimai 2.57+, invoice meta fields require Kimai 2.56+. Everything else works with older Kimai versions as before.

### Added

- **OAuth 2.1 for the Streamable HTTP server** (Claude.ai Connectors)
  - New protected `/mcp` endpoint (no slug) with Bearer-token authentication
  - Dynamic Client Registration, mandatory PKCE (S256), refresh-token rotation
  - Login form at `/oauth/login` (user slug + new per-user `auth_secret` in users.json or `KIMAI_USER_<SLUG>_AUTH_SECRET`)
  - New CLI options / env vars: `--public-url` (`KIMAI_MCP_PUBLIC_URL`), `--trusted-proxy` (`KIMAI_MCP_TRUSTED_PROXIES`), `--disable-legacy-slugs` (`KIMAI_MCP_DISABLE_LEGACY_SLUGS`), `--oauth-state-file` (`KIMAI_MCP_OAUTH_STATE_FILE`)
- **New `comment` tool** (12th tool): list/create/delete/pin comments on projects and customers (Kimai 2.57+)
- **Invoice meta fields**: `meta` tool now supports `entity: "invoice"` (Kimai 2.56+); all fields are sent in a single request
- Dispatch smoke tests covering every tool action against a spec'd client mock, plus OAuth/security test suites

### Fixed

- **Five completely broken tool actions** (called non-existent client methods or wrong signatures): `timesheet export_toggle`, `timesheet batch_export`, `absence batch_approve`, `entity invoice list`, `entity holiday list`, and `meta update` (passed a list where the API client expects single fields)
- `entity holiday list` / holiday calendar returned 400 from Kimai because dates were sent date-only; they now use full ISO datetime (verified against Kimai 2.60.0)
- `timer active` crashed with a timezone error as soon as a timer was running
- Tool outputs contained literal `\n` text instead of line breaks (~270 occurrences)
- Rate listing never showed internal rate and fixed/hourly type; absence listing never showed end date and half-day flag (wrong attribute names)
- `entity project list` ignored the `term` search filter
- Broken JSON schema keyword (`allOff`) disabled conditional validation in the `entity` tool
- Auto-pagination in the client was unreachable from the `timesheet` tool and ignored singular entity filters
- MCP handshake reported hardcoded version 2.0.0 instead of the package version
- httpx client leak when a user session failed to initialize (Streamable HTTP server)
- Rate-limiter and enumeration-protection cleanup never ran (unbounded memory growth)
- `X-Forwarded-For` was trusted unconditionally, allowing rate-limit bypass; now only honored behind a configured `--trusted-proxy`

### Changed

- Centralized error handling: API errors now reach the client with status code, validation details, and a 403 permission hint (relevant since Kimai 2.57/2.58 enforce permissions more strictly)
- Performance: `user_scope="all"` operations (absences, statistics, attendance, bulk lock/unlock) now run user lookups and per-user requests in parallel; shared user-discovery helper replaces six duplicated code paths; `config type=all` fetches in parallel; tag listing filters server-side
- `analyze_project_team` stops fetching at the dataset limit instead of discarding data afterwards, and searches projects server-side

### Deprecated

- SSE server (`kimai-mcp-server`) — non-functional, use `kimai-mcp-streamable`
- `--kimai-user` / `KIMAI_DEFAULT_USER` — never had any effect
- `/mcp/{slug}` URLs on the Streamable HTTP server — use OAuth at `/mcp`

### Removed

- `kimai_user_id` from users.json / `KIMAI_USER_*_USER_ID` env vars (dead configuration)
- `sse-starlette` dependency (unused)

## [2.11.3] - 2026-04-21

### Fixed

- Timesheet list no longer crashes when `begin`/`end` filters are missing (#12, #13)

## [2.11.2] - 2026-01-07

### Fixed

- Version is imported from `__init__.py` instead of being hardcoded in `server.py`

## [2.11.1] - 2026-01-01

### Changed

- Better work contract error handling

## [2.10.0] - 2025-12-31

### Added

- **User Preferences Management** - New `set_preferences` action for user entities in the `entity` tool
  - Configure work contracts (weekly or daily hours)
  - Set vacation days and public holiday groups
  - Define contract start/end dates
  - Set user rates (hourly/internal)
  - Supports both "week" type (total hours) and "day" type (per-weekday hours)
- New client method `update_user_preferences()` for PATCH `/api/users/{id}/preferences`
- New `UserPreference` Pydantic model for preference name-value pairs
- Documentation for all work contract preferences in `examples/usage_examples.md`

### Changed

- `entity` tool now accepts `preferences` parameter for user type with `set_preferences` action

## [2.9.0] - 2025-12-30

### Added

- **Comprehensive Security Module** - New `security.py` with enterprise-grade security features
  - **Rate Limiting**: Token bucket algorithm to prevent DoS and brute-force attacks (configurable via `--rate-limit-rpm`)
  - **Session Management**: Maximum concurrent sessions and TTL-based expiration (configurable via `--max-sessions`, `--session-ttl`)
  - **Security Headers**: Automatic X-Content-Type-Options, X-Frame-Options, X-XSS-Protection headers
  - **Enumeration Protection**: Random delays on 404 responses and automatic blocking after excessive failed requests
- New CLI arguments for security configuration:
  - `--rate-limit-rpm`: Requests per minute per IP (default: 60, 0 to disable)
  - `--max-sessions`: Maximum concurrent sessions (default: 100, SSE server only)
  - `--session-ttl`: Session timeout in seconds (default: 3600, SSE server only)
  - `--require-https`: Enforce HTTPS connections (SSE server only)
- Environment variable support: `RATE_LIMIT_RPM`, `MAX_SESSIONS`, `SESSION_TTL`, `REQUIRE_HTTPS`
- Unit tests for all security components in `tests/test_security.py`

### Changed

- **CORS Security Fix**: `allow_credentials=False` when using wildcard origins (`*`) to prevent credential theft
- **Removed X-Session-ID Header**: Session IDs no longer exposed in HTTP response headers

### Removed

- **`/users` Endpoint** (Streamable HTTP Server): Removed to prevent user/endpoint enumeration attacks
- **User slugs in `/health` response** (Streamable HTTP Server): Now only returns `user_count` instead of full user list

### Security

- Fixed potential session hijacking via overly permissive CORS configuration
- Fixed unbounded session growth that could lead to memory exhaustion
- Fixed timing-based user enumeration via 404 response times
- Added protection against brute-force attacks on MCP endpoints

### Migration Notes

- The `/users` endpoint is no longer available - administrators should track user slugs separately
- Health check response format changed: `users` array replaced with `user_count` integer
- Rate limiting is enabled by default (60 req/min) - set `--rate-limit-rpm=0` to disable

## [2.8.0] - 2025-12-30

### Added

- **Streamable HTTP Server for Claude.ai Connectors** - New `streamable_http_server.py` enables integration with Claude.ai custom connectors
  - Works with Claude.ai web and mobile apps
  - Multi-user support with per-user endpoints (`/mcp/{user_slug}`)
  - Server-side Kimai credential management via `users.json`
- **User Configuration System** - New `user_config.py` for managing multiple user credentials
  - JSON-based configuration file (`config/users.json`)
  - Support for per-user Kimai URL, token, and settings
- New CLI entry point `kimai-mcp-streamable` for running the Streamable HTTP server
- Example configuration template `config/users.example.json`

### Changed

- Docker default command changed from `kimai-mcp-server` to `kimai-mcp-streamable`
- Docker Compose now mounts `config/users.json` for user configuration

### Migration Notes

- Existing SSE server users: No changes required, use `kimai-mcp-server`
- Docker users: Default behavior changed to Streamable HTTP - override CMD if SSE is preferred

## [2.7.0] - 2025-12-29

### Added
- **Remote MCP Server with HTTP/SSE Transport** - New `sse_server.py` enables remote deployment of the MCP server, allowing multiple clients to connect via HTTP/SSE
- **Per-Client Kimai Authentication** - Each client can now use their own Kimai credentials when connecting to the remote server
- **Docker Support** - Complete Docker deployment with multi-architecture images (amd64/arm64)
  - New `Dockerfile` for containerized deployment
  - New `docker-compose.yml` for easy orchestration
  - GitHub Actions workflow for automatic Docker image publishing to GHCR
- **Deployment Documentation** - Comprehensive guide in `DEPLOYMENT.md` for remote server setup
- **Release Process Documentation** - Step-by-step release guide in `RELEASING.md`
- New CLI entry point `kimai-mcp-server` for running the SSE server

### Changed
- Added `[server]` optional dependencies in `pyproject.toml` for FastAPI, Uvicorn, and SSE-Starlette

## [2.6.0] - 2024-12-XX

### Added
- Batch operations for absences, timesheets, and entities
- Auto-split for absences exceeding 30-day limit
- Attendance action to show who is present today
- Absence analytics and improved permission handling

### Fixed
- Filter attendance to show only active employees
- Auto-split year-crossing absences for Kimai compatibility

## [2.5.x] - 2024-12-XX

### Added
- Attendance tracking features
- CLI improvements with `--help`, `--version`, and `--setup` wizard

### Fixed
- Correct `user_scope='all'` handling for timesheets and absences

## [2.3.x] - 2024-XX-XX

### Added
- Consolidated tools architecture (73 tools → 10 tools)
- Universal entity handler for CRUD operations
- Smart user selection with `user_scope` enum

### Changed
- 87% reduction in tool count while maintaining all functionality
