"""Source lint test: no literal backslash-n sequences in tool output strings.

A past bug class: handler output strings contained the two characters
backslash + 'n' (written as a double backslash followed by 'n' in the
source) instead of a real newline escape, so the MCP client displayed a
literal ``\\n`` to the user.

This test scans the source text of every module in ``kimai_mcp/tools`` for
the three-character sequence backslash, backslash, 'n'. Checking the source
text is more robust than runtime checks, because it covers every string
literal regardless of which code path produces it.
"""

from pathlib import Path

import pytest

TOOLS_DIR = (
    Path(__file__).resolve().parent.parent / "src" / "kimai_mcp" / "tools"
)

# The three characters: backslash, backslash, 'n' - as they appear in the
# source text of a buggy string literal like "line1\\nline2".
LITERAL_BACKSLASH_N = "\\\\n"

TOOL_SOURCES = sorted(TOOLS_DIR.glob("*.py"))


def test_tools_directory_found():
    """Sanity check so the parametrized test below cannot pass vacuously."""
    assert TOOLS_DIR.is_dir(), f"Tools directory not found: {TOOLS_DIR}"
    assert TOOL_SOURCES, f"No Python sources found in {TOOLS_DIR}"


@pytest.mark.parametrize(
    "source_file", TOOL_SOURCES, ids=lambda p: p.name
)
def test_no_literal_backslash_n_in_tool_sources(source_file):
    """No tool source may contain an escaped backslash followed by 'n'.

    Such a sequence in a string literal produces the literal characters
    ``\\n`` in handler output instead of a real line break. If a future
    legitimate use arises (e.g. a Windows path like ``C:\\new``), exclude
    that line explicitly here.
    """
    text = source_file.read_text(encoding="utf-8")

    offending = [
        (lineno, line.strip())
        for lineno, line in enumerate(text.splitlines(), start=1)
        if LITERAL_BACKSLASH_N in line
    ]

    assert not offending, (
        f"{source_file.name} contains literal backslash-n sequences "
        f"(these render as '\\n' text instead of a newline): {offending}"
    )
