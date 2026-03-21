"""nightshift run -- execute tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def run(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show plan without executing."),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Run only for a specific project path or name."
    ),
) -> None:
    """Execute a NightShift run (collect tasks and process them)."""
    from nightshift.config.loader import load_global_config
    from nightshift.executor.runner import execute_run
    from nightshift.reporting.digest import format_summary
    from nightshift.storage.store import save_run

    try:
        global_config = load_global_config()
    except Exception as exc:
        console.print(f"[red]Failed to load global config: {exc}[/red]")
        console.print("[dim]Run 'nightshift init' to set up configuration.[/dim]")
        raise typer.Exit(1)

    # Resolve project filter
    project_path: Path | None = None
    if project:
        # Try as absolute path first, then match by name
        candidate = Path(project)
        if candidate.is_absolute() and candidate.is_dir():
            project_path = candidate
        else:
            for pref in global_config.projects:
                if pref.path.name == project or str(pref.path) == project:
                    project_path = pref.path
                    break
            if project_path is None:
                console.print(f"[red]Project '{project}' not found in config.[/red]")
                console.print("[dim]Configured projects:[/dim]")
                for pref in global_config.projects:
                    console.print(f"  - {pref.path}")
                raise typer.Exit(1)

    if dry_run:
        _dry_run(global_config, project_path)
        return

    # --- Live run ---
    # Set up file logging for unattended runs
    from datetime import datetime, timezone

    from nightshift.logging import configure_logging
    from nightshift.storage.store import get_log_dir

    run_id = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    log_dir = get_log_dir(run_id)
    configure_logging(log_file=log_dir / "run.log")

    console.print(Panel("[bold cyan]NightShift Run[/bold cyan]", expand=False))

    projects_to_run = (
        [p for p in global_config.projects if p.path == project_path]
        if project_path
        else global_config.projects
    )

    if not projects_to_run:
        console.print("[yellow]No projects to run.[/yellow]")
        raise typer.Exit(0)

    console.print(f"Running for {len(projects_to_run)} project(s)...")

    import asyncio

    try:
        result = asyncio.run(execute_run(global_config, project_path=project_path))
    except Exception as exc:
        console.print(f"[red]Run failed: {exc}[/red]")
        raise typer.Exit(1)

    # Persist
    try:
        save_run(result)
    except Exception as exc:
        console.print(f"[yellow]Warning: failed to save run result: {exc}[/yellow]")

    # Display summary
    try:
        format_summary(result)
    except Exception:
        # Fallback: manual summary
        _print_result_table(result)

    # Exit code based on results
    failed = sum(1 for tr in result.task_results if tr.status == "failed")
    if failed:
        console.print(f"\n[red]{failed} task(s) failed.[/red]")
        raise typer.Exit(1)


def _dry_run(global_config, project_path: Path | None) -> None:
    """Show tasks from the local queue that would be executed."""
    from nightshift.config.loader import load_project_config
    from nightshift.storage.task_queue import get_pending_tasks

    console.print(Panel("[bold yellow]DRY RUN[/bold yellow] -- no changes will be made", expand=False))

    project_filter = str(project_path.resolve()) if project_path else None
    pending = get_pending_tasks(project_path=project_filter)

    if not pending:
        console.print("[dim]No pending tasks in queue.[/dim]")
        console.print("[dim]Run 'nightshift sync' to import from sources, or 'nightshift tasks add' to create one.[/dim]")
        return

    # Group by project
    projects: dict[str, list] = {}
    for qt in pending:
        projects.setdefault(qt.project_path, []).append(qt)

    total_tasks = 0
    for proj_path_str, tasks in projects.items():
        proj_path = Path(proj_path_str)
        console.print(f"\n[bold cyan]{proj_path.name}[/bold cyan] ({proj_path})")

        try:
            project_config = load_project_config(proj_path)
        except Exception as exc:
            console.print(f"  [red]Could not load project config: {exc}[/red]")
            continue

        limit = project_config.limits.max_tasks_per_run

        table = Table(show_header=True, header_style="bold")
        table.add_column("#", style="dim", width=4)
        table.add_column("Task", min_width=30)
        table.add_column("Source", width=10)
        table.add_column("Priority", width=10)

        for i, qt in enumerate(tasks[:limit], 1):
            table.add_row(str(i), qt.title, qt.source_type, qt.priority)

        console.print(table)
        total_tasks += min(len(tasks), limit)
        if len(tasks) > limit:
            console.print(
                f"  [dim]({len(tasks) - limit} "
                f"additional tasks queued beyond limit)[/dim]"
            )

    console.print(f"\n[bold]Total: {total_tasks} task(s) across {len(projects)} project(s)[/bold]")
    console.print("[dim]Run without --dry-run to execute.[/dim]")


def _print_result_table(result) -> None:
    """Fallback result display."""
    table = Table(title="Run Results", show_header=True, header_style="bold")
    table.add_column("Task", min_width=25)
    table.add_column("Project")
    table.add_column("Status", width=10)
    table.add_column("PR", width=20)
    table.add_column("Duration", width=10)

    for tr in result.task_results:
        status_style = "green" if tr.status == "passed" else "red" if tr.status == "failed" else "yellow"
        pr_display = tr.pr_url or "-"
        duration = f"{tr.duration_seconds:.0f}s"
        table.add_row(
            tr.task_title,
            Path(tr.project_path).name,
            f"[{status_style}]{tr.status}[/{status_style}]",
            pr_display,
            duration,
        )

    console.print(table)

    passed = sum(1 for tr in result.task_results if tr.status == "passed")
    failed = sum(1 for tr in result.task_results if tr.status == "failed")
    skipped = sum(1 for tr in result.task_results if tr.status == "skipped")
    console.print(
        f"\n[bold]Summary:[/bold] {passed} passed, {failed} failed, {skipped} skipped"
    )
