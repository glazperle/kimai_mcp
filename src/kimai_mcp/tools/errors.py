"""Tool-layer error type shared by the consolidated tool handlers.

Handlers raise :class:`ToolError` when they cannot fulfill a request (invalid
or missing input, an unknown action/type, an unsupported operation, or a
permission/discovery failure). Both servers' ``_call_tool`` catch it and return
a ``CallToolResult(isError=True)`` (via ``server.error_result``), so programmatic
MCP clients can detect the failure instead of mistaking the error text for a
successful payload.

This module intentionally has no imports so it can be imported from any tool
module without creating an import cycle.
"""


class ToolError(Exception):
    """A tool could not fulfill the request.

    The message is surfaced verbatim to the MCP client as the error result's
    text, so it should be human-readable and actionable.
    """
