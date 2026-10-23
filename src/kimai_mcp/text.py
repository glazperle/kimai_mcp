"""Text a Kimai user writes, made safe for line-based tool output.

A listing is read by a model, line by line. A line break inside a value
written by a Kimai user would start a line of its own, and one shaped like a
record ('#6 2026-09-01 ...', 'User: admin (ID: 1)', 'Exported: No') could not
be told from a real one. Two rules keep that from happening:

* Every text field of a read model is joined to one line when it is parsed
  (``models.KimaiModel``), except the few that may span lines
  (``multiline_fields``: descriptions, comments, meta values).
* Text shown where it could be mistaken for structure goes through a renderer
  here: ``quoted`` for free text, ``value_text`` for a value in a
  ``name=value, ...`` list, ``label_text`` for a name in a ``name (#id)``
  label. Each JSON-quotes when the text would be ambiguous, which is lossless,
  so a value read back with ``get`` can be written again.

A line break is anything ``str.splitlines`` splits on, the Unicode separators
U+2028, U+2029 and U+0085 included.
"""

import json
import re
import unicodedata

_LINE_BREAK = re.compile("[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]")
# Characters that are not shown as themselves: controls (Cc), format
# characters (Cf: zero-width spaces and joiners, bidi overrides, the BOM) and
# the line and paragraph separators (Zl, Zp). A zero-width space in front of
# '"Kickoff"' made it look like the quoted form of Kickoff, and U+202E turns
# the rest of a line around on screen. tests/test_output_and_resilience.py
# checks this class against unicodedata.
_INVISIBLE = re.compile(
    "[\x00-\x1f\x7f-\x9f\u00ad\u0600-\u0605\u061c\u06dd\u070f\u0890\u0891\u08e2\u180e"
    "\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb"
    "\U000110bd\U000110cd\U00013430-\U0001343f\U0001bca0-\U0001bca3\U0001d173-\U0001d17a"
    "\U000e0001\U000e0020-\U000e007f]"
)
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


def _escape(match: re.Match) -> str:
    return json.dumps(match.group())[1:-1]  # \\uXXXX, a surrogate pair for U+10000 and above


def _json(text: str) -> str:
    """``text`` as a JSON string with every invisible character escaped.

    ``json.dumps(..., ensure_ascii=False)`` escapes the ASCII controls but
    leaves DEL, the C1 controls, the format characters and U+2028/U+2029 as
    they are.
    """
    return _INVISIBLE.sub(_escape, json.dumps(text, ensure_ascii=False))


def _ambiguous(text: str) -> bool:
    """Whether ``text`` shown as is could be misread: an invisible character
    (line breaks included), outer whitespace, or a leading double quote (so a
    stored '"Kickoff"' is not mistaken for the quoted form of 'Kickoff';
    look-alikes such as U+FF02 count)."""
    return (
        bool(_INVISIBLE.search(text))
        or text != text.strip()
        or unicodedata.normalize("NFKC", text[:1]) == '"'
    )


def quoted(text) -> str:
    """Free text (a description, a comment): as is, or as a JSON string."""
    text = str(text)
    return _json(text) if _ambiguous(text) else text


def value_text(value) -> str:
    """A meta value or tag inside a ``name=value, ...`` list: plain, else JSON-quoted.

    Quoted as soon as it holds a separator (``,`` ``;`` ``=``, or a look-alike
    that NFKC folds into one, such as U+FF0C), a quote, a backslash, an
    invisible character or outer whitespace, so ``ticket=CA-1, approved=yes``
    cannot be one value posing as two fields, and the stored value can be
    read back.
    """
    text = str(value)
    plain = (
        _PLAIN_VALUE.fullmatch(text)
        and _PLAIN_VALUE.fullmatch(unicodedata.normalize("NFKC", text))
        and not _INVISIBLE.search(text)
    )
    return text if plain else _json(text)


def label_text(name) -> str:
    """A name in a row of ``name (#id)`` labels: as is, else JSON-quoted.

    In ``Acme / Relaunch (#2) / Meetings (#1), Bob (#4) - description`` each
    ``(#id)`` ends a label, so a name holding a '#' (an alias such as
    'Bob (#4) - approved by Ana (#5)') or ' / ' could pose as other labels and
    is quoted, as is an ambiguous one (see ``quoted``).
    """
    text = str(name)
    return _json(text) if "#" in text or " / " in text or _ambiguous(text) else text
