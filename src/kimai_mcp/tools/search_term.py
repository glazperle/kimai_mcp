"""What Kimai's ``term`` parameter takes literally (``src/Repository/Search/SearchTerm.php``)."""


def is_literal(text: str) -> bool:
    """Whether Kimai's search term matches ``text`` as plain substrings.

    Kimai splits the term on whitespace and ANDs the words, each a ``LIKE
    '%word%'``. A word containing ':' is a meta-field search, a leading '!'
    excludes, and the LIKE pattern is not escaped, so a backslash (MySQL's
    escape character) changes what matches. Text with any of these must not
    be sent as a term when it is meant as a plain name or value.
    """
    return ":" not in text and "\\" not in text and not any(word.startswith("!") for word in text.split())


def is_literal_meta_value(value: str) -> bool:
    """Whether ``name:value`` searches for ``value`` itself.

    One word only (the term is split on whitespace), literal as above, and
    none of the special values ``*`` (any value), ``~`` and ``""``.
    """
    return value.split() == [value] and is_literal(value) and value not in ("*", "~", '""')
