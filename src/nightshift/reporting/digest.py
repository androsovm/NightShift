"""Rich-formatted reporting output."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from nightshift.models.run import RunResult, TaskResult

console = Console()

STATUS_COLORS = {
    "passed": "green",
    "failed": "red",
    "skipped": "yellow",
}


def _format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m {secs:.0f}s"
    hours = int(minutes // 60)
    mins = minutes % 60
    return f"{hours}h {mins}m"


def _run_duration(result: RunResult) -> str:
    """Calculate and format the total run duration."""
    if result.finished_at and result.started_at:
        delta = result.finished_at - result.started_at
        return _format_duration(delta.total_seconds())
    return "in progress"


def _status_counts(result: RunResult) -> dict[str, int]:
    """Count task results by status."""
    counts: dict[str, int] = {"passed": 0, "failed": 0, "skipped": 0}
    for task in result.task_results:
        counts[task.status] = counts.get(task.status, 0) + 1
    return counts


def format_digest(result: RunResult) -> None:
    """Print a full digest of a run to the console using Rich."""
    # --- Summary panel ---
    duration = _run_duration(result)
    started = result.started_at.strftime("%Y-%m-%d %H:%M:%S")
    finished = result.finished_at.strftime("%Y-%m-%d %H:%M:%S") if result.finished_at else "—"

    summary_text = Text()
    summary_text.append("Run ID:    ", style="bold")
    summary_text.append(f"{result.run_id}\n")
    summary_text.append("Started:   ", style="bold")
    summary_text.append(f"{started}\n")
    summary_text.append("Finished:  ", style="bold")
    summary_text.append(f"{finished}\n")
    summary_text.append("Duration:  ", style="bold")
    summary_text.append(duration)

    console.print(Panel(summary_text, title="NightShift Run", border_style="blue"))

    # --- Task table ---
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right", width=4)
    table.add_column("Task")
    table.add_column("Project")
    table.add_column("Status")
    table.add_column("Files", justify="right")
    table.add_column("Lines", justify="right")
    table.add_column("PR")
    table.add_column("Duration", justify="right")

    for i, task in enumerate(result.task_results, 1):
        color = STATUS_COLORS.get(task.status, "white")
        lines = f"+{task.lines_added} -{task.lines_removed}"
        pr = task.pr_url or "—"
        table.add_row(
            str(i),
            task.task_title,
            task.project_path,
            Text(task.status, style=color),
            str(task.files_changed),
            lines,
            pr,
            _format_duration(task.duration_seconds),
        )

    console.print(table)

    # --- Bottom summary ---
    counts = _status_counts(result)
    parts: list[str] = []
    if counts["passed"]:
        parts.append(f"[green]{counts['passed']} passed[/green]")
    if counts["failed"]:
        parts.append(f"[red]{counts['failed']} failed[/red]")
    if counts["skipped"]:
        parts.append(f"[yellow]{counts['skipped']} skipped[/yellow]")
    console.print("\n" + ", ".join(parts))


def format_summary(result: RunResult) -> None:
    """Print a shorter post-run summary."""
    counts = _status_counts(result)
    duration = _run_duration(result)

    parts: list[str] = []
    if counts["passed"]:
        parts.append(f"[green]{counts['passed']} passed[/green]")
    if counts["failed"]:
        parts.append(f"[red]{counts['failed']} failed[/red]")
    if counts["skipped"]:
        parts.append(f"[yellow]{counts['skipped']} skipped[/yellow]")

    status_line = ", ".join(parts) if parts else "no tasks"
    console.print(
        Panel(
            f"{status_line}  [dim]({duration})[/dim]",
            title=f"Run {result.run_id}",
            border_style="blue",
        )
    )


def format_task_detail(result: TaskResult) -> None:
    """Print a detailed view of a single task result."""
    color = STATUS_COLORS.get(result.status, "white")

    detail = Text()
    detail.append("Task ID:   ", style="bold")
    detail.append(f"{result.task_id}\n")
    detail.append("Title:     ", style="bold")
    detail.append(f"{result.task_title}\n")
    detail.append("Project:   ", style="bold")
    detail.append(f"{result.project_path}\n")
    detail.append("Status:    ", style="bold")
    detail.append(f"{result.status}\n", style=color)
    detail.append("Branch:    ", style="bold")
    detail.append(f"{result.branch or '—'}\n")
    detail.append("Duration:  ", style="bold")
    detail.append(f"{_format_duration(result.duration_seconds)}\n")
    detail.append("Files:     ", style="bold")
    detail.append(f"{result.files_changed}\n")
    detail.append("Lines:     ", style="bold")
    detail.append(f"+{result.lines_added} -{result.lines_removed}\n")
    detail.append("PR:        ", style="bold")
    detail.append(f"{result.pr_url or '—'}")

    if result.error:
        detail.append("\n\n")
        detail.append("Error:\n", style="bold red")
        detail.append(result.error, style="red")

    if result.log_file:
        detail.append("\n\n")
        detail.append("Log file:  ", style="bold")
        detail.append(result.log_file, style="dim")

    console.print(Panel(detail, title=f"Task: {result.task_title}", border_style=color))
