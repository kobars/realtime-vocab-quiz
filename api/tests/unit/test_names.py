# AI-ASSISTED: tests for the display name rule: trim, NFC, 1-32 characters, at least one visible.
import pytest

from quiz.domain.names import NAME_MAX, display_name

ZWSP, LRM, RLM, ZWJ = "\u200b", "\u200e", "\u200f", "\u200d"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        ZWSP,
        ZWSP * 5,
        LRM + RLM,
        f" {ZWSP}{LRM} ",
        "⁠﻿­",  # word joiner, BOM, soft hyphen: format characters
        "\x00\x07\x1b",  # control characters
        "́́",  # combining marks with nothing to sit on
        "ㅤᅟ",  # Hangul fillers
        "⠀",  # blank Braille pattern
        "x" * (NAME_MAX + 1),
    ],
)
def test_refused(raw: str) -> None:
    assert display_name(raw) is None


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ("  Ana ", "Ana"),
        ("Café", "Café"),  # NFC
        (f"A{ZWSP}na", f"A{ZWSP}na"),  # visible text keeps its invisible characters
        (f"{RLM}Ana", f"{RLM}Ana"),
        ("🦊", "🦊"),
        (f"👩{ZWJ}💻", f"👩{ZWJ}💻"),  # an emoji sequence held by a zero-width joiner
        ("مريم", "مريم"),  # right-to-left script
        ("x" * NAME_MAX, "x" * NAME_MAX),
    ],
)
def test_accepted(raw: str, stored: str) -> None:
    assert display_name(raw) == stored
