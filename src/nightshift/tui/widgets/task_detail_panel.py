"""Task detail panel — shows description of the selected task."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Label, Static

from nightshift.models.task import QueuedTask
from nightshift.tui.constants import CYAN, GREEN, GREY, PRIORITY_DISPLAY, RED, YELLOW


class TaskDetailPanel(VerticalScroll):
    """Scrollable bordered panel showing detail for a selected task."""

    DEFAULT_CSS = """
    TaskDetailPanel {
        height: 1fr;
        scrollbar-size: 1 1;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="task-detail-panel")
        self._content: Label | None = None

    def compose(self):
        self._content = Label("")
        yield self._content

    def on_mount(self) -> None:
        self.border_title = "TASK DETAIL"
        self.add_class("panel")
        self._show_empty()

    def _show_empty(self) -> None:
        if self._content:
            self._content.update(
                Text("Select a task from the queue", style=f"italic {GREY}")
            )

    def update_task(self, task: QueuedTask | None) -> None:
        if self._content is None:
            return
        if task is None:
            self._show_empty()
            return

        priority_symbol, priority_color = PRIORITY_DISPLAY.get(
            task.priority, ("·", GREY)
        )

        text = Text()
        text.append("Title:    ", style=f"bold {GREY}")
        text.append(f"{task.title}\n", style=f"{CYAN}")

        text.append("Project:  ", style=f"bold {GREY}")
        text.append(f"{Path(task.project_path).name}\n", style=f"{CYAN}")

        text.append("Priority: ", style=f"bold {GREY}")
        text.append(f"{priority_symbol} {task.priority.value}\n", style=f"{priority_color}")

        text.append("Source:   ", style=f"bold {GREY}")
        text.append(f"{task.source_type}")
        if task.source_ref:
            text.append(f" ({task.source_ref})", style=f"{GREY}")
        text.append("\n")

        text.append("Model:    ", style=f"bold {GREY}")
        text.append(f"{task.model or 'project default'}\n", style=f"{CYAN}")

        text.append("Status:   ", style=f"bold {GREY}")
        text.append(f"{task.status.value}\n")

        if task.estimated_minutes:
            text.append("Estimate: ", style=f"bold {GREY}")
            text.append(f"~{task.estimated_minutes}min\n")

        if task.intent:
            text.append("\n")
            text.append("Intent:\n", style=f"bold {GREY}")
            text.append(f"  {task.intent}\n")

        if task.scope:
            text.append("\n")
            text.append("Scope:\n", style=f"bold {GREY}")
            for s in task.scope:
                text.append(f"  · {s}\n", style=f"{CYAN}")

        if task.constraints:
            text.append("\n")
            text.append("Constraints:\n", style=f"bold {GREY}")
            for c in task.constraints:
                text.append(f"  · {c}\n", style=f"{YELLOW}")

        if task.attempts:
            text.append("\n")
            text.append(f"Attempts: {len(task.attempts)}\n", style=f"bold {GREY}")
            for attempt in task.attempts[-3:]:
                status = attempt.status.value
                color = GREEN if status == "passed" else RED if status == "failed" else GREY
                text.append(f"  {attempt.timestamp.strftime('%m/%d %H:%M')}", style=f"{GREY}")
                text.append(f"  {status}", style=f"{color}")
                if attempt.pr_url:
                    text.append(f"  PR: {attempt.pr_url}", style=f"{GREY}")
                text.append("\n")

        self._content.update(text)
        self.scroll_home(animate=False)
