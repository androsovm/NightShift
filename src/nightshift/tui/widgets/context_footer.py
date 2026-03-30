"""Context footer widget — keybinding hints."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from nightshift.tui.constants import CYAN, GREY


class ContextFooter(Static):
    """Bottom bar with available keybinding hints."""

    DEFAULT_CSS = """
    ContextFooter {
        height: 1;
        padding: 0 1;
        dock: bottom;
        color: #616E88;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="context-footer")

    def on_mount(self) -> None:
        text = Text()
        bindings = [
            ("q", "Quit"),
            ("r", "Run task"),
            ("R", "Run all"),
            ("t", "Add"),
            ("x", "Toggle/Remove"),
            ("p", "Priority"),
            ("e", "Retry"),
            ("m", "Model"),
            ("s", "Sync"),
            ("d", "Doctor"),
            ("?", "Help"),
        ]
        for i, (key, label) in enumerate(bindings):
            if i > 0:
                text.append("  ", style="default")
            text.append(f"[{key}]", style=f"bold {CYAN}")
            text.append(f" {label}", style=f"{GREY}")
        self.update(text)
