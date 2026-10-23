"""User-written text in tool output: on one line, or quoted.

A listing is read by a model, line by line. A line break inside a value
written by a Kimai user (a description, a meta field, a comment) would start a
line of its own, and one shaped like a record ('#6 2026-09-01 ...', 'ID: 99 -
holiday') could not be told from a real one. Names are made single-line when
they are parsed (``models.OneLine``); the free text that may legitimately span
lines goes through these helpers when it is rendered.
"""

import json
import re

# One or more words without separators or quotes, single spaces between them.
_PLAIN_VALUE = re.compile(r'[^\s,="\\]+(?: [^\s,="\\]+)*')


def one_line(text) -> str:
    """``text`` with its lines joined by ' | ' (blank lines dropped).

    The first line keeps its leading whitespace, so an indented detail line
    of a listing stays indented.
    """
    first, *rest = str(text).splitlines() or [""]
    return " | ".join([first, *(part.strip() for part in rest if part.strip())])


def quoted(text) -> str:
    """``text`` as is, or as a JSON string when it spans lines or has outer whitespace.

    Lossless: the escapes give the stored value back, which matters where a
    caller reads a value to write it again (a description, a comment).
    """
    text = str(text)
    if len(text.splitlines()) > 1 or text != text.strip() or any(ord(c) < 32 for c in text):
        return json.dumps(text, ensure_ascii=False)
    return text


def value_text(value) -> str:
    """A meta value or tag inside a ``name=value, ...`` list: plain, else JSON-quoted.

    Quoted as soon as it holds a separator (``,`` ``=``), a quote, a backslash,
    a line break or outer whitespace, so ``ticket=CA-1, approved=yes`` cannot be
    one value posing as two fields, and the stored value can be read back.
    """
    text = str(value)
    return text if _PLAIN_VALUE.fullmatch(text) else json.dumps(text, ensure_ascii=False)
