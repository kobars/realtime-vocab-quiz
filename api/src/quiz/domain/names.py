# AI-ASSISTED: the display name rule of the mock session and the join: trim, NFC, length, visible.
"""A display name is trimmed and NFC-normalized, then has 1-32 characters, one of them visible.

Invisible characters are kept, not stripped: a zero-width joiner holds an emoji sequence together
and the bidirectional marks order mixed-script text. They only cannot make up the whole name.
"""

import unicodedata

NAME_MAX = 32
NAME_RULE = f"displayName must be 1-{NAME_MAX} characters, at least one of them visible"
# Letters and symbols that draw as blank space: the Hangul fillers and the blank Braille pattern.
_BLANK = frozenset("ᅟᅠㅤﾠ⠀")


def _visible(char: str) -> bool:
    """Not a control, format or other C* character, a separator, a combining mark or a blank."""
    return unicodedata.category(char)[0] not in "CZM" and char not in _BLANK


def display_name(raw: str) -> str | None:
    """The name to store and show, or None when ``raw`` breaks the rule."""
    name = unicodedata.normalize("NFC", raw.strip())
    ok = 1 <= len(name) <= NAME_MAX and any(_visible(char) for char in name)
    return name if ok else None
