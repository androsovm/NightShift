"""nightshift sync -- import tasks from sources into the local queue."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import questionary
import typer
from rich.console import Console

from nightshift.config.loader import load_global_config, load_project_config
from nightshift.models.task import QueuedTask
from nightshift.sources import ADAPTERS
from nightshift.storage.task_queue import add_task, find_by_source_ref

console = Console()


def _content_changed(existing: QueuedTask, new: QueuedTask) -> bool:
    """Check if meaningful fields differ between existing and newly fetched task."""
    return (
        existing.title != new.title
        or existing.intent != new.intent
        or existing.scope != new.scope
        or existing.constraints != new.constraints
        or existing.priority != new.priority
    )


async def _do_sync(project_filter: str | None) -> None:
    global_config = load_global_config()

    project_paths = [ref.path for ref in global_config.projects]
    if project_filter:
        project_paths = [
            p for p in project_paths
            if p.name == project_filter or str(p) == project_filter
        ]
        if not project_paths:
            console.print(f"[red]Project '{project_filter}' not found in config.[/red]")
            raise typer.Exit(1)

    added = 0
    skipped = 0
    updated = 0

    for proj_path in project_paths:
        proj_path = proj_path.resolve()
        project_config = load_project_config(proj_path)

        console.print(f"\n[bold]Syncing [cyan]{proj_path.name}[/cyan][/bold]")

        for source_config in project_config.sources:
            adapter_cls = ADAPTERS.get(source_config.type)
            if adapter_cls is None:
                console.print(f"  [yellow]Unknown source type: {source_config.type}[/yellow]")
                continue

            adapter = adapter_cls()
            try:
                tasks = await adapter.fetch_tasks(str(proj_path), source_config)
            except Exception as exc:
                console.print(f"  [red]Error fetching from {source_config.type}: {exc}[/red]")
                continue

            for task in tasks:
                queued = QueuedTask.from_task(task)
                existing = (
                    find_by_source_ref(task.source_type, task.source_ref)
                    if task.source_ref
                    else None
                )

                if existing is None:
                    add_task(queued)
                    console.print(f"  [green]+[/green] {task.title}")
                    added += 1
                elif not _content_changed(existing, queued):
                    skipped += 1
                else:
                    # Content changed — ask user
                    console.print(f"  [yellow]Changed:[/yellow] {task.title}")
                    action = questionary.select(
                        f"  Task '{task.title}' already exists but has changed. What to do?",
                        choices=[
                            questionary.Choice("Skip (keep existing)", value="skip"),
                            questionary.Choice("Update (overwrite fields)", value="update"),
                            questionary.Choice("Add as duplicate", value="duplicate"),
                        ],
                    ).ask()

                    if action == "update":
                        from nightshift.storage.task_queue import update_task
                        update_task(
                            existing.id,
                            title=queued.title,
                            intent=queued.intent,
                            scope=queued.scope,
                            constraints=queued.constraints,
                            priority=queued.priority,
                        )
                        updated += 1
                    elif action == "duplicate":
                        queued.id = f"{queued.id}-dup"
                        add_task(queued)
                        added += 1
                    else:
                        skipped += 1

    console.print(f"\n[bold]Sync complete:[/bold] {added} added, {updated} updated, {skipped} skipped")


def sync(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Sync only one project."),
) -> None:
    """Import tasks from configured sources into the local queue."""
    asyncio.run(_do_sync(project))
