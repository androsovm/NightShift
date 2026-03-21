"""nightshift tasks -- manage the local task queue."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import questionary
import typer
from rich.console import Console
from rich.table import Table
from slugify import slugify

from nightshift.models.task import QueuedTask, TaskPriority, TaskStatus
from nightshift.storage.task_queue import (
    add_task,
    get_task,
    load_tasks,
    remove_task,
    update_task,
)

console = Console()

tasks_app = typer.Typer(
    name="tasks",
    help="Manage the local task queue.",
    no_args_is_help=True,
    invoke_without_command=True,
)


@tasks_app.callback(invoke_without_command=True)
def tasks_default(ctx: typer.Context) -> None:
    """Show task list when no subcommand given."""
    if ctx.invoked_subcommand is None:
        list_tasks()


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@tasks_app.command("list")
def list_tasks(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status."),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filter by project name."),
    priority: Optional[str] = typer.Option(None, "--priority", help="Filter by priority."),
) -> None:
    """List all tasks in the queue."""
    tasks = load_tasks()

    if status:
        tasks = [t for t in tasks if t.status == status]
    if project:
        tasks = [t for t in tasks if Path(t.project_path).name == project or t.project_path == project]
    if priority:
        tasks = [t for t in tasks if t.priority == priority]

    if not tasks:
        console.print("[dim]No tasks in queue.[/dim]")
        console.print("[dim]Run 'nightshift sync' to import from sources, or 'nightshift tasks add' to create one.[/dim]")
        return

    table = Table(show_header=True)
    table.add_column("ID", style="cyan", max_width=30)
    table.add_column("Title", max_width=50)
    table.add_column("Status", justify="center")
    table.add_column("Priority", justify="center")
    table.add_column("Project", max_width=20)
    table.add_column("Source")
    table.add_column("#", justify="right")

    status_styles = {
        "pending": "[white]pending[/white]",
        "passed": "[green]passed[/green]",
        "failed": "[red]failed[/red]",
        "skipped": "[yellow]skipped[/yellow]",
        "running": "[blue]running[/blue]",
        "done": "[dim]done[/dim]",
    }
    priority_styles = {
        "high": "[red]high[/red]",
        "medium": "[yellow]medium[/yellow]",
        "low": "[dim]low[/dim]",
    }

    for t in tasks:
        table.add_row(
            t.id,
            t.title[:50],
            status_styles.get(t.status, t.status),
            priority_styles.get(t.priority, t.priority),
            Path(t.project_path).name,
            t.source_type,
            str(len(t.attempts)),
        )

    console.print(table)
    console.print(f"[dim]{len(tasks)} task(s)[/dim]")


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


@tasks_app.command()
def add(
    title: Optional[str] = typer.Argument(None, help="Task title (interactive if omitted)."),
) -> None:
    """Add a task manually to the queue."""
    from nightshift.config.loader import load_global_config

    if not title:
        title = questionary.text("Task title:").ask()
        if not title:
            raise typer.Abort()

    global_config = load_global_config()
    project_choices = [
        questionary.Choice(str(ref.path.name), value=str(ref.path))
        for ref in global_config.projects
    ]

    if len(project_choices) == 1:
        project_path = project_choices[0].value
    else:
        project_path = questionary.select(
            "Project:", choices=project_choices
        ).ask()
        if not project_path:
            raise typer.Abort()

    priority = questionary.select(
        "Priority:",
        choices=[
            questionary.Choice("high", value="high"),
            questionary.Choice("medium (default)", value="medium"),
            questionary.Choice("low", value="low"),
        ],
        default="medium (default)",
    ).ask() or "medium"

    intent = questionary.text("Description (intent):").ask()

    scope_raw = questionary.text("Scope (files, comma-separated, optional):").ask()
    scope = [s.strip() for s in scope_raw.split(",") if s.strip()] if scope_raw else []

    constraints_raw = questionary.text("Constraints (comma-separated, optional):").ask()
    constraints = [c.strip() for c in constraints_raw.split(",") if c.strip()] if constraints_raw else []

    task_id = slugify(title)[:60]

    task = QueuedTask(
        id=task_id,
        title=title,
        source_type="manual",
        project_path=project_path,
        priority=TaskPriority(priority),
        intent=intent or None,
        scope=scope,
        constraints=constraints,
    )
    add_task(task)
    console.print(f"[green]Added:[/green] {task.id}")


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


@tasks_app.command()
def remove(
    task_id: str = typer.Argument(..., help="Task ID to remove."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Remove a task from the queue."""
    task = get_task(task_id)
    if not task:
        console.print(f"[red]Task '{task_id}' not found.[/red]")
        raise typer.Exit(1)

    if not yes:
        confirm = questionary.confirm(
            f"Remove '{task.title}'?", default=False
        ).ask()
        if not confirm:
            raise typer.Abort()

    remove_task(task_id)
    console.print(f"[green]Removed:[/green] {task_id}")


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


