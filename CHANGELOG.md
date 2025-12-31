# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
