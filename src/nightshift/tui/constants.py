"""Colors, status definitions, and UI constants for the TUI dashboard."""

from __future__ import annotations

from nightshift.models.task import TaskPriority, TaskStatus

# Nord Aurora theme palette (consistent with Clorch)
THEME = {
    "bg": "#2E3440",
    "green": "#A3BE8C",
    "cyan": "#88C0D0",
    "pink": "#B48EAD",
    "red": "#BF616A",
    "yellow": "#EBCB8B",
    "grey": "#616E88",
    "fg": "#D8DEE9",
    "dim": "#4C566A",
    "border": "#3B4252",
    "accent": "#434C5E",
    "bright": "#ECEFF4",
}

GREEN = THEME["green"]
CYAN = THEME["cyan"]
PINK = THEME["pink"]
RED = THEME["red"]
YELLOW = THEME["yellow"]
GREY = THEME["grey"]
DIM = THEME["dim"]
BORDER = THEME["border"]
ACCENT = THEME["accent"]

# Task priority display: symbol, color
PRIORITY_DISPLAY: dict[TaskPriority, tuple[str, str]] = {
    TaskPriority.HIGH: ("●", RED),
    TaskPriority.MEDIUM: ("○", YELLOW),
    TaskPriority.LOW: ("·", GREY),
}

# Task status display: symbol, label, color
STATUS_DISPLAY: dict[TaskStatus, tuple[str, str, str]] = {
    TaskStatus.PENDING: ("◦", "pending", GREY),
    TaskStatus.RUNNING: (">>>", "running", GREEN),
    TaskStatus.PASSED: ("✓", "passed", GREEN),
    TaskStatus.FAILED: ("✗", "failed", RED),
    TaskStatus.SKIPPED: ("—", "skipped", YELLOW),
    TaskStatus.DONE: ("✓", "done", GREEN),
}

# Run result status colors
RUN_STATUS_COLORS = {
    "passed": GREEN,
    "failed": RED,
    "skipped": YELLOW,
}

# Sparkline characters (8 levels)
SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"

# Braille spinner frames
BRAILLE_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Poll interval for data refresh (seconds)
POLL_INTERVAL = 2.0

# Animation tick interval (seconds)
ANIM_INTERVAL = 0.25
