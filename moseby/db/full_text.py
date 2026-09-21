"""Shared keyword matching for SQLite FTS5 columns."""

import re
from unicodedata import normalize

from sqlalchemy import ColumnElement, false

_WORDS = re.compile(r"[^\W_]+")


def match_keywords(column: ColumnElement[str], text: str) -> ColumnElement[bool]:
    """Require every whole-word keyword, in any order, using a bound FTS5 query.

    Punctuation separates words; quoting treats search operators as ordinary words.
    Input with no words matches nothing. Use an index configured with unicode61
    and remove_diacritics=2 for case-insensitive and Latin-accent-insensitive matching.
    """
    words = _WORDS.findall(normalize("NFC", text))
    if not words:
        return false()
    return column.match(" AND ".join(f'"{word}"' for word in words))
