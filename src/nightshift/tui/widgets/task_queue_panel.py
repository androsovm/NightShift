"""Task queue panel — scrollable list of pending tasks."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.widgets import Label, ListItem, ListView, Static

from nightshift.models.task import QueuedTask
from nightshift.tui.constants import CYAN, GREY, PRIORITY_DISPLAY


class TaskQueuePanel(Static):
    """Bordered panel showing the task queue."""

    DEFAULT_CSS = """
    TaskQueuePanel {
        height: 1fr;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="task-queue-panel")
        self._list_view: ListView | None = None
        self._fingerprint: str = ""
        self._tasks: list[QueuedTask] = []

    def compose(self):
        self._list_view = ListView()
        yield self._list_view

    def on_mount(self) -> None:
        self.border_title = "TASK QUEUE"
        self.add_class("panel")

    @staticmethod
    def _make_fingerprint(tasks: list[QueuedTask]) -> str:
        return "|".join(f"{t.id}:{t.status}:{t.priority}" for t in tasks)

    def get_selected_task(self) -> QueuedTask | None:
        if self._list_view is None or not self._tasks:
            return None
        idx = self._list_view.index
        if idx is not None and 0 <= idx < len(self._tasks):
            return self._tasks[idx]
        return None

    def update_tasks(self, tasks: list[QueuedTask]) -> None:
        if self._list_view is None:
            return

        fp = self._make_fingerprint(tasks)
        if fp == self._fingerprint:
            return
        self._fingerprint = fp
        self._tasks = list(tasks)

        self._list_view.clear()

        if not tasks:
            self._list_view.mount(
                ListItem(Label(Text("No pending tasks", style=f"italic {GREY}")))
            )
            return

        for task in tasks:
            text = Text()
            priority_symbol, priority_color = PRIORITY_DISPLAY.get(
                task.priority, ("·", GREY)
            )
            text.append(f" {priority_symbol} ", style=f"{priority_color}")
            text.append(f"[{task.priority.value}]", style=f"{priority_color}")
            text.append("  ", style="default")
            text.append(task.title[:50], style=f"{CYAN}")
            text.append("  ", style="default")
            project_name = Path(task.project_path).name
            text.append(project_name, style=f"{GREY}")

            self._list_view.mount(ListItem(Label(text)))
