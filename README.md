# Kimai MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

A comprehensive Model Context Protocol (MCP) server for integrating with the Kimai time-tracking API. This server allows AI assistants like Claude to interact with Kimai instances to manage time tracking, projects, activities, customers, users, teams, absences, and more.

## 🚀 Quick Start

```bash
# Install the package
pip install -e .

# Run with your Kimai credentials
python -m kimai_mcp --kimai-url=https://your-kimai.com --kimai-token=your-token
```

## Features

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
- **No .env Dependencies** - Configuration through MCP client (Claude Desktop)

## Installation

### Prerequisites
- Python 3.8+
- A Kimai instance with API access enabled
- API token from your Kimai user profile

### Install the Package

```bash
# Clone the repository
git clone https://github.com/yourusername/kimai-mcp.git
cd kimai-mcp

# Install the package
pip install -e .
```

### Alternative: Install Dependencies Only
```bash
pip install mcp httpx pydantic
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

**Important Notes:**
- Replace `https://your-kimai-instance.com` with your actual Kimai URL
- Replace `your-api-token-here` with your API token from Kimai
- Optionally add `--kimai-user=USER_ID` for a default user ID

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
```

Then use this Claude Desktop configuration:
```json
{
  "mcpServers": {
    "kimai": {
      "command": "python",
      "args": ["-m", "kimai_mcp"],
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
      "command": "python",
      "args": ["-m", "kimai_mcp"],
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
      "command": "python",
      "args": ["-m", "kimai_mcp"]
    }
  }
}
```

#### Method 3: Using a Python Script
Create a script `run_kimai_mcp.py`:
```python
#!/usr/bin/env python3
import asyncio
from kimai_mcp.server import KimaiMCPServer

async def main():
    server = KimaiMCPServer(
        base_url="https://your-kimai-instance.com",
        api_token="your-api-token-here",
        default_user_id="1"  # Optional
    )
    try:
        await server.run()
    finally:
        await server.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
