"""Tests for TUI constants."""

from nightshift.models.task import TaskPriority, TaskStatus
from nightshift.tui.constants import (
    BRAILLE_SPINNER,
    PRIORITY_DISPLAY,
    SPARKLINE_CHARS,
    STATUS_DISPLAY,
    THEME,
)


class TestTheme:
    def test_theme_has_required_keys(self):
        required = {"bg", "green", "cyan", "pink", "red", "yellow", "grey", "fg", "dim", "border", "accent", "bright"}
        assert required <= set(THEME.keys())

    def test_theme_values_are_hex_colors(self):
        for key, val in THEME.items():
            assert val.startswith("#"), f"{key}: {val} is not a hex color"
            assert len(val) == 7, f"{key}: {val} is not 7 chars"


class TestDisplayMappings:
    def test_all_priorities_have_display(self):
        for p in TaskPriority:
            assert p in PRIORITY_DISPLAY, f"Missing display for priority: {p}"
            symbol, color = PRIORITY_DISPLAY[p]
            assert symbol, f"Empty symbol for {p}"
            assert color.startswith("#"), f"Invalid color for {p}: {color}"

    def test_all_statuses_have_display(self):
        for s in TaskStatus:
            assert s in STATUS_DISPLAY, f"Missing display for status: {s}"
            symbol, label, color = STATUS_DISPLAY[s]
            assert symbol, f"Empty symbol for {s}"
            assert label, f"Empty label for {s}"
            assert color.startswith("#"), f"Invalid color for {s}: {color}"


class TestAnimationConstants:
    def test_sparkline_chars_length(self):
        assert len(SPARKLINE_CHARS) >= 8

    def test_braille_spinner_length(self):
        assert len(BRAILLE_SPINNER) >= 8
