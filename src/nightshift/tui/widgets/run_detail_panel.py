"""Run detail panel — detailed view of a selected run."""

from __future__ import annotations

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Label

from nightshift.models.run import RunResult
from nightshift.tui.constants import CYAN, GREEN, GREY, RED, YELLOW


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m {secs:.0f}s"
    hours = int(minutes // 60)
    mins = minutes % 60
    return f"{hours}h {mins}m"


class RunDetailPanel(VerticalScroll):
    """Scrollable bordered panel showing detail for a selected run."""

    DEFAULT_CSS = """
    RunDetailPanel {
        height: 1fr;
        scrollbar-size: 1 1;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="run-detail-panel")
        self._content: Label | None = None

    def compose(self):
        self._content = Label("")
        yield self._content

    def on_mount(self) -> None:
        self.border_title = "RUN DETAIL"
        self.add_class("panel")
        self._show_empty()

    def _show_empty(self) -> None:
        if self._content:
            self._content.update(
                Text("Select a run from history", style=f"italic {GREY}")
            )

    def update_run(self, run: RunResult | None) -> None:
        if self._content is None:
            return
        if run is None:
            self._show_empty()
            return

        text = Text()
        text.append("Run ID:   ", style=f"bold {GREY}")
        text.append(f"{run.run_id}\n", style=f"{CYAN}")

        if run.started_at:
            text.append("Started:  ", style=f"bold {GREY}")
            text.append(f"{run.started_at.strftime('%Y-%m-%d %H:%M:%S')}\n")

        if run.finished_at and run.started_at:
            delta = (run.finished_at - run.started_at).total_seconds()
            text.append("Duration: ", style=f"bold {GREY}")
            text.append(f"{_format_duration(delta)}\n")

        text.append("\n")

        for task_result in run.task_results:
            status = task_result.status
            if status == "passed":
                symbol, color = "✓", GREEN
            elif status == "failed":
                symbol, color = "✗", RED
            elif status == "skipped":
                symbol, color = "—", YELLOW
            else:
                symbol, color = "?", GREY

            text.append(f"  {symbol} ", style=f"{color}")
            text.append(f"{task_result.task_title[:40]}", style=f"{CYAN}")
            text.append(f"  {_format_duration(task_result.duration_seconds)}", style=f"{GREY}")

            if task_result.pr_url:
                text.append(f"\n    PR: {task_result.pr_url}", style=f"{GREY}")

            if task_result.error:
                text.append(f"\n    {task_result.error[:60]}", style=f"{RED}")

            text.append("\n")

        self._content.update(text)
        self.scroll_home(animate=False)
