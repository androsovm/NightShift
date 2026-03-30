"""Tests for TUI constants."""

from pathlib import Path

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
        required = {
            "bg",
            "selection",
            "selection_focus",
            "green",
            "cyan",
            "pink",
            "red",
            "yellow",
            "grey",
            "fg",
            "dim",
            "border",
            "accent",
            "bright",
        }
        assert required <= set(THEME.keys())

    def test_theme_values_are_hex_colors(self):
        for key, val in THEME.items():
            assert val.startswith("#"), f"{key}: {val} is not a hex color"
            assert len(val) == 7, f"{key}: {val} is not 7 chars"

    def test_selection_background_preserves_accent_contrast(self):
        def _relative_luminance(color: str) -> float:
            rgb = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]

            def _linearize(channel: float) -> float:
                if channel <= 0.03928:
                    return channel / 12.92
                return ((channel + 0.055) / 1.055) ** 2.4

            red, green, blue = map(_linearize, rgb)
            return 0.2126 * red + 0.7152 * green + 0.0722 * blue

        def _contrast_ratio(left: str, right: str) -> float:
            hi, lo = sorted(
                (_relative_luminance(left), _relative_luminance(right)),
                reverse=True,
            )
            return (hi + 0.05) / (lo + 0.05)

        selection = THEME["selection"]
        for key in ("fg", "cyan", "green", "yellow", "pink", "red"):
            assert _contrast_ratio(THEME[key], selection) >= 3.0, (
                f"{key} should stay readable on selection background"
            )

    def test_textual_highlight_selectors_use_single_dash(self):
        repo_root = Path(__file__).resolve().parents[2]
        for rel_path in ("src/nightshift/tui/app.tcss", "src/nightshift/tui/app.py"):
            content = (repo_root / rel_path).read_text(encoding="utf-8")
            assert ".--highlight" not in content, f"Found invalid selector in {rel_path}"


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
