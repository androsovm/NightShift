"""nightshift status -- show latest run status."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

console = Console()


def status() -> None:
    """Show the status of the latest NightShift run."""
    from nightshift.reporting.digest import format_digest
    from nightshift.storage.store import load_latest_run

    try:
        result = load_latest_run()
    except FileNotFoundError:
        console.print("[yellow]No runs found yet.[/yellow]")
        console.print("[dim]Run 'nightshift run' to execute your first run.[/dim]")
        raise typer.Exit(0)
    except Exception as exc:
        console.print(f"[red]Failed to load run data: {exc}[/red]")
        raise typer.Exit(1)

    if result is None:
        console.print("[yellow]No runs found yet.[/yellow]")
        console.print("[dim]Run 'nightshift run' to execute your first run.[/dim]")
        raise typer.Exit(0)

    # Header
    started = result.started_at.strftime("%Y-%m-%d %H:%M:%S")
    finished = result.finished_at.strftime("%H:%M:%S") if result.finished_at else "in progress"
    console.print(
        Panel(
            f"[bold cyan]Run {result.run_id}[/bold cyan]\n"
            f"Started: {started}  |  Finished: {finished}",
            expand=False,
        )
    )

    # Use the digest formatter
    try:
        format_digest(result)
    except Exception:
        # Fallback: basic summary
        _fallback_status(result)


def _fallback_status(result) -> None:
    """Basic status display when the digest formatter is unavailable."""
    from rich.table import Table

    passed = sum(1 for t in result.task_results if t.status == "passed")
    failed = sum(1 for t in result.task_results if t.status == "failed")
    skipped = sum(1 for t in result.task_results if t.status == "skipped")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Task", min_width=25)
    table.add_column("Status", width=10)
    table.add_column("PR", width=30)
    table.add_column("Files", width=8, justify="right")
    table.add_column("+/-", width=12, justify="right")

    for tr in result.task_results:
        status_style = (
            "green" if tr.status == "passed"
            else "red" if tr.status == "failed"
            else "yellow"
        )
        pr = tr.pr_url or "-"
        diff = f"+{tr.lines_added} -{tr.lines_removed}" if tr.lines_added or tr.lines_removed else "-"
        table.add_row(
            tr.task_title,
            f"[{status_style}]{tr.status}[/{status_style}]",
            pr,
            str(tr.files_changed) if tr.files_changed else "-",
            diff,
        )

    console.print(table)
    console.print(f"\n[bold]{passed} passed[/bold], [red]{failed} failed[/red], [yellow]{skipped} skipped[/yellow]")

    if result.finished_at and result.started_at:
        duration = result.finished_at - result.started_at
        minutes = duration.total_seconds() / 60
        console.print(f"[dim]Total duration: {minutes:.1f} minutes[/dim]")
