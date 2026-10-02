# AI-ASSISTED: the display name rule of the mock session and the join: trim, NFC, length, visible.
"""A display name is trimmed and NFC-normalized, then has 1-32 characters, one of them visible,
and no control character.

Format characters are kept, not stripped: a zero-width joiner holds an emoji sequence together
and the bidirectional marks order mixed-script text. They only cannot make up the whole name.
Control characters (tab, line break, escape) have no use in a name and are refused anywhere.
The join form (web/src/components/join/validation.ts) applies the same rule to the cases in
docs/spec/display-names.json.
"""

import unicodedata

NAME_MAX = 32
NAME_RULE = (
    f"displayName must be 1-{NAME_MAX} characters, at least one of them visible,"
    " and no control characters"
)
# What String.prototype.trim removes: ECMAScript white space and line terminators. str.strip()
# with no argument would also remove U+001C-U+001F and U+0085 but keep U+FEFF.
_TRIM = "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
_TRIM += "\u2028\u2029\u202f\u205f\u3000\ufeff"
# Letters and symbols that draw as blank space: the Hangul fillers and the blank Braille pattern.
_BLANK = frozenset("\u115f\u1160\u3164\uffa0\u2800")
# Unassigned (Cn) and private-use (Co) code points count as visible: a newer emoji may be
# unassigned in the server's Unicode tables while the browser draws it.
_INVISIBLE = frozenset({"Cc", "Cf", "Cs"})


def _visible(char: str) -> bool:
    """Not a control, format or surrogate code point, a separator, a combining mark or a blank."""
    category = unicodedata.category(char)
    return category not in _INVISIBLE and category[0] not in "ZM" and char not in _BLANK


def display_name(raw: str) -> str | None:
    """The name to store and show, or None when ``raw`` breaks the rule."""
    name = unicodedata.normalize("NFC", raw.strip(_TRIM))
    ok = (
        1 <= len(name) <= NAME_MAX
        and any(_visible(char) for char in name)
        and not any(unicodedata.category(char) == "Cc" for char in name)
    )
    return name if ok else None
