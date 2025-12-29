# Contributing to Kimai MCP Server

Thank you for your interest in contributing to the Kimai MCP Server! This document provides guidelines and information for contributors.

## 🤝 How to Contribute

### Reporting Issues

1. **Search existing issues** first to avoid duplicates
2. **Use the issue template** if available
3. **Provide clear details** including:
   - Your environment (OS, Python version, Kimai version)
   - Steps to reproduce the problem
   - Expected vs actual behavior
   - Error messages or logs

### Feature Requests

1. **Check existing feature requests** to avoid duplicates
2. **Describe the use case** clearly
3. **Explain the benefit** to other users
4. **Consider implementation complexity**

### Code Contributions

#### Prerequisites

- Python 3.10 or higher
- Access to a Kimai instance for testing
- Familiarity with async/await Python programming
- Understanding of the Model Context Protocol (MCP)

#### Setup Development Environment

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/yourusername/kimai-mcp.git
   cd kimai-mcp
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install development dependencies:**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Set up test environment:**
   ```bash
   # Copy example environment file
   cp .env.example .env
   # Edit .env with your test Kimai instance details
   ```

#### Development Workflow

1. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following the coding standards below

3. **Run tests:**
   ```bash
   pytest tests/ -v
   ```

4. **Test with real Kimai instance:**
   ```bash
   python test_tools_registration.py
   python -m kimai_mcp
   ```

5. **Commit your changes:**
   ```bash
   git add .
   git commit -m "feat: add your feature description"
   ```

6. **Push and create a pull request:**
   ```bash
   git push origin feature/your-feature-name
   ```

## 📝 Coding Standards

### Code Style

- **Follow PEP 8** Python style guidelines
- **Use type hints** for all function parameters and return values
- **Write docstrings** for all public functions and classes
- **Keep functions focused** on a single responsibility
- **Use meaningful variable names**

### MCP Tool Development

When adding new MCP tools:

1. **Tool Definition Structure:**
   ```python
   def your_tool() -> Tool:
       """Define the your tool."""
       return Tool(
           name="category_action",
           description="Clear, concise description of what the tool does",
           inputSchema={
               "type": "object",
               "required": ["required_param"],
               "properties": {
                   "required_param": {
                       "type": "string", 
                       "description": "What this parameter is for"
                   },
                   "optional_param": {
                       "type": "integer", 
                       "description": "Optional parameter description"
                   }
               }
           }
       )
   ```

2. **Handler Function Structure:**
   ```python
   async def handle_your_action(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
       """Handle your action."""
       # Validate and extract arguments
       required_param = arguments['required_param']
       optional_param = arguments.get('optional_param')
       
       # Call Kimai API
       result = await client.your_api_method(required_param, optional_param)
       
       # Format response with helpful information
       formatted_result = f"""Action completed successfully!
       
   Details: {result.details}
   Status: {result.status}"""
       
       return [TextContent(type="text", text=formatted_result)]
   ```

3. **Register tools** in `server.py`:
   - Add tool to `_list_tools()` method
   - Add handler to `_call_tool()` method

### Testing Guidelines

1. **Write tests for new features:**
   ```python
   @pytest.mark.asyncio
   async def test_your_feature(mock_client):
       """Test your feature."""
       # Setup mock responses
       mock_client.your_method.return_value = expected_result
       
       # Call your handler
       result = await handle_your_action(mock_client, test_arguments)
       
       # Assert expected behavior
       assert len(result) == 1
       assert "expected text" in result[0].text
       mock_client.your_method.assert_called_once_with(expected_args)
   ```

2. **Test error handling:**
   ```python
   @pytest.mark.asyncio
   async def test_your_feature_error_handling(mock_client):
       """Test error handling in your feature."""
       mock_client.your_method.side_effect = KimaiAPIError("Test error", 404)
       
       with pytest.raises(KimaiAPIError):
           await handle_your_action(mock_client, test_arguments)
   ```

3. **Integration tests** should use mock clients to avoid dependencies on real Kimai instances

## 🏗️ Architecture Overview

### Project Structure

```
kimai_mcp/
├── src/kimai_mcp/
│   ├── __init__.py
│   ├── __main__.py              # Entry point for python -m kimai_mcp
│   ├── server.py                # Main MCP server implementation
│   ├── client.py                # Kimai API client wrapper
│   ├── models.py                # Pydantic data models
│   └── tools/                   # MCP tool implementations
│       ├── __init__.py
│       ├── batch_utils.py       # Batch operation utilities (asyncio.gather)
│       ├── entity_manager.py    # Universal CRUD for all entity types
│       ├── timesheet_consolidated.py  # Timesheet management
│       ├── rate_manager.py      # Rate management across entities
│       ├── team_access_manager.py     # Team member/permission management
│       ├── absence_manager.py   # Absence workflow management
│       ├── calendar_meta.py     # Calendar and meta field tools
│       ├── project_analysis.py  # Project analytics
│       └── config_info.py       # Server configuration tools
├── tests/                       # Test suite
├── examples/                    # Usage examples
└── pyproject.toml              # Project configuration
```

### Key Components

1. **KimaiMCPServer**: Main server class that implements MCP protocol
2. **KimaiClient**: Async HTTP client for Kimai API
3. **Tool Modules**: Individual modules for each category of functionality
4. **Models**: Pydantic models for data validation and serialization

## 🚀 Release Process

### Version Numbering

We follow [Semantic Versioning](https://semver.org/):
- **MAJOR**: Breaking changes to MCP tool interfaces
- **MINOR**: New features, new tools, backwards-compatible changes
- **PATCH**: Bug fixes, documentation updates

### Changelog

Update `README.md` changelog section with:
- New features added
- Bug fixes
- Breaking changes
- Deprecation notices

## 📋 Pull Request Guidelines

### Before Submitting

- [ ] Code follows project style guidelines
- [ ] Tests pass locally
- [ ] New features include tests
- [ ] Documentation updated if needed
- [ ] Changelog updated for significant changes

### Pull Request Template

```markdown
## Description
Brief description of changes made.

## Type of Change
- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update

## Testing
- [ ] Tests pass locally
- [ ] Added tests for new functionality
- [ ] Tested with real Kimai instance

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] Changelog updated
```

## 🆘 Getting Help

- **Documentation**: Check the README and examples first
- **Issues**: Search existing issues or create a new one
- **Discussions**: Use GitHub Discussions for questions and ideas
- **Kimai Documentation**: Visit [kimai.org](https://www.kimai.org/) for Kimai-specific questions

## 📄 License

By contributing to this project, you agree that your contributions will be licensed under the MIT License.

Thank you for contributing! 🎉