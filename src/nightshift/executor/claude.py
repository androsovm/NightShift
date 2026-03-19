"""Claude Code invocation for NightShift executor."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import structlog

from nightshift.models.task import Task

log = structlog.get_logger(__name__)

# Retryable error patterns (case-insensitive)
_RETRYABLE_PATTERNS = ("529", "overloaded", "rate limit", "connection", "ECONNRESET", "ETIMEDOUT")
_MAX_RETRIES = 3
_RETRY_DELAY_SECONDS = 30


def build_prompt(task: Task, system_prompt: str | None = None) -> str:
    """Assemble a prompt string from *task* fields and an optional system prompt."""
    parts: list[str] = []

    # System context for autonomous operation
    parts.append(
        "You are working autonomously as part of NightShift — an automated overnight "
        "task runner. There is no human to ask questions. You must complete the task "
        "fully on your own."
    )
    parts.append("")

    if system_prompt:
        parts.append(system_prompt.strip())
        parts.append("")

    parts.append(f"# Task: {task.title}")
    parts.append("")

    if task.intent:
        parts.append(f"## What to do\n{task.intent}")
        parts.append("")

    if task.scope:
        parts.append("## Scope (files to touch)")
        for item in task.scope:
            parts.append(f"- {item}")
        parts.append("")

    if task.constraints:
        parts.append("## Constraints")
        for item in task.constraints:
            parts.append(f"- {item}")
        parts.append("")

    parts.append("## Instructions")
    parts.append(
        "1. Read the relevant source files to understand the current code.\n"
        "2. Implement the changes described above.\n"
        "3. If the task asks for tests, run them with `pytest` to verify they pass.\n"
        "4. Run `ruff check` on any files you changed and fix any issues.\n"
        "5. Commit your work with a clear, descriptive commit message.\n"
        "6. Do NOT create pull requests or push — that is handled externally.\n"
        "7. Do NOT ask questions — make reasonable decisions and proceed."
    )

    return "\n".join(parts)


def _is_retryable(output: str) -> bool:
    """Check if the error output indicates a transient/retryable failure."""
    lower = output.lower()
    return any(pattern.lower() in lower for pattern in _RETRYABLE_PATTERNS)


def invoke_claude(
    project_path: Path,
    prompt: str,
    timeout_minutes: int,
    log_file: Path,
) -> tuple[bool, str]:
    """Run ``claude`` CLI in *project_path* with the given *prompt*.

    Retries up to 3 times on transient errors (API overload, connection issues).
    Stdout and stderr are captured and written to *log_file*.
    Returns ``(success, output)``.
    """
    log.info(
        "invoke_claude",
        project=str(project_path),
        timeout_minutes=timeout_minutes,
        log_file=str(log_file),
    )

    timeout_seconds = timeout_minutes * 60
    log_file.parent.mkdir(parents=True, exist_ok=True)
    last_output = ""

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            result = subprocess.run(
                [
                    "claude",
                    "-p",
                    prompt,
                    "--dangerously-skip-permissions",
                ],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )

            output = result.stdout
            if result.stderr:
                output += "\n--- STDERR ---\n" + result.stderr

            last_output = output

            if result.returncode == 0:
                log_file.write_text(output, encoding="utf-8")
                log.info("claude_success", attempt=attempt)
                return True, output

            # Non-zero exit — check if retryable
            if attempt < _MAX_RETRIES and _is_retryable(output):
                log.warning(
                    "claude_retryable_error",
                    attempt=attempt,
                    max_retries=_MAX_RETRIES,
                    delay=_RETRY_DELAY_SECONDS,
                    snippet=output[:200],
                )
                time.sleep(_RETRY_DELAY_SECONDS)
                continue

            # Non-retryable failure or last attempt
            log.warning(
                "claude_nonzero_exit",
                returncode=result.returncode,
                attempt=attempt,
                stderr=result.stderr[:500],
            )
            log_file.write_text(output, encoding="utf-8")
            return False, output

        except subprocess.TimeoutExpired:
            msg = f"Claude timed out after {timeout_minutes} minutes (attempt {attempt}/{_MAX_RETRIES})"
            log.error("claude_timeout", timeout_minutes=timeout_minutes, attempt=attempt)
            last_output = msg
            # Timeouts are not retryable — task is genuinely too slow
            log_file.write_text(msg, encoding="utf-8")
            return False, msg

        except FileNotFoundError:
            msg = "claude CLI not found on PATH"
            log.error("claude_not_found")
            log_file.write_text(msg, encoding="utf-8")
            return False, msg

    # All retries exhausted
    log.error("claude_all_retries_exhausted", max_retries=_MAX_RETRIES)
    log_file.write_text(last_output, encoding="utf-8")
    return False, last_output