```

Then use this configuration:
```json
{
  "mcpServers": {
    "kimai": {
      "command": "python",
      "args": ["run_kimai_mcp.py"]
    }
  }
}
```

## Available Tools

### Timesheet Management

#### `timesheet_list` - List Timesheets
List timesheets with comprehensive filtering options.

**Parameters:**
- `user` (string): User ID or 'all' for all users
- `project` (integer): Project ID filter
- `activity` (integer): Activity ID filter
- `customer` (integer): Customer ID filter
- `begin` (datetime): Start date filter (ISO format)
- `end` (datetime): End date filter (ISO format)
- `exported` (0|1): Export status filter
- `active` (0|1): Active status filter
- `billable` (0|1): Billable status filter
- `page` (integer): Page number for pagination
- `size` (integer): Page size (default: 50)
- `term` (string): Search term

#### `timesheet_create` - Create Timesheet
Create a new timesheet entry.

**Parameters:**
- `project` (integer, required): Project ID
- `activity` (integer, required): Activity ID
- `begin` (datetime): Start time (ISO format, default: now)
- `end` (datetime): End time (if not set, timer runs)
- `description` (string): Description/notes
- `tags` (string): Comma-separated tags
- `billable` (boolean): Whether entry is billable
- `fixedRate` (number): Fixed rate override
- `hourlyRate` (number): Hourly rate override

#### `timesheet_start` - Start Timer
Start a new timer (creates a running timesheet).

**Parameters:**
- `project` (integer, required): Project ID
- `activity` (integer, required): Activity ID
- `description` (string): Description/notes
- `tags` (string): Comma-separated tags

#### `timesheet_stop` - Stop Timer
Stop a running timer.

**Parameters:**
- `id` (integer, required): Timesheet ID of the running timer

#### `timesheet_active` - Get Active Timers
Get all active/running timers for the current user.

#### `timesheet_recent` - Recent Activities
Get recent timesheet activities for quick access.

**Parameters:**
- `size` (integer): Number of entries to return (default: 10)
- `begin` (datetime): Only entries after this date

### Project & Activity Management

#### `project_list` - List Projects
**Parameters:**
- `customer` (integer): Customer ID filter
- `visible` (1|2|3): Visibility filter (1=visible, 2=hidden, 3=both)
- `term` (string): Search term

#### `project_get` - Get Project Details
**Parameters:**
- `id` (integer, required): Project ID

#### `activity_list` - List Activities
**Parameters:**
- `project` (integer): Project ID filter
- `visible` (1|2|3): Visibility filter
- `globals` ("0"|"1"): Global activities filter
- `term` (string): Search term

#### `activity_get` - Get Activity Details
**Parameters:**
- `id` (integer, required): Activity ID

### Customer Management

#### `customer_list` - List Customers
**Parameters:**
- `visible` (1|2|3): Visibility filter
- `term` (string): Search term

#### `customer_get` - Get Customer Details
**Parameters:**
- `id` (integer, required): Customer ID

### User Management

#### `user_list` - List Users
**Parameters:**
- `visible` (1|2|3): Visibility filter
- `term` (string): Search term
- `order_by` (string): Sort field (id, username, alias, email)
- `order` (ASC|DESC): Sort order

#### `user_get` - Get User Details
**Parameters:**
- `id` (integer, required): User ID

#### `user_current` - Get Current User
Get information about the currently authenticated user.

#### `user_create` - Create User
**Parameters:**
- `username` (string, required): Unique username
- `email` (string, required): User email address
- `language` (string, required): Language code (e.g., 'en', 'de')
- `locale` (string, required): Locale code (e.g., 'en_US', 'de_DE')
- `timezone` (string, required): Timezone (e.g., 'Europe/Berlin')
- `plainPassword` (string, required): Plain text password
- Plus optional fields: alias, title, roles, supervisor, etc.

#### `user_update` - Update User
**Parameters:**
- `id` (integer, required): User ID to update
- `email` (string, required): User email address
- `language` (string, required): Language code
- `locale` (string, required): Locale code
- `timezone` (string, required): Timezone
- Plus optional fields: alias, title, roles, supervisor, etc.

### Team Management

#### `team_list` - List Teams
List all teams.

#### `team_get` - Get Team Details
**Parameters:**
- `id` (integer, required): Team ID

#### `team_create` - Create Team
**Parameters:**
- `name` (string, required): Team name
- `color` (string): Team color (hex format)
- `members` (array): Initial team members with user IDs and teamlead status

#### `team_update` - Update Team
**Parameters:**
- `id` (integer, required): Team ID to update
- `name` (string, required): Team name
- `color` (string): Team color
- `members` (array): Team members (replaces existing)

#### `team_delete` - Delete Team
**Parameters:**
- `id` (integer, required): Team ID to delete

#### `team_add_member` - Add Team Member
**Parameters:**
- `team_id` (integer, required): Team ID
- `user_id` (integer, required): User ID to add

#### `team_remove_member` - Remove Team Member
**Parameters:**
- `team_id` (integer, required): Team ID
- `user_id` (integer, required): User ID to remove

### Absence Management

#### `absence_list` - List Absences
**Parameters:**
- `user` (string): User ID to filter absences
- `begin` (date): Only absences after this date (YYYY-MM-DD)
- `end` (date): Only absences before this date (YYYY-MM-DD)
- `status` (approved|open|all): Status filter

#### `absence_types` - Get Absence Types
**Parameters:**
- `language` (string): Language code for translations

#### `absence_create` - Create Absence
**Parameters:**
- `comment` (string, required): Comment/reason for the absence
- `date` (date, required): Start date of absence (YYYY-MM-DD)
- `type` (string, required): Type of absence (holiday, time_off, sickness, etc.)
- `user` (integer): User ID (requires permission, defaults to current user)
- `end` (date): End date for multi-day absences
- `halfDay` (boolean): Whether this is a half-day absence
- `duration` (string): Duration in Kimai format

#### `absence_delete` - Delete Absence
**Parameters:**
- `id` (integer, required): Absence ID to delete

#### `absence_approve` - Approve Absence
**Parameters:**
- `id` (integer, required): Absence ID to approve

#### `absence_reject` - Reject Absence
**Parameters:**
- `id` (integer, required): Absence ID to reject

### Tag Management

#### `tag_list` - List Tags
**Parameters:**
- `name` (string): Filter tags by name (partial match)

#### `tag_create` - Create Tag
**Parameters:**
- `name` (string, required): Tag name
- `color` (string): Tag color (hex format)
- `visible` (boolean): Whether tag is visible

#### `tag_delete` - Delete Tag
**Parameters:**
- `id` (integer, required): Tag ID to delete

### Invoice Queries

#### `invoice_list` - List Invoices
**Parameters:**
- `begin` (date): Start date filter (YYYY-MM-DD)
- `end` (date): End date filter (YYYY-MM-DD)
- `customers` (array): Customer IDs to filter by
- `status` (array): Invoice status filter (new, pending, paid, canceled)
- `page` (integer): Page number for pagination
- `size` (integer): Number of items per page

#### `invoice_get` - Get Invoice Details
**Parameters:**
- `id` (integer, required): Invoice ID to retrieve

## Usage Examples

### Starting a Timer
```
Use the timesheet_start tool with:
{
  "project": 1,
  "activity": 5,
  "description": "Working on API integration"
}
```

### Listing Today's Timesheets
```
Use the timesheet_list tool with:
{
  "begin": "2024-01-15T00:00:00",
  "end": "2024-01-15T23:59:59"
}
```

### Creating an Absence
```
Use the absence_create tool with:
{
  "comment": "Vacation in the mountains",
  "date": "2024-02-15",
  "end": "2024-02-20",
  "type": "holiday"
}
```

### Managing Teams
```
Use the team_create tool with:
{
  "name": "Development Team",
  "color": "#3498db",
  "members": [
    {"user": 1, "teamlead": true},
    {"user": 2, "teamlead": false}
  ]
}
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

