"""nightshift sync -- import tasks from sources into the local queue."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import questionary
import structlog
import typer
from rich.console import Console

from nightshift.config.loader import load_global_config, load_project_config
from nightshift.models.task import QueuedTask, TaskStatus
from nightshift.sources import ADAPTERS
from nightshift.sources.github_reviews import check_approved_prs, fetch_review_tasks
from nightshift.sources.github_source import GitHubSource
from nightshift.storage.task_queue import (
    add_task,
    find_by_source_ref,
    load_tasks,
    update_task,
)

console = Console()
log = structlog.get_logger(__name__)


def _content_changed(existing: QueuedTask, new: QueuedTask) -> bool:
    """Check if meaningful fields differ between existing and newly fetched task."""
    return (
        existing.title != new.title
        or existing.intent != new.intent
        or existing.scope != new.scope
        or existing.constraints != new.constraints
        or existing.priority != new.priority
    )


async def _mark_approved(pr_number: int, pr_url: str) -> int:
    """Mark all tasks related to an approved PR as DONE.

    Returns the number of tasks marked done.
    """
    tasks = load_tasks()
    done_count = 0

    for task in tasks:
        if task.status not in (TaskStatus.PASSED, TaskStatus.PENDING):
            continue

        # Match review tasks by pr_number field
        is_review = task.pr_number == pr_number
        # Match original tasks by pr_url in their attempts
        is_original = any(
            a.pr_url and a.pr_url == pr_url
            for a in task.attempts
        )

        if not (is_review or is_original):
            continue

        update_task(task.id, status=TaskStatus.DONE)
        console.print(f"  [green]done[/green] {task.title} (PR #{pr_number} approved)")
        done_count += 1

        # Call source adapter mark_done for the original task (not review tasks)
        if is_original and task.source_type != "github_review":
            adapter_cls = ADAPTERS.get(task.source_type)
            if adapter_cls:
                try:
                    adapter = adapter_cls()
                    await adapter.mark_done(task.to_task(), pr_url)
                except Exception as exc:
                    log.warning(
                        "mark_done_error",
                        task_id=task.id,
                        source_type=task.source_type,
                        error=str(exc),
                    )

    return done_count


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

    # ------------------------------------------------------------------
    # Phase 2: Scan open NightShift PRs for review feedback & approvals
    # ------------------------------------------------------------------
    reviews_added = 0
    done_count = 0
    scanned_repos: set[str] = set()

    for proj_path in project_paths:
        proj_path = proj_path.resolve()

        # Detect GitHub repo from git remote (works regardless of source type)
        repo = GitHubSource._detect_repo_from(proj_path)
        if not repo or repo in scanned_repos:
            continue
        scanned_repos.add(repo)

        console.print(f"\n[bold]Scanning PR reviews for [cyan]{repo}[/cyan][/bold]")

        # 1. Fetch review tasks for PRs with unaddressed feedback
        try:
            review_tasks = await fetch_review_tasks(str(proj_path), repo)
        except Exception as exc:
            console.print(f"  [red]Error scanning PR reviews: {exc}[/red]")
            continue

        for task in review_tasks:
            existing = find_by_source_ref("github_review", task.source_ref)
            if existing is None:
                queued = QueuedTask.from_task(task)
                add_task(queued)
                console.print(f"  [yellow]review[/yellow] {task.title}")
                reviews_added += 1

        # 2. Check for approved PRs → mark tasks DONE
        try:
            approved = await check_approved_prs(repo)
        except Exception as exc:
            console.print(f"  [red]Error checking PR approvals: {exc}[/red]")
            continue

        for pr_number, pr_url in approved:
            done_count += await _mark_approved(pr_number, pr_url)

    parts = [f"{added} added", f"{updated} updated", f"{skipped} skipped"]
    if reviews_added:
        parts.append(f"{reviews_added} review tasks")
    if done_count:
        parts.append(f"{done_count} done (approved)")
    console.print(f"\n[bold]Sync complete:[/bold] {', '.join(parts)}")


def sync(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Sync only one project."),
) -> None:
    """Import tasks from configured sources into the local queue."""
    asyncio.run(_do_sync(project))
