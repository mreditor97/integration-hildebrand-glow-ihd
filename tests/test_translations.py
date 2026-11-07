"""Tests for the translation files."""

from __future__ import annotations

import json
from pathlib import Path

INTEGRATION = Path(__file__).parent.parent / "custom_components/hildebrand_glow_ihd"


def test_strings_match_english_translation() -> None:
    """Home Assistant reads translations/en.json, keep strings.json the same."""
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    english = json.loads(
        (INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8"),
    )
    assert strings == english
