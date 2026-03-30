"""Run history panel — recent runs with pass/fail counts."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.widgets import Label, ListItem, ListView, Static

from nightshift.models.run import RunResult
from nightshift.tui.constants import BRAILLE_SPINNER, CYAN, GREEN, GREY, RED, SPARKLINE_CHARS, YELLOW


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours = int(minutes // 60)
    mins = minutes % 60
    return f"{hours}h{mins}m"


def _sparkline(values: list[float], width: int = 10) -> str:
    if not values:
        return ""
    max_val = max(values) if max(values) > 0 else 1
    chars = []
    for v in values[-width:]:
        idx = int(v / max_val * (len(SPARKLINE_CHARS) - 1))
        chars.append(SPARKLINE_CHARS[idx])
    return "".join(chars)


def _format_started_at(started_at: datetime | None) -> str:
    if started_at is None:
        return "—"
    return started_at.astimezone().strftime("%m/%d %H:%M")


def _status_counts(run: RunResult) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for task in run.task_results:
        counts[task.status] = counts.get(task.status, 0) + 1
    return counts


def _run_total_cost(run: RunResult) -> float | None:
    costs = [task.claude_cost_usd for task in run.task_results if task.claude_cost_usd is not None]
    return sum(costs) if costs else None


def _format_cost(cost_usd: float | None) -> str:
    if cost_usd is None:
        return ""
    return f"${cost_usd:.2f}"


def _run_outcome(run: RunResult) -> tuple[str, str]:
    counts = _status_counts(run)
    if run.finished_at is None:
        return "RUN", YELLOW
    if counts["failed"]:
        return "FAIL", RED
    if counts["skipped"]:
        return "PART", YELLOW
    if counts["passed"]:
        return "OK", GREEN
    return "EMPTY", GREY


def _run_summary_text(run: RunResult) -> Text:
    counts = _status_counts(run)
    outcome, outcome_color = _run_outcome(run)
    total_tasks = len(run.task_results)
    date_str = _format_started_at(run.started_at)
    duration = (
        _format_duration((run.finished_at - run.started_at).total_seconds())
        if run.finished_at and run.started_at
        else "running"
    )
    cost = _format_cost(_run_total_cost(run))

    if counts["failed"]:
        summary = f"{counts['failed']} failed"
        summary_color = RED
    elif counts["skipped"]:
        summary = f"{counts['skipped']} skipped"
        summary_color = YELLOW
    elif counts["passed"]:
        summary = "all passed"
        summary_color = GREEN
    else:
        summary = "no tasks"
        summary_color = GREY

    text = Text()
    text.append(f" {outcome:<5}", style=f"bold {outcome_color}")
    text.append(f" {date_str}", style=f"{GREY}")
    text.append(f"  {total_tasks} task{'s' if total_tasks != 1 else ''}", style=f"{CYAN}")
    text.append(f"  {summary}", style=f"{summary_color}")
    text.append(f"  {duration}", style=f"{GREY}")
    if cost:
        text.append(f"  {cost}", style=f"{YELLOW}")
    return text


class RunHistoryPanel(Static):
    """Bordered panel showing recent run history."""

    def __init__(self) -> None:
        super().__init__(id="run-history-panel")
        self._list_view: ListView | None = None
        self._runs: list[RunResult] = []
        self._fingerprint: str = ""
        self._running_label: str = ""
        self._spinner_frame: int = 0
        self._running_item: ListItem | None = None
        self._run_map: list[RunResult | None] = []

    def compose(self):
        self._list_view = ListView()
        yield self._list_view

    def on_mount(self) -> None:
        self.border_title = "RECENT RUNS"
        self.add_class("panel")
        self.set_interval(0.25, self._tick_spinner)

    def set_running(self, label: str) -> None:
        """Show a running entry at the top of the list."""
        selected_run = self.get_selected_run()
        self._running_label = label
        self._spinner_frame = 0
        self._update_running_item()
        self._restore_selection(selected_run.run_id if selected_run else None)

    def set_idle(self) -> None:
        """Remove the running entry."""
        selected_run = self.get_selected_run()
        self._running_label = ""
        if self._running_item and self._list_view:
            self._running_item.remove()
            self._running_item = None
            if self._run_map and self._run_map[0] is None:
                self._run_map.pop(0)
            self._restore_selection(selected_run.run_id if selected_run else None)

    def _tick_spinner(self) -> None:
        """Animate the spinner on the running entry."""
        if not self._running_label or not self._running_item:
            return
        self._spinner_frame += 1
        spinner = BRAILLE_SPINNER[self._spinner_frame % len(BRAILLE_SPINNER)]
        row = Text()
        row.append(f"  {spinner} LIVE ", style=f"bold {YELLOW}")
        row.append(f"{self._running_label}", style=f"{CYAN}")
        self._running_item.query_one(Label).update(row)

    def _update_running_item(self) -> None:
        """Insert or update the running entry at the top."""
        if not self._list_view or not self._running_label:
            return
        spinner = BRAILLE_SPINNER[0]
        row = Text()
        row.append(f"  {spinner} LIVE ", style=f"bold {YELLOW}")
        row.append(f"{self._running_label}", style=f"{CYAN}")
        if self._running_item:
            self._running_item.query_one(Label).update(row)
        else:
            self._running_item = ListItem(Label(row))
            self._running_item.disabled = True
            self._list_view.mount(self._running_item, before=0)
            self._run_map.insert(0, None)

    @staticmethod
    def _make_fingerprint(runs: list[RunResult]) -> str:
        return "|".join(
            f"{r.run_id}:{r.finished_at.isoformat() if r.finished_at else ''}:{len(r.task_results)}"
            for r in runs
        )

    def _restore_selection(self, selected_run_id: str | None) -> None:
        if self._list_view is None or not self._run_map:
            return

        target_index: int | None = None
        if selected_run_id:
            for idx, run in enumerate(self._run_map):
                if run and run.run_id == selected_run_id:
                    target_index = idx
                    break

        if target_index is None:
            for idx, run in enumerate(self._run_map):
                if run is not None:
                    target_index = idx
                    break

        self._list_view.index = target_index

    def update_runs(self, runs: list[RunResult]) -> None:
        selected_run = self.get_selected_run()
        fp = self._make_fingerprint(runs)
        if fp == self._fingerprint:
            return
        self._fingerprint = fp
        self._runs = runs

        if self._list_view is None:
            return
        self._list_view.clear()
        self._running_item = None  # cleared by lv.clear()
        self._run_map = []

        # Re-insert running indicator if active
        if self._running_label:
            self._update_running_item()

        if not runs:
            empty_item = ListItem(Label(Text("No runs yet", style=f"italic {GREY}")))
            empty_item.disabled = True
            self._list_view.mount(empty_item)
            self._run_map.append(None)
            return

        for run in runs:
            self._list_view.mount(ListItem(Label(_run_summary_text(run))))
            self._run_map.append(run)

        self._restore_selection(selected_run.run_id if selected_run else None)

    def get_selected_run(self) -> RunResult | None:
        if self._list_view is None or not self._run_map:
            return None
        idx = self._list_view.index
        if idx is not None and 0 <= idx < len(self._run_map):
            return self._run_map[idx]
        return None
