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

**For enterprise/team environments:** Deploy the server once and let all users connect remotely with their own credentials!

```bash
# Quick start with Docker
docker run -d \
  -p 8000:8000 \
  -e DEFAULT_KIMAI_URL=https://your-kimai.com \
  ghcr.io/glazperle/kimai-mcp:latest

# Or use Docker Compose (see DEPLOYMENT.md for full guide)
docker-compose up -d
```

**🔐 Per-Client Authentication:**
- Each user uses their **own** Kimai API token
- Individual permissions and access control
- Auditable actions per user
- No shared credentials
- Enhanced security and compliance

**Benefits:**
- ✅ Install once, use everywhere
- ✅ Central management and updates
- ✅ Each user keeps their individual permissions
- ✅ No local installation on client machines
- ✅ Full audit trail per user

**Client Setup:**
```json
{
  "mcpServers": {
    "kimai": {
      "url": "http://your-server:8000/sse",
      "headers": {
        "Authorization": "Bearer MCP-SERVER-TOKEN",
        "X-Kimai-Token": "YOUR-PERSONAL-KIMAI-TOKEN"
      }
    }
  }
}
```

📖 **[See full deployment guide →](DEPLOYMENT.md)**

## Command Line Options

| Option | Description |
| ------ | ----------- |
| `--kimai-url URL` | Kimai server URL (e.g., `https://kimai.example.com`) |
| `--kimai-token TOKEN` | API authentication token from your Kimai user profile |
| `--kimai-user USER_ID` | Default user ID for operations (optional) |
| `--ssl-verify VALUE` | SSL verification: `true` (default), `false`, or path to CA certificate |
| `--setup` | Interactive setup wizard for Claude Desktop configuration |
| `--help` | Show help message and exit |
| `--version` | Show version number and exit |

## 🛠️ Available Tools

### Core Management Tools
1. **Entity Tool** - Universal CRUD operations for projects, activities, customers, users, teams, tags, invoices, holidays
2. **Timesheet Tool** - Complete timesheet management (list, create, update, delete, export, batch operations)
3. **Timer Tool** - Active timer operations (start, stop, restart, view active/recent)
4. **Rate Tool** - Rate management across all entity types
5. **Team Access Tool** - Team member and permission management
6. **Absence Tool** - Complete absence workflow (create, approve, reject, list, attendance, batch operations, auto-split)
7. **Calendar Tool** - Unified calendar data access
8. **Meta Tool** - Custom field management across entities
9. **User Current Tool** - Current user information
10. **Project Analysis Tool** - Advanced project analytics
11. **Config Tool** - Server configuration (timesheet settings, color codes, plugins, version info)

### Complete Kimai Integration
- **Timesheet Management** - Create, update, delete, start/stop timers, view active timers
- **Project & Activity Management** - Browse and view projects and activities
- **Customer Management** - Browse and view customer information
- **User Management** - List, view, create, and update user accounts
- **Team Management** - Create teams, manage members, control access permissions
- **Absence Management** - Create, approve, reject, and track absences
- **Tag Management** - Create and manage tags for better organization
- **Invoice Queries** - View invoice information and status

### Advanced Features
- **Real-time Timer Control** - Start, stop, and monitor active time tracking
- **Comprehensive Filtering** - Advanced filters for all data types
- **Permission Management** - Respect Kimai's role-based permissions
- **Error Handling** - Proper error handling with meaningful messages
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
- Optionally add `--kimai-user=USER_ID` for a default user ID
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
KIMAI_DEFAULT_USER=1
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
export KIMAI_DEFAULT_USER="1"  # Optional
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
│   │   ├── server.py         # MCP server implementation
│   │   ├── client.py         # Kimai API client
│   │   ├── models.py         # Data models
│   │   └── tools/            # MCP tool implementations
│   │       ├── entity_manager.py
│   │       ├── timesheet_consolidated.py
│   │       ├── rate_manager.py
│   │       ├── team_access_manager.py
│   │       ├── absence_manager.py
│   │       ├── calendar_meta.py
│   │       ├── project_analysis.py
│   │       └── config_info.py
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