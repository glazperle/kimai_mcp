"""Text a Kimai user writes, made safe for line-based tool output.

A listing is read by a model, line by line. A line break inside a value
written by a Kimai user would start a line of its own, and one shaped like a
record ('#6 2026-09-01 ...', 'User: admin (ID: 1)', 'Exported: No') could not
be told from a real one. Two rules keep that from happening:

* Every text field of a read model is joined to one line when it is parsed
  (``models.KimaiModel``), except the few that may span lines
  (``multiline_fields``: descriptions, comments, meta and preference values).
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
# characters (Cf: zero-width spaces and joiners, bidi overrides, the BOM), the
# line and paragraph separators (Zl, Zp), the other default-ignorable code
# points (variation selectors, the combining grapheme joiner, the Hangul
# fillers) and the blank Braille pattern U+2800. A zero-width space in front
# of '"Kickoff"' made it look like the quoted form of Kickoff, and U+202E
# turns the rest of a line around on screen. tests/test_output_and_resilience.py
# checks this class against unicodedata and the default-ignorable list.
_INVISIBLE = re.compile(
    "[\x00-\x1f\x7f-\x9f\u00ad\u034f\u0600-\u0605\u061c\u06dd\u070f\u0890\u0891\u08e2"
    "\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u2028-\u202e\u2060-\u206f"
    "\u2800\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufffb"
    "\U000110bd\U000110cd\U00013430-\U0001343f\U0001bca0-\U0001bca3\U0001d173-\U0001d17a"
    "\U000e0000-\U000e0fff]"
)
# Beyond ASCII, what a value or a label may hold and still be shown as is:
# letters, digits, numbers and currency signs whose compatibility form holds
# no separator (U+1F102 is '1,'); the modifier letters that are part of words
# (_WORD_MODIFIERS); combining marks right after a letter (Devanagari vowel
# signs, a decomposed umlaut), except those a separator can be drawn with
# (the comma below, the solidus overlays, the marks for symbols U+20D0 to
# U+20FF); and the typographic apostrophes and dashes common in names
# (O'Brien with U+2019). Other punctuation, symbols, spaces, modifier letters
# and marks are quoted: among them are look-alikes of the separators that
# NFKC does not fold (U+201A for ',', U+A78A and U+A60C for '=', U+266F for
# '#', U+2215 and U+3033 for '/'), and quoting is lossless.
_SHOWN_AS_IS = frozenset({"Lu", "Ll", "Lt", "Lo", "Nd", "No", "Sc"})
_LETTERS = frozenset({"Lu", "Ll", "Lt", "Lo", "Lm"})
_TYPOGRAPHIC = frozenset("\u2013\u2014\u2018\u2019")
# The Thai and Lao repetition marks, the Japanese iteration marks and the
# prolonged sound mark (also halfwidth).
_WORD_MODIFIERS = frozenset("\u0e46\u0ec6\u3005\u309d\u309e\u30fc\u30fd\u30fe\uff70")
_OVERLAYS = frozenset("\u0326\u0337\u0338")
# Letters shaped like '/', which a name may hold but not between spaces.
_SLASH_LIKE = ("\u30ce", "\u4e3f", "\uff89")


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
    (line breaks included), outer whitespace, or a first character that could
    be a double quote (so a stored '"Kickoff"' is not mistaken for the quoted
    form of 'Kickoff'). Beyond ASCII only a letter, digit, number or currency
    sign may come first: the look-alikes of '"' include punctuation (U+05F4,
    U+3003), modifier letters (U+02BA) and a combining mark, which sits on
    the space before it."""
    if _INVISIBLE.search(text) or text != text.strip():
        return True
    first = text[:1]
    if first.isascii():
        return first == '"'
    return unicodedata.category(first) not in _SHOWN_AS_IS


def _shown_as_is(text: str, reserved: str) -> bool:
    """Whether every character of ``text`` is printable ASCII outside
    ``reserved`` or one of those listed above ``_SHOWN_AS_IS``, none of them
    invisible (U+3164 HANGUL FILLER is a letter, and blank)."""
    after_letter = False
    for char in text:
        if char.isascii():
            if not " " <= char <= "~" or char in reserved:
                return False
            after_letter = char.isalpha()
            continue
        if _INVISIBLE.match(char):
            return False
        category = unicodedata.category(char)
        if category in ("Mn", "Mc"):
            if not after_letter or char in _OVERLAYS or "\u20d0" <= char <= "\u20ff":
                return False
            continue  # a second mark sits on the same letter
        if not (category in _SHOWN_AS_IS or char in _TYPOGRAPHIC or char in _WORD_MODIFIERS):
            return False
        if any(folded in reserved for folded in unicodedata.normalize("NFKC", char)):
            return False
        after_letter = category in _LETTERS
    return True


def quoted(text) -> str:
    """Free text (a description, a comment): as is, or as a JSON string."""
    text = str(text)
    return _json(text) if _ambiguous(text) else text


def value_text(value) -> str:
    """A meta value or tag inside a ``name=value, ...`` list: plain, else JSON-quoted.

    ';' separates the segments of a row ("tags: ...; meta: ..."), ',' and '='
    the values inside one. A value is plain only as one or more words of
    printable ASCII other than those, a quote or a backslash, or of the
    characters beyond ASCII listed above ``_SHOWN_AS_IS`` (letters, digits and
    the like), single spaces between them.
    So ``ticket=CA-1, approved=yes`` cannot be one value posing as two fields,
    with ASCII separators or with look-alikes of them, and the stored value
    can be read back.
    """
    text = str(value)
    plain = text and text == text.strip() and "  " not in text and _shown_as_is(text, ',;="\\')
    return text if plain else _json(text)


def label_text(name) -> str:
    """A name in a row of ``name (#id)`` labels: as is, else JSON-quoted.

    In ``Acme / Relaunch (#2) / Meetings (#1), Bob (#4) - description`` each
    ``(#id)`` ends a label, so a name holding a '#' (an alias such as
    'Bob (#4) - approved by Ana (#5)') or ' / ' could pose as other labels and
    is quoted, as is one holding a character beyond ASCII not listed above
    ``_SHOWN_AS_IS`` (a look-alike such as U+FF03 or U+266F), a letter shaped
    like '/' between spaces (``_SLASH_LIKE``), and an ambiguous one (see
    ``quoted``).
    """
    text = str(name)
    plain = (
        not _ambiguous(text)
        and " / " not in text
        and not any(f" {char} " in text for char in _SLASH_LIKE)
        and _shown_as_is(text, "#")
    )
    return text if plain else _json(text)
