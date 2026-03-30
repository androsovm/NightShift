"""Run detail panel — detailed view of a selected run."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Label

from nightshift.models.run import RunResult, TaskResult
from nightshift.tui.constants import CYAN, DIM, GREEN, GREY, RED, YELLOW


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


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _status_counts(run: RunResult) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for task in run.task_results:
        counts[task.status] = counts.get(task.status, 0) + 1
    return counts


def _run_outcome(run: RunResult) -> tuple[str, str]:
    counts = _status_counts(run)
    if run.finished_at is None:
        return "RUNNING", YELLOW
    if counts["failed"]:
        return "FAILED", RED
    if counts["skipped"]:
        return "PARTIAL", YELLOW
    if counts["passed"]:
        return "PASSED", GREEN
    return "EMPTY", GREY


def _run_total_cost(run: RunResult) -> float | None:
    costs = [task.claude_cost_usd for task in run.task_results if task.claude_cost_usd is not None]
    return sum(costs) if costs else None


def _run_total_turns(run: RunResult) -> int | None:
    turns = [task.claude_num_turns for task in run.task_results if task.claude_num_turns is not None]
    return sum(turns) if turns else None


def _run_token_totals(run: RunResult) -> dict[str, int]:
    fields = {
        "input": "claude_input_tokens",
        "output": "claude_output_tokens",
        "cache_create": "claude_cache_creation_tokens",
        "cache_read": "claude_cache_read_tokens",
    }
    totals: dict[str, int] = {}
    for label, attr in fields.items():
        values = [getattr(task, attr) for task in run.task_results if getattr(task, attr) is not None]
        if values:
            totals[label] = sum(values)
    return totals


def _run_diff_totals(run: RunResult) -> tuple[int, int, int]:
    return (
        sum(task.files_changed for task in run.task_results),
        sum(task.lines_added for task in run.task_results),
        sum(task.lines_removed for task in run.task_results),
    )


def _format_cost(cost_usd: float | None) -> str:
    return f"${cost_usd:.2f}" if cost_usd is not None else "n/a"


def _format_token_summary(totals: dict[str, int]) -> str | None:
    parts: list[str] = []
    if "input" in totals:
        parts.append(f"{totals['input']:,} in")
    if "output" in totals:
        parts.append(f"{totals['output']:,} out")
    if "cache_read" in totals:
        parts.append(f"{totals['cache_read']:,} cache read")
    if "cache_create" in totals:
        parts.append(f"{totals['cache_create']:,} cache write")
    return ", ".join(parts) if parts else None


def _summarize_error(error: str | None, limit: int = 180) -> str | None:
    if not error:
        return None
    compact = " ".join(error.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _task_status_style(task: TaskResult) -> tuple[str, str]:
    if task.status == "passed":
        return "✓", GREEN
    if task.status == "failed":
        return "✗", RED
    if task.status == "skipped":
        return "—", YELLOW
    return "?", GREY


def _append_task_block(text: Text, task: TaskResult) -> None:
    symbol, color = _task_status_style(task)
    project_name = Path(task.project_path).name

    text.append(f"  {symbol} ", style=f"{color}")
    text.append(task.task_title[:70], style=f"{CYAN}")
    text.append(f"  [{project_name}]", style=f"{DIM}")
    text.append(f"  {_format_duration(task.duration_seconds)}", style=f"{GREY}")
    if task.claude_cost_usd is not None:
        text.append(f"  {_format_cost(task.claude_cost_usd)}", style=f"{YELLOW}")
    if task.claude_num_turns is not None:
        text.append(f"  {task.claude_num_turns} turns", style=f"{GREY}")
    text.append("\n")

    if task.model:
        text.append(f"    Model: {task.model}\n", style=f"{DIM}")

    token_summary = _format_token_summary(
        {
            key: value
            for key, value in {
                "input": task.claude_input_tokens,
                "output": task.claude_output_tokens,
                "cache_create": task.claude_cache_creation_tokens,
                "cache_read": task.claude_cache_read_tokens,
            }.items()
            if value is not None
        }
    )
    if token_summary:
        text.append(f"    Tokens: {token_summary}\n", style=f"{GREY}")

    if task.pr_url:
        text.append(f"    PR: {task.pr_url}\n", style=f"{GREY}")

    if task.files_changed or task.lines_added or task.lines_removed:
        text.append(
            f"    Diff: {task.files_changed} files, +{task.lines_added}/-{task.lines_removed}\n",
            style=f"{GREY}",
        )

    error_summary = _summarize_error(task.error)
    if error_summary:
        text.append(f"    Why: {error_summary}\n", style=f"{RED if task.status == 'failed' else YELLOW}")

    if task.log_file:
        text.append(f"    Log: {task.log_file}\n", style=f"{DIM}")


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
        self._fingerprint: str = ""

    def compose(self):
        self._content = Label("")
        yield self._content

    def on_mount(self) -> None:
        self.border_title = "RUN SUMMARY"
        self.add_class("panel")
        self._show_empty()

    def _show_empty(self) -> None:
        if self._content:
            self._fingerprint = ""
            self._content.update(
                Text("Select a run from Recent Runs", style=f"italic {GREY}")
            )

    @staticmethod
    def _make_fingerprint(run: RunResult) -> str:
        counts = _status_counts(run)
        return (
            f"{run.run_id}:{run.finished_at.isoformat() if run.finished_at else ''}:"
            f"{len(run.task_results)}:{counts['passed']}:{counts['failed']}:{counts['skipped']}"
        )

    def update_run(self, run: RunResult | None) -> None:
        if self._content is None:
            return
        if run is None:
            self._show_empty()
            return

        fingerprint = self._make_fingerprint(run)
        if fingerprint == self._fingerprint:
            return
        self._fingerprint = fingerprint

        text = Text()
        counts = _status_counts(run)
        outcome, outcome_color = _run_outcome(run)
        total_cost = _run_total_cost(run)
        total_turns = _run_total_turns(run)
        token_summary = _format_token_summary(_run_token_totals(run))
        pr_count = sum(1 for task in run.task_results if task.pr_url)
        files_changed, lines_added, lines_removed = _run_diff_totals(run)

        text.append("Outcome:  ", style=f"bold {GREY}")
        text.append(outcome, style=f"bold {outcome_color}")
        text.append("\n")

        text.append("Started:  ", style=f"bold {GREY}")
        text.append(f"{_format_timestamp(run.started_at)}\n", style=f"{CYAN}")
        if run.started_at:
            text.append("Finished: ", style=f"bold {GREY}")
            text.append(f"{_format_timestamp(run.finished_at)}\n", style=f"{CYAN}")

        if run.finished_at and run.started_at:
            delta = (run.finished_at - run.started_at).total_seconds()
            text.append("Duration: ", style=f"bold {GREY}")
            text.append(f"{_format_duration(delta)}\n", style=f"{CYAN}")
        elif run.started_at and not run.finished_at:
            from nightshift.storage.task_queue import _is_runner_alive

            if _is_runner_alive():
                elapsed = (datetime.now(tz=timezone.utc) - run.started_at).total_seconds()
                text.append("Elapsed:  ", style=f"bold {GREY}")
                text.append(f"{_format_duration(elapsed)}", style=f"{YELLOW}")
                text.append(" ⏱\n", style=f"{YELLOW}")

        text.append("Tasks:    ", style=f"bold {GREY}")
        text.append(f"{len(run.task_results)} total", style=f"{CYAN}")
        text.append(f"  {counts['passed']} passed", style=f"{GREEN}")
        text.append(f"  {counts['failed']} failed", style=f"{RED}")
        text.append(f"  {counts['skipped']} skipped\n", style=f"{YELLOW}")

        text.append("Spend:    ", style=f"bold {GREY}")
        text.append(_format_cost(total_cost), style=f"{YELLOW if total_cost is not None else GREY}")
        if total_turns is not None:
            text.append(f"  {total_turns} turns", style=f"{GREY}")
        text.append("\n")

        text.append("Tokens:   ", style=f"bold {GREY}")
        text.append(token_summary or "n/a", style=f"{GREY}")
        text.append("\n")

        text.append("Artifacts:", style=f"bold {GREY}")
        text.append(f" {pr_count} PRs", style=f"{CYAN}")
        if files_changed or lines_added or lines_removed:
            text.append(
                f"  {files_changed} files, +{lines_added}/-{lines_removed}",
                style=f"{GREY}",
            )
        text.append("\n")

        text.append("Run ID:   ", style=f"bold {GREY}")
        text.append(f"{run.run_id}\n", style=f"{DIM}")
        text.append("\n")

        failed = [task for task in run.task_results if task.status == "failed"]
        skipped = [task for task in run.task_results if task.status == "skipped"]
        passed = [task for task in run.task_results if task.status == "passed"]
        other = [task for task in run.task_results if task.status not in {"failed", "skipped", "passed"}]

        sections = [
            ("Failures", RED, failed),
            ("Skipped", YELLOW, skipped),
            ("Passed", GREEN, passed),
            ("Other", GREY, other),
        ]

        for title, color, tasks in sections:
            if not tasks:
                continue
            text.append(f"{title}\n", style=f"bold {color}")
            for task in tasks:
                _append_task_block(text, task)
            text.append("\n")

        if not run.task_results:
            text.append("No task results recorded for this run.", style=f"italic {GREY}")

        self._content.update(text)
        self.scroll_home(animate=False)
