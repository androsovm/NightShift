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
    """Collect tasks and display plan without executing."""
    from nightshift.config.loader import load_project_config

    console.print(Panel("[bold yellow]DRY RUN[/bold yellow] -- no changes will be made", expand=False))

    projects_to_run = (
        [p for p in global_config.projects if p.path == project_path]
        if project_path
        else global_config.projects
    )

    if not projects_to_run:
        console.print("[yellow]No projects configured.[/yellow]")
        return

    total_tasks = 0
    for pref in projects_to_run:
        console.print(f"\n[bold cyan]{pref.path.name}[/bold cyan] ({pref.path})")

        try:
            project_config = load_project_config(pref.path)
        except Exception as exc:
            console.print(f"  [red]Could not load project config: {exc}[/red]")
            continue

        # Collect tasks from each source
        import asyncio

        from nightshift.sources import ADAPTERS

        tasks = []
        for source_cfg in project_config.sources:
            adapter_cls = ADAPTERS.get(str(source_cfg.type))
            if adapter_cls is None:
                console.print(f"  [yellow]Unknown source type: {source_cfg.type}[/yellow]")
                continue
            try:
                adapter = adapter_cls()
                source_tasks = asyncio.run(adapter.fetch_tasks(str(pref.path), source_cfg))
                tasks.extend(source_tasks)
            except Exception as exc:
                console.print(f"  [yellow]Failed to collect from {source_cfg.type}: {exc}[/yellow]")

        if not tasks:
            console.print("  [dim]No tasks found.[/dim]")
            continue

        table = Table(show_header=True, header_style="bold")
        table.add_column("#", style="dim", width=4)
        table.add_column("Task", min_width=30)
        table.add_column("Source", width=10)
        table.add_column("Priority", width=10)

        for i, task in enumerate(tasks[: project_config.limits.max_tasks_per_run], 1):
            table.add_row(str(i), task.title, task.source_type, task.priority)

        console.print(table)
        total_tasks += min(len(tasks), project_config.limits.max_tasks_per_run)
        if len(tasks) > project_config.limits.max_tasks_per_run:
            console.print(
                f"  [dim]({len(tasks) - project_config.limits.max_tasks_per_run} "
                f"additional tasks queued beyond limit)[/dim]"
            )

    console.print(f"\n[bold]Total: {total_tasks} task(s) across {len(projects_to_run)} project(s)[/bold]")
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
