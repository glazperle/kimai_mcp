"""Text a Kimai user writes, made safe for line-based tool output.

A listing is read by a model, line by line. A line break inside a value
written by a Kimai user would start a line of its own, and one shaped like a
record ('#6 2026-09-01 ...', 'User: admin (ID: 1)', 'Exported: No') could not
be told from a real one. Two rules keep that from happening:

* Every text field of a read model is joined to one line when it is parsed
  (``models.KimaiModel``), except the few that may span lines
  (``multiline_fields``: descriptions, comments, meta values).
* Those are rendered through ``quoted`` or ``value_text`` here: JSON-quoted
  when they would be ambiguous, which is lossless, so a value read back with
  ``get`` can be written again.

A line break is anything ``str.splitlines`` splits on, the Unicode separators
U+2028, U+2029 and U+0085 included.
"""

import json
import re

_LINE_BREAK = re.compile("[\n\r\v\f\x1c\x1d\x1e\x85  ]")
# One or more words without separators or quotes, single spaces between them.
# ';' separates the segments of a row ("tags: ...; meta: ..."), ',' and '='
# the values inside one.
_PLAIN_VALUE = re.compile(r'[^\s,;="\\]+(?: [^\s,;="\\]+)*')


def one_line(text) -> str:
    """``text`` unchanged, or its lines stripped and joined by ' | ' (blank lines dropped)."""
    text = str(text)
    if not _LINE_BREAK.search(text):
        return text
    return " | ".join(part.strip() for part in text.splitlines() if part.strip())


def _json(text: str) -> str:
    """``text`` as a JSON string with no raw line break left in it.

    ``json.dumps(..., ensure_ascii=False)`` escapes the ASCII controls but
    leaves U+2028, U+2029 and U+0085 as they are.
    """
    return (
        json.dumps(text, ensure_ascii=False)
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
        .replace("\x85", "\\u0085")
    )


def quoted(text) -> str:
    """Free text (a description, a comment): as is, or as a JSON string.

    Quoted when it spans lines, has outer whitespace or a control character,
    or starts with a double quote (so a stored '"Kickoff"' is not mistaken for
    the quoted form of 'Kickoff').
    """
    text = str(text)
    if (
        _LINE_BREAK.search(text)
        or text != text.strip()
        or text.startswith('"')
        or any(ord(c) < 32 for c in text)
    ):
        return _json(text)
    return text


def value_text(value) -> str:
    """A meta value or tag inside a ``name=value, ...`` list: plain, else JSON-quoted.

    Quoted as soon as it holds a separator (``,`` ``;`` ``=``), a quote, a
    backslash, a line break or outer whitespace, so ``ticket=CA-1, approved=yes``
    cannot be one value posing as two fields, and the stored value can be read
    back.
    """
    text = str(value)
    return text if _PLAIN_VALUE.fullmatch(text) else _json(text)
