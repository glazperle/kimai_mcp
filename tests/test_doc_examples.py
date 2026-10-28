"""Every documented tool call must pass the tool's own schema.

With every input object closed, a documented key that no schema declares
(``filters.orderBy`` instead of ``order_by``) is an input validation error, not
a parameter Kimai ignores. The examples are what users and models copy, so
each JSON block of the form ``{"tool": ..., "parameters": ...}`` in the README
and in examples/ is validated here.
"""

import json
import re
from pathlib import Path

import pytest

from kimai_mcp.tools import registry
from kimai_mcp.tools.registry import all_tools, validate_arguments

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", *sorted((ROOT / "examples").glob("*.md"))]
JSON_BLOCK = re.compile(r"```json\s*\n(.*?)```", re.DOTALL)
# examples/usage_examples.md writes calls as "Tool: name" + "Parameters: {...}",
# sometimes several per block, sometimes followed by the expected output.
ANY_BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
TOOL_CALL = re.compile(r"Tool:\s*(\w+)\s*\nParameters:\s*")


def _calls():
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        for match in JSON_BLOCK.finditer(text):
            try:
                block = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue  # configuration snippets with comments, not tool calls
            if isinstance(block, dict) and "tool" in block and "parameters" in block:
                line = text.count("\n", 0, match.start()) + 1
                yield pytest.param(block["tool"], block["parameters"], id=f"{doc.name}:{line}")
        for block in ANY_BLOCK.finditer(text):
            for call in TOOL_CALL.finditer(block.group(1)):
                line = text.count("\n", 0, block.start(1) + call.start()) + 1
                # Parsed in the test, so a block that is not valid JSON fails there.
                yield pytest.param(call.group(1), block.group(1)[call.end():], id=f"{doc.name}:{line}")


CALLS = list(_calls())


def test_examples_were_found():
    assert len(CALLS) > 20, "the doc parser found suspiciously few examples"


@pytest.mark.parametrize(("tool_name", "arguments"), CALLS)
def test_documented_call_is_valid(tool_name, arguments):
    """Against what the server validates, and against what a client is shown
    (the entity schema is flattened for clients, issue #38): a client that
    checks its arguments locally must not refuse a valid call."""
    tools = {t.name: t for t in all_tools()}
    assert tool_name in tools, f"documented tool '{tool_name}' does not exist"
    if isinstance(arguments, str):
        arguments, _end = json.JSONDecoder().raw_decode(arguments)
    registry._check(registry._tool_validator(tool_name), arguments)
    validate_arguments(tools[tool_name], arguments)
