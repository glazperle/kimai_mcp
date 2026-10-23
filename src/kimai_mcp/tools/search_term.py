"""What Kimai's ``term`` parameter takes literally (``src/Utils/SearchTermPart.php``)."""


def is_literal(text: str) -> bool:
    """Whether Kimai's search term matches ``text`` as plain substrings.

    Kimai splits the term on whitespace and ANDs the words, each a ``LIKE
    '%word%'``. A word containing ':' is a meta-field search, a leading '!'
    excludes, and the LIKE pattern is not escaped, so a backslash (MySQL's
    escape character) changes what matches. Text with any of these must not
    be sent as a term when it is meant as a plain name or value.
    """
    return ":" not in text and "\\" not in text and not any(word.startswith("!") for word in text.split())


def is_meta_name(name: str) -> bool:
    """Whether ``name:value`` addresses the meta field ``name``.

    One word without ':' (the word is split at its first colon). The name is
    compared with '=', so nothing else in it is special.
    """
    return bool(name) and name.split() == [name] and ":" not in name


def is_literal_meta_value(value: str) -> bool:
    """Whether ``name:value`` searches for ``value`` itself.

    One word; not excluded by a leading '!'; no backslash (the LIKE escape);
    none of the special values ``*`` (any value), ``~`` and ``""``. A colon is
    literal: Kimai 2.35+ splits the word at its first colon only (2.34 split
    at every colon, which made the whole word a plain term).
    """
    return (
        value.split() == [value]
        and not value.startswith("!")
        and "\\" not in value
        and value not in ("*", "~", '""')
    )