@tasks_app.command()
def edit(
    task_id: str = typer.Argument(..., help="Task ID to edit."),
    title: Optional[str] = typer.Option(None, "--title"),
    intent: Optional[str] = typer.Option(None, "--intent"),
    priority: Optional[str] = typer.Option(None, "--priority"),
) -> None:
    """Edit a task's fields."""
    task = get_task(task_id)
    if not task:
        console.print(f"[red]Task '{task_id}' not found.[/red]")
        raise typer.Exit(1)

    fields: dict = {}

    if title is None and intent is None and priority is None:
        # Interactive mode
        new_title = questionary.text("Title:", default=task.title).ask()
        if new_title and new_title != task.title:
            fields["title"] = new_title

        new_intent = questionary.text("Intent:", default=task.intent or "").ask()
        if new_intent != (task.intent or ""):
            fields["intent"] = new_intent or None

        new_priority = questionary.select(
            "Priority:",
            choices=["high", "medium", "low"],
            default=task.priority,
        ).ask()
        if new_priority and new_priority != task.priority:
            fields["priority"] = TaskPriority(new_priority)
    else:
        if title is not None:
            fields["title"] = title
        if intent is not None:
            fields["intent"] = intent
        if priority is not None:
            fields["priority"] = TaskPriority(priority)

    if not fields:
        console.print("[dim]No changes.[/dim]")
        return

    update_task(task_id, **fields)
    console.print(f"[green]Updated:[/green] {task_id}")


# ---------------------------------------------------------------------------
# prioritize
# ---------------------------------------------------------------------------


@tasks_app.command()
def prioritize(
    task_id: str = typer.Argument(..., help="Task ID."),
    priority: str = typer.Argument(..., help="New priority: high, medium, low."),
) -> None:
    """Change a task's priority."""
    task = get_task(task_id)
    if not task:
        console.print(f"[red]Task '{task_id}' not found.[/red]")
        raise typer.Exit(1)

    update_task(task_id, priority=TaskPriority(priority))
    console.print(f"[green]{task_id}[/green] → {priority}")


# ---------------------------------------------------------------------------
# skip / requeue
# ---------------------------------------------------------------------------


@tasks_app.command()
def skip(
    task_id: str = typer.Argument(..., help="Task ID to skip."),
) -> None:
    """Mark a task as skipped."""
    task = get_task(task_id)
    if not task:
        console.print(f"[red]Task '{task_id}' not found.[/red]")
        raise typer.Exit(1)

    update_task(task_id, status=TaskStatus.SKIPPED)
    console.print(f"[yellow]Skipped:[/yellow] {task_id}")


@tasks_app.command()
def requeue(
    task_id: str = typer.Argument(..., help="Task ID to requeue."),
) -> None:
    """Move a task back to pending."""
    task = get_task(task_id)
    if not task:
        console.print(f"[red]Task '{task_id}' not found.[/red]")
        raise typer.Exit(1)

    update_task(task_id, status=TaskStatus.PENDING)
    console.print(f"[green]Requeued:[/green] {task_id}")


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


@tasks_app.command()
def history(
    task_id: str = typer.Argument(..., help="Task ID."),
) -> None:
    """Show execution history for a task."""
    task = get_task(task_id)
    if not task:
        console.print(f"[red]Task '{task_id}' not found.[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]{task.title}[/bold] ({task.id})")
    console.print(f"Status: {task.status} | Priority: {task.priority} | Attempts: {len(task.attempts)}")

    if not task.attempts:
        console.print("[dim]No execution attempts yet.[/dim]")
        return

    table = Table(show_header=True)
    table.add_column("When")
    table.add_column("Status")
    table.add_column("Branch")
    table.add_column("PR")
    table.add_column("Duration")
    table.add_column("Error", max_width=40)

    for a in task.attempts:
        status_str = (
            f"[green]{a.status}[/green]" if a.status == TaskStatus.PASSED
            else f"[red]{a.status}[/red]"
        )
        duration = f"{a.duration_seconds:.0f}s" if a.duration_seconds else "-"
        table.add_row(
            a.timestamp.strftime("%Y-%m-%d %H:%M"),
            status_str,
            a.branch or "-",
            a.pr_url or "-",
            duration,
            (a.error[:40] if a.error else "-"),
        )

    console.print(table)
