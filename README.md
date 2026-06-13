# Kimai MCP Server

[![PyPI version](https://badge.fury.io/py/kimai-mcp.svg)](https://pypi.org/project/kimai-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

A comprehensive Model Context Protocol (MCP) server for integrating with the Kimai time-tracking API. This server allows AI assistants like Claude to efficiently interact with Kimai instances to manage time tracking, projects, activities, customers, users, teams, absences, and more.

## 🚀 Quick Start

### Local Installation (Single User)

```bash
# Install from PyPI
pip install kimai-mcp

# Run with your Kimai credentials
kimai-mcp --kimai-url=https://your-kimai.com --kimai-token=your-token

# Or use the interactive setup wizard
kimai-mcp --setup
```

### 🌐 Remote Server Deployment (Recommended for Teams)

**For enterprise/team environments:** Deploy the server once and let all users connect remotely!

#### Server Types

| Server | Command | Best For |
|--------|---------|----------|
| **Local** | `kimai-mcp` | Claude Desktop, single user, development |
| **Streamable HTTP** | `kimai-mcp-streamable` | Claude.ai Connectors (web/mobile), teams |
| **SSE Server** | `kimai-mcp-server` | **Deprecated** — do not use (see below) |

> **Deprecation notice:** The SSE server (`kimai-mcp-server`) is deprecated and not functional (the SSE transport was removed from the MCP specification). It prints a startup warning. Use the Streamable HTTP server (`kimai-mcp-streamable`) instead.

#### Quick Start with Docker (Streamable HTTP + OAuth)

Since v2.12.0 the Streamable HTTP server includes an OAuth 2.1 authorization server. Users authenticate with a user slug and a per-user `auth_secret` instead of a secret URL.

```bash
# 1. Generate a random slug and an auth_secret per user
python -c "import secrets; print(secrets.token_urlsafe(16))"   # slug
python -c "import secrets; print(secrets.token_urlsafe(32))"   # auth_secret

# 2. Create config file
mkdir config
cat > config/users.json << 'EOF'
{
  "xK9mP2qW7vL4aB8c": {
    "kimai_url": "https://your-kimai.com",
    "kimai_token": "your-api-token",
    "auth_secret": "long-random-oauth-login-secret"
  }
}
EOF

# 3. Start server
docker-compose up -d
```

> **Security Warning:** Use random slugs, NOT usernames! The server warns at startup about low-entropy slugs (shorter than 16 characters or plain lowercase words). Slugs may only contain letters, digits, `-` and `_`.

#### Claude.ai Connectors Integration (OAuth)

The Streamable HTTP server works with Claude.ai custom connectors:

1. Set an `auth_secret` for each user in `users.json` (see above)
2. Run the server behind an HTTPS reverse proxy:
   ```bash
   kimai-mcp-streamable \
     --users-config ./config/users.json \
     --public-url https://mcp.example.com \
     --trusted-proxy 127.0.0.1 \
     --oauth-state-file ./config/oauth_clients.json \
     --disable-legacy-slugs
   ```
3. In Claude.ai: **Settings → Connectors → Add custom connector**
4. Enter URL: `https://mcp.example.com/mcp` (no slug in the URL)
5. Claude.ai registers itself automatically (Dynamic Client Registration). When connecting, a login page appears — enter your user slug and `auth_secret`.

Access tokens are valid for 1 hour and refreshed automatically (refresh tokens up to 30 days). Tokens are kept in memory, so users must reconnect after a server restart.

**Legacy endpoints:** The previous per-user URLs `/mcp/{slug}` still work but are deprecated. Migrate to the OAuth endpoint `/mcp` and start the server with `--disable-legacy-slugs`.

#### OIDC federated login (optional)

Instead of the built-in slug + `auth_secret` form, the Streamable HTTP server can delegate user authentication to any standard **OpenID Connect** provider (Microsoft Entra ID / Azure AD, Keycloak, Auth0, Google, Okta, …). The server stays the OAuth 2.1 authorization server toward Claude.ai (same opaque tokens, DCR and PKCE); it only federates the login step: `/authorize` redirects to your OIDC provider, the `id_token` is verified (signature via JWKS, `iss`/`aud`/`exp`/`nonce`), and the resulting identity is mapped to a configured user.

```bash
kimai-mcp-streamable \
  --users-config ./config/users.json \
  --public-url https://mcp.example.com \
  --auth-backend oidc \
  --oidc-issuer https://login.microsoftonline.com/<tenant-id>/v2.0 \
  --oidc-client-id <client-id>
# Confidential clients: set KIMAI_MCP_OIDC_CLIENT_SECRET (env preferred over the CLI flag).
```

Map each OIDC identity to a Kimai user by adding the `oidc_identity` field (matched case-insensitively against `--oidc-identity-claim`, default `email`):

```json
{
  "x7Kp2mQ9wL4r": {
    "kimai_url": "https://kimai.example.com",
    "kimai_token": "api_token_for_alice",
    "oidc_identity": "alice@example.com"
  }
}
```

Register **`<public-url>/oauth/oidc/callback`** as the redirect URI at your OIDC provider. Requires the `[server]` extra (`pip install "kimai-mcp[server]"`, which pulls in `PyJWT[crypto]`). The built-in slug login form is not exposed while the OIDC backend is active.

When mapping by `email`, the `id_token` must also assert `email_verified: true`, otherwise the email claim is ignored — so a provider that lets users self-assert an unverified address cannot impersonate a mapped user. For providers that do not emit `email_verified` but are trusted to only issue verified emails, pass `--oidc-allow-unverified-email` (or `KIMAI_MCP_OIDC_ALLOW_UNVERIFIED_EMAIL=true`).

📖 **[See full deployment guide →](DEPLOYMENT.md)**

## Command Line Options

Options for the local server (`kimai-mcp`):

| Option | Description |
| ------ | ----------- |
| `--kimai-url URL` | Kimai server URL (e.g., `https://kimai.example.com`) |
| `--kimai-token TOKEN` | API authentication token from your Kimai user profile |
| `--kimai-user USER_ID` | **Deprecated** — accepted but ignored (use the `user_scope` parameter of the tools instead) |
| `--ssl-verify VALUE` | SSL verification: `true` (default), `false`, or path to CA certificate |
| `--setup` | Interactive setup wizard for Claude Desktop configuration |
| `--help` | Show help message and exit |
| `--version` | Show version number and exit |

Options for the Streamable HTTP server (`kimai-mcp-streamable`):

| Option | Environment variable | Description |
| ------ | -------------------- | ----------- |
| `--host HOST` | — | Host to bind to (default: `0.0.0.0`) |
| `--port PORT` | — | Port to bind to (default: `8000`) |
| `--users-config FILE` | `USERS_CONFIG_FILE` | Path to `users.json` |
| `--public-url URL` | `KIMAI_MCP_PUBLIC_URL` | Public base URL, used as OAuth issuer/resource URL (required behind a reverse proxy) |
| `--oauth-state-file FILE` | `KIMAI_MCP_OAUTH_STATE_FILE` | JSON file to persist registered OAuth clients across restarts |
| `--disable-legacy-slugs` | `KIMAI_MCP_DISABLE_LEGACY_SLUGS` | Disable the deprecated `/mcp/{slug}` endpoints |
| `--trusted-proxy IP` | `KIMAI_MCP_TRUSTED_PROXIES` (comma-separated) | Reverse proxy IPs whose `X-Forwarded-For`/`X-Real-IP` headers are honored; may be given multiple times |
| `--rate-limit-rpm N` | `RATE_LIMIT_RPM` | Maximum requests per minute per IP (default: 60, 0 to disable) |
| `--auth-backend {local,oidc}` | `KIMAI_MCP_AUTH_BACKEND` | Login backend: `local` (built-in slug form, default) or `oidc` (federate to an external OIDC provider) |
| `--oidc-issuer URL` | `KIMAI_MCP_OIDC_ISSUER` | OIDC issuer URL (required for `--auth-backend oidc`) |
| `--oidc-client-id ID` | `KIMAI_MCP_OIDC_CLIENT_ID` | OIDC client ID (required for `--auth-backend oidc`) |
| `--oidc-client-secret SECRET` | `KIMAI_MCP_OIDC_CLIENT_SECRET` | OIDC client secret (optional; public/PKCE-only if omitted — prefer the env var) |
| `--oidc-scopes SCOPES` | `KIMAI_MCP_OIDC_SCOPES` | Requested scopes (default: `openid email profile`) |
| `--oidc-identity-claim CLAIM` | `KIMAI_MCP_OIDC_IDENTITY_CLAIM` | id_token claim mapped to a user's `oidc_identity` (default: `email`) |
| `--oidc-discovery-url URL` | `KIMAI_MCP_OIDC_DISCOVERY_URL` | Override the discovery URL (default: `<issuer>/.well-known/openid-configuration`) |

## 🛠️ Available Tools

### Core Management Tools
1. **Entity Tool** (`entity`) - Universal CRUD operations for projects, activities, customers, users, teams, tags, invoices, holidays
2. **Timesheet Tool** (`timesheet`) - Complete timesheet management (list, create, update, delete, export, batch operations)
3. **Timer Tool** (`timer`) - Active timer operations (start, stop, restart, view active/recent)
4. **Rate Tool** (`rate`) - Rate management across all entity types
5. **Team Access Tool** (`team_access`) - Team member and permission management
6. **Absence Tool** (`absence`) - Complete absence workflow (create, approve, reject, list, attendance, batch operations, auto-split)
7. **Calendar Tool** (`calendar`) - Unified calendar data access
8. **Meta Tool** (`meta`) - Custom field management for customers, projects, activities, timesheets, and invoices (invoice meta requires Kimai 2.56+)
9. **User Current Tool** (`user_current`) - Current user information
10. **Project Analysis Tool** (`analyze_project_team`) - Advanced project analytics
11. **Config Tool** (`config`) - Server configuration (timesheet settings, color codes, plugins, version info)
12. **Comment Tool** (`comment`) - Comments on projects and customers: list, create, delete, pin (requires Kimai 2.57+)

### Complete Kimai Integration
- **Timesheet Management** - Create, update, delete, start/stop timers, view active timers
- **Project & Activity Management** - Browse and view projects and activities
- **Customer Management** - Browse and view customer information
- **User Management** - List, view, create, update user accounts, and configure work contracts (preferences)
- **Team Management** - Create teams, manage members, control access permissions
- **Absence Management** - Create, approve, reject, and track absences
- **Tag Management** - Create and manage tags for better organization
- **Invoice Queries** - View invoice information and status
- **Comments** - Manage pinned and regular comments on projects and customers (Kimai 2.57+)

### Advanced Features
- **Real-time Timer Control** - Start, stop, and monitor active time tracking
- **Comprehensive Filtering** - Advanced filters for all data types
- **Permission Management** - Respect Kimai's role-based permissions
- **Error Handling** - API errors are reported with status code and validation details; 403 responses include a permission hint (Kimai 2.57/2.58 enforce API permissions more strictly)
- **Flexible Configuration** - Multiple configuration methods (CLI args, .env files, environment variables)

## Installation

### Prerequisites
- Python 3.10+
- A Kimai instance with API access enabled
- API token from your Kimai user profile

### Install from PyPI (Recommended)

```bash
pip install kimai-mcp
```

### Install from Source (Development)

```bash
# Clone the repository
git clone https://github.com/glazperle/kimai_mcp.git
cd kimai_mcp

# Install in development mode
pip install -e ".[dev]"
```

## Configuration

### Getting Your Kimai API Token

1. Log into your Kimai instance
2. Go to your user profile (click your username)
3. Navigate to the "API" or "API Access" section
4. Create a new API token or copy an existing one
5. Note your Kimai instance URL (e.g., `https://kimai.example.com`)

## Claude Desktop Integration

### Step 1: Configure Claude Desktop

Add the Kimai MCP server to your Claude Desktop configuration file:

**On macOS:**
`~/Library/Application Support/Claude/claude_desktop_config.json`

**On Windows:**
`%APPDATA%\Claude\claude_desktop_config.json`

### Step 2: Add Configuration

Add the following to your Claude Desktop configuration:

```json
{
  "mcpServers": {
    "kimai": {
      "command": "kimai-mcp",
      "args": [
        "--kimai-url=https://your-kimai-instance.com",
        "--kimai-token=your-api-token-here"
      ]
    }
  }
}
```

**Important Notes:**
- Replace `https://your-kimai-instance.com` with your actual Kimai URL
- Replace `your-api-token-here` with your API token from Kimai
- The `kimai-mcp` command is available after `pip install kimai-mcp`

**Alternative:** If `kimai-mcp` is not in your PATH, use `python -m kimai_mcp.server` instead:
```json
{
  "mcpServers": {
    "kimai": {
      "command": "python",
      "args": [
        "-m", "kimai_mcp.server",
        "--kimai-url=https://your-kimai-instance.com",
        "--kimai-token=your-api-token-here"
      ]
    }
  }
}
```

### Step 3: Restart Claude Desktop

After saving the configuration file, restart Claude Desktop for the changes to take effect.

### Alternative Configuration Methods

#### Method 1: Using a .env File (Recommended for Development)
If you prefer using a .env file for configuration, create a `.env` file in your project directory:

```bash
# .env file in the kimai_mcp directory
KIMAI_URL=https://your-kimai-instance.com
KIMAI_API_TOKEN=your-api-token-here
KIMAI_SSL_VERIFY=true  # or path to CA certificate
```

Then use this Claude Desktop configuration:
```json
{
  "mcpServers": {
    "kimai": {
      "command": "kimai-mcp",
      "cwd": "/path/to/your/kimai_mcp/directory"
    }
  }
}
```

**Important Notes for .env Configuration:**
- Replace `/path/to/your/kimai_mcp/directory` with the actual path to your kimai_mcp directory
- The `cwd` parameter ensures the .env file is found in the correct directory
- Keep your .env file secure and never commit it to version control
- On Windows, use forward slashes in the path or escape backslashes

**Example Windows Path:**
```json
{
  "mcpServers": {
    "kimai": {
      "command": "kimai-mcp",
      "cwd": "C:/Users/YourName/Projects/kimai_mcp"
    }
  }
}
```

#### Method 2: Using Environment Variables (System-wide)
If you prefer system environment variables, you can set:
```bash
export KIMAI_URL="https://your-kimai-instance.com"
export KIMAI_API_TOKEN="your-api-token-here"
```

Then use this Claude Desktop configuration:
```json
{
  "mcpServers": {
    "kimai": {
      "command": "kimai-mcp"
    }
  }
}
```

## Usage Examples

### Timesheet Management

#### List Timesheets
```json
{
  "tool": "timesheet",
  "parameters": {
    "action": "list",
    "filters": {
      "project": 17,
      "user_scope": "self"
    }
  }
}
```

#### Create a Timesheet Entry
```json
{
  "tool": "timesheet",
  "parameters": {
    "action": "create",
    "data": {
      "project": 1,
      "activity": 5,
      "description": "Working on API integration",
      "begin": "2024-08-03T09:00:00",
      "end": "2024-08-03T10:30:00"
    }
  }
}
```

#### Start a Timer
```json
{
  "tool": "timer",
  "parameters": {
    "action": "start",
    "data": {
      "project": 1,
      "activity": 5,
      "description": "Working on API integration"
    }
  }
}
```

#### Stop a Timer
```json
{
  "tool": "timer",
  "parameters": {
    "action": "stop",
    "id": 12345
  }
}
```

### Project & Activity Management

#### List Projects
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

#### Get Project Details
```json
{
  "tool": "entity",
  "parameters": {
    "type": "project",
    "action": "get",
    "id": 17
  }
}
```

#### List Activities
```json
{
  "tool": "entity",
  "parameters": {
    "type": "activity",
    "action": "list",
    "filters": {"project": 17}
  }
}
```

### User & Team Management

#### List Users
```json
{
  "tool": "entity",
  "parameters": {
    "type": "user",
    "action": "list"
  }
}
```

#### Create a Team
```json
{
  "tool": "entity",
  "parameters": {
    "type": "team",
    "action": "create",
    "data": {
      "name": "Development Team",
      "color": "#3498db"
    }
  }
}
```

#### Add Team Member
```json
{
  "tool": "team_access",
  "parameters": {
    "action": "add_member",
    "team_id": 1,
    "user_id": 5
  }
}
```

### Absence Management

#### Create an Absence
```json
{
  "tool": "absence",
  "parameters": {
    "action": "create",
    "data": {
      "comment": "Vacation in the mountains",
      "date": "2024-02-15",
      "end": "2024-02-20",
      "type": "holiday"
    }
  }
}
```

#### List Absences
```json
{
  "tool": "absence",
  "parameters": {
    "action": "list",
    "filters": {
      "user": "5",
      "status": "all"
    }
  }
}
```

#### Check Attendance (Who is Present Today)

```json
{
  "tool": "absence",
  "parameters": {
    "action": "attendance",
    "date": "2024-12-29"
  }
}
```

Returns a report showing present and absent employees with absence reasons.

### Batch Operations

Batch operations allow executing multiple API calls in parallel for efficient bulk processing.

#### Batch Delete Absences
```json
{
  "tool": "absence",
  "parameters": {
    "action": "batch_delete",
    "ids": [1, 2, 3, 4, 5]
  }
}
```

#### Batch Approve Absences
```json
{
  "tool": "absence",
  "parameters": {
    "action": "batch_approve",
    "ids": [10, 11, 12, 13]
  }
}
```

#### Batch Delete Timesheets
```json
{
  "tool": "timesheet",
  "parameters": {
    "action": "batch_delete",
    "ids": [100, 101, 102, 103]
  }
}
```

#### Batch Export Timesheets
```json
{
  "tool": "timesheet",
  "parameters": {
    "action": "batch_export",
    "ids": [200, 201, 202]
  }
}
```

#### Batch Delete Entities
```json
{
  "tool": "entity",
  "parameters": {
    "type": "project",
    "action": "batch_delete",
    "ids": [5, 6, 7]
  }
}
```

### Rate Management

#### List Customer Rates
```json
{
  "tool": "rate",
  "parameters": {
    "entity": "customer",
    "action": "list",
    "entity_id": 1
  }
}
```

### Comments (Kimai 2.57+)

#### List Project Comments
```json
{
  "tool": "comment",
  "parameters": {
    "entity": "project",
    "entity_id": 17,
    "action": "list"
  }
}
```

#### Add a Pinned Customer Comment
```json
{
  "tool": "comment",
  "parameters": {
    "entity": "customer",
    "entity_id": 5,
    "action": "create",
    "data": {
      "message": "Billing contact changed, see email from 2026-06-01",
      "pinned": true
    }
  }
}
```

### Current User Information

#### Get Current User

```json
{
  "tool": "user_current"
}
```

### Smart Features

#### Automatic Absence Splitting

The MCP automatically handles Kimai's limitations when creating absences:

**Year-Boundary Splitting**: Kimai doesn't allow absences spanning multiple years. The MCP automatically splits them.

```json
{
  "tool": "absence",
  "parameters": {
    "action": "create",
    "data": {
      "date": "2025-09-01",
      "end": "2026-03-31",
      "type": "parental",
      "comment": "Parental leave"
    }
  }
}
```

This automatically becomes two entries:

- `2025-09-01` to `2025-12-31`
- `2026-01-01` to `2026-03-31`

**30-Day Limit Splitting**: Kimai limits absences to 30 days maximum. Longer absences are automatically split into 30-day chunks.

```json
{
  "tool": "absence",
  "parameters": {
    "action": "create",
    "data": {
      "date": "2025-09-01",
      "end": "2025-11-29",
      "type": "parental",
      "comment": "Parental leave (90 days)"
    }
  }
}
```

This automatically becomes three 30-day entries with output:

```
Created 3 absence(s) for parental
Period: 2025-09-01 to 2025-11-29 (90 days)
IDs: 123, 124, 125
(Automatically split due to Kimai limitations)
```

## Troubleshooting

### Common Issues

#### Connection Problems
1. **Verify Kimai URL**: Ensure your Kimai URL is correct and accessible
2. **Check API Token**: Verify your API token is valid and not expired
3. **API Access**: Ensure your Kimai instance has API access enabled
4. **Network**: Check if there are any firewall or network restrictions

#### Permission Errors
- Creating timesheets for other users requires admin permissions
- Managing users and teams requires appropriate role permissions
- Some absence operations require manager permissions

#### Configuration Issues
1. **Claude Desktop Config**: Verify the JSON syntax is correct
2. **Path Issues**: Ensure Python can find the `kimai_mcp` module
3. **Arguments**: Check that command-line arguments are properly formatted

#### SSL Certificate Errors (Self-Hosted Instances)

If you're running a self-hosted Kimai instance with a custom CA certificate (e.g., self-signed certificates), you may encounter this error:

```
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain
```

**Solution 1: Use the `--ssl-verify` CLI option**

```bash
# Point to your CA certificate file
kimai-mcp --kimai-url=https://kimai.example.com --kimai-token=your-token --ssl-verify=/path/to/ca-bundle.crt

# Or disable verification (not recommended for production)
kimai-mcp --kimai-url=https://kimai.example.com --kimai-token=your-token --ssl-verify=false
```

**Solution 2: Use environment variables**

```bash
# Using httpx's built-in SSL environment variables
SSL_CERT_DIR=/etc/ssl/certs kimai-mcp --kimai-url=... --kimai-token=...

# Or using the KIMAI_SSL_VERIFY environment variable
KIMAI_SSL_VERIFY=/path/to/ca-bundle.crt kimai-mcp --kimai-url=... --kimai-token=...
```

**Claude Desktop configuration with custom certificates:**

```json
{
  "mcpServers": {
    "kimai": {
      "command": "kimai-mcp",
      "args": [
        "--kimai-url=https://kimai.example.com",
        "--kimai-token=your-token",
        "--ssl-verify=/path/to/ca-bundle.crt"
      ]
    }
  }
}
```

Or using the environment variable:

```json
{
  "mcpServers": {
    "kimai": {
      "command": "kimai-mcp",
      "args": ["--kimai-url=...", "--kimai-token=..."],
      "env": {
        "KIMAI_SSL_VERIFY": "/path/to/ca-bundle.crt"
      }
    }
  }
}
```

### Debug Mode
For debugging, you can run the server directly:

```bash
# Using command line arguments
kimai-mcp --kimai-url=https://your-kimai.com --kimai-token=your-token

# Using .env file (make sure you're in the directory with the .env file)
kimai-mcp

# Alternative: using Python module execution
python -m kimai_mcp.server --kimai-url=https://your-kimai.com --kimai-token=your-token
```

### Logging
The server includes comprehensive logging. Check the logs for detailed error information.

## Security Considerations

- **API Token Security**: Keep your API token secure and never commit it to version control
- **Network Security**: Use HTTPS for your Kimai instance
- **Permission Management**: Use appropriate Kimai roles and permissions
- **Regular Updates**: Keep the MCP server and dependencies updated

## Development

### Project Structure
```
kimai_mcp/
├── src/
│   ├── kimai_mcp/
│   │   ├── __init__.py
│   │   ├── server.py                  # Local MCP server (stdio)
│   │   ├── streamable_http_server.py  # Streamable HTTP server with OAuth (Claude.ai)
│   │   ├── sse_server.py              # SSE server (deprecated, non-functional)
│   │   ├── oauth.py                   # Embedded OAuth 2.1 authorization server
│   │   ├── user_config.py             # users.json / env multi-user configuration
│   │   ├── security.py                # Rate limiting, security headers, enumeration protection
│   │   ├── client.py                  # Kimai API client
│   │   ├── models.py                  # Data models
│   │   └── tools/                     # MCP tool implementations
│   │       ├── entity_manager.py
│   │       ├── timesheet_consolidated.py  # timesheet + timer tools
│   │       ├── rate_manager.py
│   │       ├── team_access_manager.py
│   │       ├── absence_manager.py
│   │       ├── calendar_meta.py           # calendar, meta, user_current tools
│   │       ├── comment_tool.py            # project/customer comments
│   │       ├── project_analysis.py
│   │       ├── config_info.py
│   │       ├── user_discovery.py          # shared user resolution helper
│   │       ├── batch_utils.py
│   │       ├── absence_analytics.py
│   │       └── timesheet_analytics.py
├── tests/
├── README.md
├── pyproject.toml
└── .gitignore
```

### Running Tests
```bash
pytest tests/ -v
```

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

### Licensing Information

- **Kimai MCP Server**: MIT License (this project)
- **Kimai Core**: AGPL-3.0 License (separate project)
- **Model Context Protocol**: Open standard by Anthropic

This MCP server is an independent integration tool that communicates with Kimai via its public API. It is not a derivative work of Kimai itself and can be freely used under the MIT license terms.

## 🤝 Contributing

We welcome contributions! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

### Development Setup

1. Clone the repository
2. Install development dependencies: `pip install -e ".[dev]"`
3. Run tests: `pytest tests/ -v`
4. Follow the existing code style and add tests for new features

## 📞 Support

- **Issues**: Please use the [GitHub issue tracker](https://github.com/glazperle/kimai_mcp/issues)
- **Documentation**: Check the examples in the `examples/` directory
- **Kimai Documentation**: Visit [kimai.org](https://www.kimai.org/) for Kimai-specific questions

## 🙏 Acknowledgments

- **Anthropic** for creating the Model Context Protocol
- **Kimai Team** for the excellent time-tracking software and API
- **MCP Community** for examples and best practices