"""Task queue panel — scrollable list grouped by category."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.widgets import Label, ListItem, ListView, Static

from nightshift.models.task import QueuedTask, TaskCategory, TaskFrequency, TaskStatus
from nightshift.tui.constants import CYAN, DIM, GREEN, GREY, PINK, RED, YELLOW, PRIORITY_DISPLAY

# Statuses shown in active/builtin sections
_VISIBLE_STATUSES = {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.FAILED}
_DONE_STATUSES = {TaskStatus.PASSED, TaskStatus.DONE, TaskStatus.SKIPPED}


class TaskQueuePanel(Static):
    """Bordered panel showing the task queue grouped by category."""

    DEFAULT_CSS = """
    TaskQueuePanel {
        height: 1fr;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="task-queue-panel")
        self._list_view: ListView | None = None
        self._fingerprint: str = ""
        # Parallel map: None for section headers, QueuedTask for task rows.
        self._task_map: list[QueuedTask | None] = []

    def compose(self):
        self._list_view = ListView()
        yield self._list_view

    def on_mount(self) -> None:
        self.border_title = "TASK QUEUE"
        self.add_class("panel")

    @staticmethod
    def _make_fingerprint(tasks: list[QueuedTask]) -> str:
        return "|".join(
            f"{t.id}:{t.status}:{t.priority}:{t.category}:{t.frequency}"
            for t in tasks
        )

    def get_selected_task(self) -> QueuedTask | None:
        if self._list_view is None or not self._task_map:
            return None
        idx = self._list_view.index
        if idx is not None and 0 <= idx < len(self._task_map):
            return self._task_map[idx]
        return None

    def update_tasks(self, tasks: list[QueuedTask]) -> None:
        if self._list_view is None:
            return

        fp = self._make_fingerprint(tasks)
        if fp == self._fingerprint:
            return
        self._fingerprint = fp

        # Group tasks into 4 categories
        active: list[QueuedTask] = []
        builtin: list[QueuedTask] = []
        completed: list[QueuedTask] = []
        inactive: list[QueuedTask] = []

        for t in tasks:
            if t.category == TaskCategory.INACTIVE:
                inactive.append(t)
            elif t.status in _DONE_STATUSES:
                completed.append(t)
            elif t.category == TaskCategory.BUILTIN:
                if t.status in _VISIBLE_STATUSES:
                    builtin.append(t)
            else:
                if t.status in _VISIBLE_STATUSES:
                    active.append(t)

        new_items: list[ListItem] = []
        task_map: list[QueuedTask | None] = []

        if not active and not builtin and not completed and not inactive:
            new_items.append(
                ListItem(Label(Text("No tasks in queue", style=f"italic {GREY}")))
            )
            task_map.append(None)
        else:
            self._add_section(f"ACTIVE ({len(active)})", active, new_items, task_map)
            self._add_section(f"BUILT-IN ({len(builtin)})", builtin, new_items, task_map, show_frequency=True)
            self._add_section(f"INACTIVE ({len(inactive)})", inactive, new_items, task_map, dimmed=True)
            self._add_section(f"COMPLETED ({len(completed)})", completed, new_items, task_map, dimmed=True)

        self._task_map = task_map

        # Single atomic DOM swap
        self._list_view.clear()
        self._list_view.mount(*new_items)

    def _add_section(
        self,
        header: str,
        tasks: list[QueuedTask],
        items: list[ListItem],
        task_map: list[QueuedTask | None],
        *,
        show_frequency: bool = False,
        dimmed: bool = False,
    ) -> None:
        """Append a section header + task rows to the items list."""
        # Section header
        header_text = Text()
        header_text.append(f"── {header} ", style=f"bold {YELLOW}")
        header_text.append("─" * max(0, 40 - len(header)), style=f"{GREY}")
        header_item = ListItem(Label(header_text))
        header_item.disabled = True
        items.append(header_item)
        task_map.append(None)

        if not tasks:
            empty_text = Text("  (empty)", style=f"italic {GREY}")
            empty_item = ListItem(Label(empty_text))
            empty_item.disabled = True
            items.append(empty_item)
            task_map.append(None)
            return

        for task in tasks:
            text = self._render_task_row(task, show_frequency=show_frequency, dimmed=dimmed)
            items.append(ListItem(Label(text)))
            task_map.append(task)

    @staticmethod
    def _render_task_row(
        task: QueuedTask,
        *,
        show_frequency: bool = False,
        dimmed: bool = False,
    ) -> Text:
        text = Text()
        is_failed = task.status == TaskStatus.FAILED
        is_running = task.status == TaskStatus.RUNNING
        is_done = task.status in (TaskStatus.PASSED, TaskStatus.DONE)

        if is_running:
            text.append(" >>> ", style=f"bold {GREEN}")
            text.append("[running]", style=f"{GREEN}")
        elif is_failed:
            text.append(" ✗ ", style=f"{RED}")
            text.append("[failed]", style=f"{RED}")
        elif is_done:
            text.append(" ✓ ", style=f"{DIM}")
            text.append(f"[{task.status.value}]", style=f"{DIM}")
        else:
            priority_symbol, priority_color = PRIORITY_DISPLAY.get(
                task.priority, ("·", GREY)
            )
            color = GREY if dimmed else priority_color
            text.append(f" {priority_symbol} ", style=f"{color}")
            text.append(f"[{task.priority.value}]", style=f"{color}")

        text.append("  ", style="default")
        if dimmed:
            title_color = GREY
        elif is_running:
            title_color = GREEN
        elif is_failed:
            title_color = RED
        elif is_done:
            title_color = DIM
        else:
            title_color = CYAN
        text.append(task.title[:50], style=f"{title_color}")

        text.append("  ", style="default")
        project_name = Path(task.project_path).name
        text.append(project_name, style=f"{PINK}" if not dimmed else f"{GREY}")

        if show_frequency and task.frequency:
            text.append(f"  {task.frequency.value}", style=f"{DIM}")

        return text
