# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
