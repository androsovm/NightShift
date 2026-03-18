"""Claude Code invocation for NightShift executor."""

from __future__ import annotations

import subprocess
from pathlib import Path

import structlog

from nightshift.models.task import Task

log = structlog.get_logger(__name__)


def build_prompt(task: Task, system_prompt: str | None = None) -> str:
    """Assemble a prompt string from *task* fields and an optional system prompt."""
    parts: list[str] = []

    if system_prompt:
        parts.append(system_prompt.strip())
        parts.append("")  # blank separator

    parts.append(f"# Task: {task.title}")
    parts.append("")

    if task.intent:
        parts.append(f"**Intent:** {task.intent}")
        parts.append("")

    if task.scope:
        parts.append("**Scope (files / areas to touch):**")
        for item in task.scope:
            parts.append(f"- {item}")
        parts.append("")

    if task.constraints:
        parts.append("**Constraints:**")
        for item in task.constraints:
            parts.append(f"- {item}")
        parts.append("")

    parts.append(
        "Implement the changes described above. "
        "Write clean, well-tested code. "
        "Commit your work with a clear commit message."
    )

    return "\n".join(parts)


def invoke_claude(
    project_path: Path,
    prompt: str,
    timeout_minutes: int,
    log_file: Path,
) -> tuple[bool, str]:
    """Run ``claude`` CLI in *project_path* with the given *prompt*.

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

        # Persist full log.
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(output, encoding="utf-8")

        success = result.returncode == 0
        if not success:
            log.warning(
                "claude_nonzero_exit",
                returncode=result.returncode,
                stderr=result.stderr[:500],
            )

        return success, output

    except subprocess.TimeoutExpired:
        msg = f"Claude timed out after {timeout_minutes} minutes"
        log.error("claude_timeout", timeout_minutes=timeout_minutes)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(msg, encoding="utf-8")
        return False, msg

    except FileNotFoundError:
        msg = "claude CLI not found on PATH"
        log.error("claude_not_found")
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(msg, encoding="utf-8")
        return False, msg
