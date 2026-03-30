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
    autofix_and_commit,
    checkout_pr_branch,
    cleanup_branch,
    comment_on_pr,
    create_branch,
    create_pr,
    get_diff_stats,
    get_pr_url,
    prepare_repo,
    push_branch,
    run_cmd,
)
from nightshift.executor.quality_gates import run_all_gates, run_baseline_tests
from nightshift.models import (
    GlobalConfig,
    ProjectConfig,
    QueuedTask,
    RunResult,
    Task,
    TaskAttempt,
    TaskPriority,
    TaskResult,
    TaskStatus,
)
from nightshift.storage.task_queue import clear_run_pid, get_pending_tasks, record_attempt, update_task, write_run_pid

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
    task_ids: list[str] | None = None,
) -> RunResult:
    """Execute a full NightShift run from the local task queue.

    If *project_path* is given only tasks for that project are processed;
    otherwise all pending tasks across all projects are processed.

    Respects ``global_config.schedule.max_duration_hours`` — stops accepting
    new tasks once the wall-clock limit is reached.
    """
    run_id = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_result = RunResult(run_id=run_id)
    max_duration_seconds = global_config.schedule.max_duration_hours * 3600
    run_start_time = time.monotonic()

    write_run_pid()
    log.info("run_start", run_id=run_id, max_duration_hours=global_config.schedule.max_duration_hours)

    # Load pending tasks from the local queue.
    project_filter = str(project_path.resolve()) if project_path else None
    pending = get_pending_tasks(project_path=project_filter)

    # Narrow to specific tasks when requested (e.g. TUI "run selected").
    if task_ids is not None:
        allowed = set(task_ids)
        pending = [t for t in pending if t.id in allowed]

    if not pending:
        log.info("no_pending_tasks")
        return run_result

    # Group by project_path (preserving priority order within each group).
    projects: dict[str, list[QueuedTask]] = {}
    for qt in pending:
        projects.setdefault(qt.project_path, []).append(qt)

    prs_created = 0

    for proj_path_str, queued_tasks in projects.items():
        proj_path = Path(proj_path_str).resolve()
        log.info("project_start", project=str(proj_path))

        try:
            results = await _process_project(
                global_config, proj_path, run_id,
                queued_tasks=queued_tasks,
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
    clear_run_pid()
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
    queued_tasks: list[QueuedTask],
    run_start_time: float,
    max_duration_seconds: float,
    prs_created: int = 0,
) -> list[TaskResult]:
    """Handle a single project: execute queued tasks, return results."""
    project_config: ProjectConfig = load_project_config(project_path)
    limits = project_config.limits

    # 1. Prepare repository
    prepare_repo(project_path)

    # 2. Apply max_tasks_per_run limit
    tasks = queued_tasks[: limits.max_tasks_per_run]

    log.info("tasks_from_queue", count=len(tasks), project=str(project_path))

    # 3. Execute each task
    results: list[TaskResult] = []

    for qt in tasks:
        # Check wall-clock limit
        elapsed = time.monotonic() - run_start_time
        if elapsed > max_duration_seconds:
            log.warning(
                "max_duration_reached",
                elapsed_minutes=round(elapsed / 60, 1),
                max_hours=global_config.schedule.max_duration_hours,
                remaining_tasks=len(tasks) - len(results),
            )
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

        # Mark as running in the queue file so status is accurate on disk.
        update_task(qt.id, status=TaskStatus.RUNNING)

        task = qt.to_task()
        task_result = await _execute_task(
            task=task,
            project_path=project_path,
            project_config=project_config,
            run_id=run_id,
        )
        results.append(task_result)

        # Record attempt in the local queue.
        attempt = TaskAttempt(
            timestamp=datetime.now(tz=timezone.utc),
            status=task_result.status,
            run_id=run_id,
            branch=task_result.branch,
            pr_url=task_result.pr_url,
            error=task_result.error,
            duration_seconds=task_result.duration_seconds,
        )
        record_attempt(qt.id, attempt)

        if task_result.status == TaskStatus.PASSED and task_result.pr_url:
            prs_created += 1

        # Return to main between tasks.
        try:
            run_cmd(["checkout", "main"], cwd=project_path)
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

    branch_reused = False

    try:
        # a. Create or checkout branch
        if task.pr_branch:
            checkout_pr_branch(project_path, task.pr_branch)
            branch = task.pr_branch
        else:
            branch, branch_reused = create_branch(project_path, slug)
        task_result.branch = branch

        # b. Run baseline tests
        _baseline_ok, baseline_passed, baseline_failed = run_baseline_tests(
            project_path
        )

        # c. Invoke Claude
        prompt = build_prompt(task, project_config.claude_system_prompt)
        model = task.model or project_config.default_model
        task_result.model = model
        invocation = invoke_claude(
            project_path=project_path,
            prompt=prompt,
            timeout_minutes=project_config.limits.task_timeout_minutes,
            log_file=log_file,
            model=model,
        )
        task_result.log_file = str(log_file)
        task_result.claude_cost_usd = invocation.cost_usd
        task_result.claude_duration_ms = invocation.duration_ms
        task_result.claude_api_duration_ms = invocation.duration_api_ms
        task_result.claude_num_turns = invocation.num_turns
        task_result.claude_input_tokens = invocation.input_tokens
        task_result.claude_output_tokens = invocation.output_tokens
        task_result.claude_cache_creation_tokens = invocation.cache_creation_tokens
        task_result.claude_cache_read_tokens = invocation.cache_read_tokens

        if not invocation.success:
            task_result.status = TaskStatus.FAILED
            task_result.error = f"Claude invocation failed: {invocation.output[:500]}"
            cleanup_branch(project_path, branch)
            return task_result

        # d. Auto-fix trivial lint issues before quality gates
        autofix_and_commit(project_path)

        # e. Run quality gates
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

        # f. Push branch and create/update PR
        push_branch(project_path, branch, force_with_lease=branch_reused)

        if task.pr_number:
            # Review task — comment on existing PR
            comment_on_pr(
                project_path,
                task.pr_number,
                f"Addressed review feedback.\n\n### Quality Gates\n{gates_msg}",
            )
            pr_url = get_pr_url(project_path, task.pr_number)
            pr_number = task.pr_number
        else:
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