### Debug Mode
For debugging, you can run the server directly:

```bash
# Using command line arguments
python -m kimai_mcp.server --kimai-url=https://your-kimai.com --kimai-token=your-token

# Using .env file (make sure you're in the directory with the .env file)
python -m kimai_mcp

# Test the package module execution
python -m kimai_mcp.server
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
│   │       ├── timesheet.py
│   │       ├── project.py
│   │       ├── activity.py
│   │       ├── customer.py
│   │       ├── user.py
│   │       ├── team.py
│   │       ├── absence.py
│   │       ├── tag.py
│   │       └── invoice.py
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

- **Issues**: Please use the [GitHub issue tracker](https://github.com/yourusername/kimai-mcp/issues)
- **Documentation**: Check the examples in the `examples/` directory
- **Kimai Documentation**: Visit [kimai.org](https://www.kimai.org/) for Kimai-specific questions

## 🙏 Acknowledgments

- **Anthropic** for creating the Model Context Protocol
- **Kimai Team** for the excellent time-tracking software and API
- **MCP Community** for examples and best practices

## 📈 Changelog

### v1.0.0 - Initial Release
- ✅ Complete Kimai API integration (73 MCP tools)
- ✅ Full CRUD operations for projects, activities, customers
- ✅ Advanced timesheet management with timer controls
- ✅ Team management with granular access controls
- ✅ Absence management and approval workflows
- ✅ Calendar integration and public holiday management
- ✅ Rate management for customers, projects, and activities
- ✅ Custom field (meta) support across all entities
- ✅ Multiple configuration methods (.env, CLI args, env vars)
- ✅ Claude Desktop integration with comprehensive documentation
- ✅ Comprehensive test suite and error handling
- ✅ MIT License for maximum compatibility