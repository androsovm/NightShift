"""Main orchestrator for NightShift nightly runs."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import structlog
from slugify import slugify

from nightshift.config.loader import load_project_config
from nightshift.executor.claude import build_prompt, invoke_claude
from nightshift.executor.git_ops import (
    cleanup_branch,
    create_branch,
    create_pr,
    prepare_repo,
    push_branch,
)
from nightshift.executor.quality_gates import run_all_gates, run_baseline_tests
from nightshift.models import (
    GlobalConfig,
    ProjectConfig,
    RunResult,
    Task,
    TaskPriority,
    TaskResult,
    TaskStatus,
)
from nightshift.sources import ADAPTERS

log = structlog.get_logger(__name__)

# Priority ordering: high first.
_PRIORITY_ORDER = {
    TaskPriority.HIGH: 0,
    TaskPriority.MEDIUM: 1,
    TaskPriority.LOW: 2,
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def execute_run(
    global_config: GlobalConfig,
    project_path: Path | None = None,
) -> RunResult:
    """Execute a full NightShift run.

    If *project_path* is given only that project is processed; otherwise all
    projects listed in *global_config* are processed.

    Respects ``global_config.schedule.max_duration_hours`` — stops accepting
    new tasks once the wall-clock limit is reached.
    """
    run_id = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_result = RunResult(run_id=run_id)
    max_duration_seconds = global_config.schedule.max_duration_hours * 3600
    run_start_time = time.monotonic()

    log.info("run_start", run_id=run_id, max_duration_hours=global_config.schedule.max_duration_hours)

    # Determine which projects to process.
    if project_path is not None:
        project_paths = [project_path]
    else:
        project_paths = [ref.path for ref in global_config.projects]

    prs_created = 0

    for proj_path in project_paths:
        proj_path = proj_path.resolve()
        log.info("project_start", project=str(proj_path))

        try:
            results = await _process_project(
                global_config, proj_path, run_id,
                run_start_time=run_start_time,
                max_duration_seconds=max_duration_seconds,
                prs_created=prs_created,
            )
            run_result.task_results.extend(results)
            prs_created += sum(
                1 for r in results
                if r.status == TaskStatus.PASSED and r.pr_url
            )
        except Exception:
            log.exception("project_error", project=str(proj_path))

    run_result.finished_at = datetime.now(tz=timezone.utc)
    log.info(
        "run_finished",
        run_id=run_id,
        total_tasks=len(run_result.task_results),
        passed=sum(1 for r in run_result.task_results if r.status == TaskStatus.PASSED),
        failed=sum(1 for r in run_result.task_results if r.status == TaskStatus.FAILED),
    )
    return run_result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _process_project(
    global_config: GlobalConfig,
    project_path: Path,
    run_id: str,
    *,
    run_start_time: float,
    max_duration_seconds: float,
    prs_created: int = 0,
) -> list[TaskResult]:
    """Handle a single project: collect tasks, execute them, return results."""
    project_config: ProjectConfig = load_project_config(project_path)
    limits = project_config.limits

    # 1. Prepare repository
    prepare_repo(project_path)

    # 2. Collect tasks from all configured sources
    tasks: list[Task] = []
    for source_config in project_config.sources:
        adapter_cls = ADAPTERS.get(source_config.type)
        if adapter_cls is None:
            log.warning("unknown_source_type", source_type=source_config.type)
            continue

        adapter = adapter_cls()
        try:
            fetched = await adapter.fetch_tasks(str(project_path), source_config)
            tasks.extend(fetched)
        except Exception:
            log.exception("fetch_tasks_error", source_type=source_config.type)

    if not tasks:
        log.info("no_tasks", project=str(project_path))
        return []

    # 3. Sort by priority (high > medium > low)
    tasks.sort(key=lambda t: _PRIORITY_ORDER.get(t.priority, 99))

    # 4. Limit to max_tasks_per_run
    tasks = tasks[: limits.max_tasks_per_run]

    log.info("tasks_collected", count=len(tasks), project=str(project_path))

    # 5. Execute each task
    results: list[TaskResult] = []

    for task in tasks:
        # Check wall-clock limit
        elapsed = time.monotonic() - run_start_time
        if elapsed > max_duration_seconds:
            log.warning(
                "max_duration_reached",
                elapsed_minutes=round(elapsed / 60, 1),
                max_hours=global_config.schedule.max_duration_hours,
                remaining_tasks=len(tasks) - len(results),
            )
            # Mark remaining tasks as skipped
            for remaining in tasks[len(results):]:
                results.append(TaskResult(
                    task_id=remaining.id,
                    task_title=remaining.title,
                    project_path=str(project_path),
                    status=TaskStatus.SKIPPED,
                    error="max_duration_hours limit reached",
                ))
            break

        # Check PR limit
        if prs_created >= global_config.max_prs_per_night:
            log.warning(
                "max_prs_reached",
                prs_created=prs_created,
                limit=global_config.max_prs_per_night,
            )
            for remaining in tasks[len(results):]:
                results.append(TaskResult(
                    task_id=remaining.id,
                    task_title=remaining.title,
                    project_path=str(project_path),
                    status=TaskStatus.SKIPPED,
                    error="max_prs_per_night limit reached",
                ))
            break

        task_result = await _execute_task(
            task=task,
            project_path=project_path,
            project_config=project_config,
            run_id=run_id,
        )
        results.append(task_result)

        if task_result.status == TaskStatus.PASSED and task_result.pr_url:
            prs_created += 1

        # Return to main between tasks.
        try:
            from nightshift.executor.git_ops import _run

            _run(["checkout", "main"], cwd=project_path)
        except Exception:
            log.exception("return_to_main_error")

    return results


async def _execute_task(
    task: Task,
    project_path: Path,
    project_config: ProjectConfig,
    run_id: str,
) -> TaskResult:
    """Execute a single task through the full pipeline."""
    start_time = time.monotonic()
    slug = slugify(task.title, max_length=50)
    branch: str | None = None
    log_dir = project_path / ".nightshift" / "logs" / run_id
    log_file = log_dir / f"{slug}.log"

    task_result = TaskResult(
        task_id=task.id,
        task_title=task.title,
        project_path=str(project_path),
        status=TaskStatus.FAILED,
    )

    try:
        # a. Create feature branch
        branch = create_branch(project_path, slug)
        task_result.branch = branch

        # b. Run baseline tests
        _baseline_ok, baseline_passed, baseline_failed = run_baseline_tests(
            project_path
        )

        # c. Invoke Claude
        prompt = build_prompt(task, project_config.claude_system_prompt)
        success, output = invoke_claude(
            project_path=project_path,
            prompt=prompt,
            timeout_minutes=project_config.limits.task_timeout_minutes,
            log_file=log_file,
        )
        task_result.log_file = str(log_file)

        if not success:
            task_result.status = TaskStatus.FAILED
            task_result.error = f"Claude invocation failed: {output[:500]}"
            cleanup_branch(project_path, branch)
            return task_result

        # d. Run quality gates
        from nightshift.executor.git_ops import get_diff_stats

        files_changed, lines_added, lines_removed = get_diff_stats(project_path)
        task_result.files_changed = files_changed
        task_result.lines_added = lines_added
        task_result.lines_removed = lines_removed

        gates_passed, gates_msg = run_all_gates(
            project_path,
            project_config.limits,
            baseline=(baseline_passed, baseline_failed),
        )

        if not gates_passed:
            task_result.status = TaskStatus.FAILED
            task_result.error = f"Quality gates failed:\n{gates_msg}"
            cleanup_branch(project_path, branch)
            return task_result

        # e. Push branch, create PR, mark done on source
        push_branch(project_path, branch)

        pr_title = f"[NightShift] {task.title}"
        pr_body = (
            f"Automated PR created by NightShift.\n\n"
            f"**Task:** {task.title}\n"
            f"**Source:** {task.source_type}\n"
            f"**Priority:** {task.priority}\n\n"
            f"---\n\n"
            f"### Quality Gates\n{gates_msg}\n"
        )
        pr_url, pr_number = create_pr(project_path, branch, pr_title, pr_body)
        task_result.pr_url = pr_url
        task_result.pr_number = pr_number
        task_result.status = TaskStatus.PASSED

        # Mark done on the source adapter.
        await _mark_task_done(task, pr_url, project_path)

        log.info(
            "task_passed",
            task_id=task.id,
            pr_url=pr_url,
            pr_number=pr_number,
        )

    except Exception as exc:
        log.exception("task_error", task_id=task.id)
        task_result.status = TaskStatus.FAILED
        task_result.error = str(exc)

        # Attempt cleanup on failure.
        if branch is not None:
            try:
                cleanup_branch(project_path, branch)
            except Exception:
                log.exception("cleanup_error", branch=branch)

    finally:
        task_result.duration_seconds = time.monotonic() - start_time

    return task_result


async def _mark_task_done(task: Task, pr_url: str, project_path: Path) -> None:
    """Call ``mark_done`` on the appropriate source adapter."""
    adapter_cls = ADAPTERS.get(task.source_type)
    if adapter_cls is None:
        return

    project_config = load_project_config(project_path)
    # Find the matching source config so the adapter is properly configured.
    for source_config in project_config.sources:
        if source_config.type == task.source_type:
            adapter = adapter_cls()
            try:
                await adapter.mark_done(task, pr_url)
            except Exception:
                log.exception("mark_done_error", task_id=task.id)
            break
