"""nightshift log -- browse run history and task details."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def log(
    task_number: Optional[int] = typer.Argument(
        None, help="Show details of task N from the latest run."
    ),
) -> None:
    """Show recent runs, or details of a specific task."""
    if task_number is not None:
        _show_task_detail(task_number)
    else:
        _show_run_list()


def _show_run_list() -> None:
    """Display a list of recent runs."""
    from nightshift.storage.store import load_runs

    try:
        runs = load_runs()
    except Exception as exc:
        console.print(f"[red]Failed to load run history: {exc}[/red]")
        raise typer.Exit(1)

    if not runs:
        console.print("[yellow]No runs recorded yet.[/yellow]")
        console.print("[dim]Run 'nightshift run' to get started.[/dim]")
        raise typer.Exit(0)

    table = Table(title="Recent NightShift Runs", show_header=True, header_style="bold")
    table.add_column("Run ID", min_width=17)
    table.add_column("Started", width=20)
    table.add_column("Tasks", width=7, justify="right")
    table.add_column("Passed", width=8, justify="right", style="green")
    table.add_column("Failed", width=8, justify="right", style="red")
    table.add_column("Duration", width=10, justify="right")

    for run_result in runs:
        started = run_result.started_at.strftime("%Y-%m-%d %H:%M")
        total = len(run_result.task_results)
        passed = sum(1 for t in run_result.task_results if t.status == "passed")
        failed = sum(1 for t in run_result.task_results if t.status == "failed")

        if run_result.finished_at and run_result.started_at:
            secs = (run_result.finished_at - run_result.started_at).total_seconds()
            duration = f"{secs / 60:.1f}m"
        else:
            duration = "-"

        table.add_row(
            run_result.run_id,
            started,
            str(total),
            str(passed),
            str(failed),
            duration,
        )

    console.print(table)
    console.print(f"\n[dim]{len(runs)} run(s) total. Use 'nightshift log N' to see task details.[/dim]")


def _show_task_detail(task_number: int) -> None:
    """Show detailed information about a specific task from the latest run."""
    from nightshift.storage.store import load_latest_run

    try:
        result = load_latest_run()
    except FileNotFoundError:
        console.print("[yellow]No runs found.[/yellow]")
        raise typer.Exit(0)
    except Exception as exc:
        console.print(f"[red]Failed to load latest run: {exc}[/red]")
        raise typer.Exit(1)

    if result is None:
        console.print("[yellow]No runs found.[/yellow]")
        raise typer.Exit(0)

    if task_number < 1 or task_number > len(result.task_results):
        console.print(
            f"[red]Task {task_number} out of range. "
            f"Latest run has {len(result.task_results)} task(s) (1-{len(result.task_results)}).[/red]"
        )
        raise typer.Exit(1)

    tr = result.task_results[task_number - 1]

    status_style = (
        "green" if tr.status == "passed"
        else "red" if tr.status == "failed"
        else "yellow"
    )

    lines = [
        f"[bold]Task #{task_number}:[/bold] {tr.task_title}",
        f"[bold]Status:[/bold] [{status_style}]{tr.status}[/{status_style}]",
        f"[bold]Project:[/bold] {Path(tr.project_path).name} ({tr.project_path})",
        f"[bold]Task ID:[/bold] {tr.task_id}",
    ]

    if tr.branch:
        lines.append(f"[bold]Branch:[/bold] {tr.branch}")
    if tr.pr_url:
        lines.append(f"[bold]PR:[/bold] {tr.pr_url}")
    if tr.pr_number:
        lines.append(f"[bold]PR #:[/bold] {tr.pr_number}")

    lines.append(f"[bold]Files changed:[/bold] {tr.files_changed}")
    lines.append(f"[bold]Lines:[/bold] +{tr.lines_added} -{tr.lines_removed}")
    lines.append(f"[bold]Duration:[/bold] {tr.duration_seconds:.1f}s")

    if tr.error:
        lines.append(f"\n[bold red]Error:[/bold red]\n{tr.error}")

    if tr.log_file:
        log_path = Path(tr.log_file)
        lines.append(f"\n[bold]Log file:[/bold] {tr.log_file}")
        if log_path.exists():
            log_content = log_path.read_text()
            # Show last 50 lines
            tail = "\n".join(log_content.splitlines()[-50:])
            lines.append(f"\n[dim]--- Last 50 lines of log ---[/dim]\n{tail}")

    console.print(
        Panel(
            "\n".join(lines),
            title=f"Run {result.run_id} - Task {task_number}",
            expand=False,
        )
    )
