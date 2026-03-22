"""Run history panel — recent runs with pass/fail counts."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Label, ListItem, ListView, Static

from nightshift.models.run import RunResult
from nightshift.tui.constants import GREEN, GREY, RED, SPARKLINE_CHARS, YELLOW


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


class RunHistoryPanel(Static):
    """Bordered panel showing recent run history."""

    def __init__(self) -> None:
        super().__init__(id="run-history-panel")
        self._list_view: ListView | None = None
        self._runs: list[RunResult] = []
        self._fingerprint: str = ""

    def compose(self):
        self._list_view = ListView()
        yield self._list_view

    def on_mount(self) -> None:
        self.border_title = "RUN HISTORY"
        self.add_class("panel")

    @staticmethod
    def _make_fingerprint(runs: list[RunResult]) -> str:
        return "|".join(r.run_id for r in runs)

    def update_runs(self, runs: list[RunResult]) -> None:
        fp = self._make_fingerprint(runs)
        if fp == self._fingerprint:
            return
        self._fingerprint = fp
        self._runs = runs

        if self._list_view is None:
            return
        self._list_view.clear()

        if not runs:
            self._list_view.mount(
                ListItem(Label(Text("No runs yet", style=f"italic {GREY}")))
            )
            return

        pass_rates: list[float] = []
        for run in reversed(runs):
            passed = sum(1 for t in run.task_results if t.status == "passed")
            total = len(run.task_results) or 1
            pass_rates.append(passed / total * 100)

        spark = _sparkline(pass_rates)

        for run in runs:
            text = Text()
            run_id_short = run.run_id[:8]
            date_str = run.started_at.strftime("%m/%d %H:%M") if run.started_at else "—"

            passed = sum(1 for t in run.task_results if t.status == "passed")
            failed = sum(1 for t in run.task_results if t.status == "failed")
            skipped = sum(1 for t in run.task_results if t.status == "skipped")

            duration = 0.0
            if run.finished_at and run.started_at:
                duration = (run.finished_at - run.started_at).total_seconds()

            text.append(f"  {run_id_short}", style=f"{GREY}")
            text.append(f"  {date_str}", style=f"{GREY}")
            text.append("  ", style="default")
            if passed:
                text.append(f"{passed}✓", style=f"{GREEN}")
                text.append(" ", style="default")
            if failed:
                text.append(f"{failed}✗", style=f"{RED}")
                text.append(" ", style="default")
            if skipped:
                text.append(f"{skipped}—", style=f"{YELLOW}")
                text.append(" ", style="default")
            text.append(f"  {_format_duration(duration)}", style=f"{GREY}")

            self._list_view.mount(ListItem(Label(text)))

        if spark:
            spark_text = Text()
            spark_text.append(f"  {spark}", style=f"{GREEN}")
            spark_text.append(" pass rate", style=f"{GREY}")
            self._list_view.mount(ListItem(Label(spark_text)))

    def get_selected_run(self) -> RunResult | None:
        if self._list_view is None or not self._runs:
            return None
        idx = self._list_view.index
        if idx is not None and 0 <= idx < len(self._runs):
            return self._runs[idx]
        return None
