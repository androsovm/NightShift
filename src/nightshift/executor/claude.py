"""Claude Code invocation for NightShift executor."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import structlog

from nightshift.models.task import Task

log = structlog.get_logger(__name__)

# Retryable error patterns (case-insensitive)
_RETRYABLE_PATTERNS = ("529", "overloaded", "rate limit", "connection", "ECONNRESET", "ETIMEDOUT")
_MAX_RETRIES = 3
_RETRY_DELAY_SECONDS = 30


@dataclass(slots=True)
class ClaudeInvocationResult:
    """Structured result for a single Claude Code invocation."""

    success: bool
    output: str
    cost_usd: float | None = None
    duration_ms: int | None = None
    duration_api_ms: int | None = None
    num_turns: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None

    def metadata_lines(self) -> list[str]:
        lines: list[str] = []
        if self.cost_usd is not None:
            lines.append(f"total_cost_usd={self.cost_usd:.6f}")
        if self.duration_ms is not None:
            lines.append(f"duration_ms={self.duration_ms}")
        if self.duration_api_ms is not None:
            lines.append(f"duration_api_ms={self.duration_api_ms}")
        if self.num_turns is not None:
            lines.append(f"num_turns={self.num_turns}")
        if self.input_tokens is not None:
            lines.append(f"input_tokens={self.input_tokens}")
        if self.output_tokens is not None:
            lines.append(f"output_tokens={self.output_tokens}")
        if self.cache_creation_tokens is not None:
            lines.append(f"cache_creation_tokens={self.cache_creation_tokens}")
        if self.cache_read_tokens is not None:
            lines.append(f"cache_read_tokens={self.cache_read_tokens}")
        return lines


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

    # Docs-only tasks don't need linting or testing steps
    touches_code = not task.scope or any(
        not s.endswith(".md") for s in task.scope
    )

    steps: list[str] = [
        "1. Read the relevant source files to understand the current code.",
        "2. Implement the changes described above.",
    ]
    if touches_code:
        steps.append(
            "3. If the task asks for tests, run them with `pytest` to verify they pass."
        )
        steps.append(
            "4. Run `ruff check` on any files you changed and fix any issues."
        )
        steps.append(
            "5. If you created or modified database migrations (e.g. Alembic), verify them:\n"
            "   a. Apply: `alembic upgrade head` — confirm it succeeds.\n"
            "   b. Rollback: `alembic downgrade -1` — confirm the downgrade works."
        )
    steps.append(f"{len(steps) + 1}. Commit your work with a clear, descriptive commit message.")
    steps.append(f"{len(steps) + 1}. Do NOT create pull requests or push — that is handled externally.")
    steps.append(f"{len(steps) + 1}. Do NOT ask questions — make reasonable decisions and proceed.")

    parts.append("\n".join(steps))

    return "\n".join(parts)


def _is_retryable(output: str) -> bool:
    """Check if the error output indicates a transient/retryable failure."""
    lower = output.lower()
    return any(pattern.lower() in lower for pattern in _RETRYABLE_PATTERNS)


def _maybe_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _maybe_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_usage(payload: dict[str, object]) -> dict[str, object]:
    usage = payload.get("usage")
    if isinstance(usage, dict):
        return usage

    for key in ("message", "result"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            nested_usage = nested.get("usage")
            if isinstance(nested_usage, dict):
                return nested_usage

    return {}


def _extract_payload(stdout: str) -> dict[str, object] | None:
    if not stdout.strip():
        return None

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None

    if isinstance(payload, dict):
        return payload

    if isinstance(payload, list):
        for item in reversed(payload):
            if isinstance(item, dict) and item.get("type") == "result":
                return item
        for item in reversed(payload):
            if isinstance(item, dict):
                return item

    return None


def _parse_invocation(stdout: str) -> ClaudeInvocationResult | None:
    payload = _extract_payload(stdout)
    if payload is None:
        return None

    usage = _extract_usage(payload)
    result_text = payload.get("result")
    output = result_text.strip() if isinstance(result_text, str) else stdout.strip()

    return ClaudeInvocationResult(
        success=True,
        output=output,
        cost_usd=_maybe_float(payload.get("total_cost_usd") or payload.get("cost_usd")),
        duration_ms=_maybe_int(payload.get("duration_ms")),
        duration_api_ms=_maybe_int(payload.get("duration_api_ms")),
        num_turns=_maybe_int(payload.get("num_turns")),
        input_tokens=_maybe_int(usage.get("input_tokens")),
        output_tokens=_maybe_int(usage.get("output_tokens")),
        cache_creation_tokens=_maybe_int(
            usage.get("cache_creation_input_tokens") or usage.get("cache_creation_tokens")
        ),
        cache_read_tokens=_maybe_int(
            usage.get("cache_read_input_tokens") or usage.get("cache_read_tokens")
        ),
    )


def _combine_output(stdout: str, stderr: str) -> str:
    parts: list[str] = []
    if stdout.strip():
        parts.append(stdout.strip())
    if stderr.strip():
        parts.append(f"--- STDERR ---\n{stderr.strip()}")
    return "\n\n".join(parts)


def _build_log_output(
    result_text: str,
    invocation: ClaudeInvocationResult,
    stderr: str,
) -> str:
    parts: list[str] = []
    if result_text.strip():
        parts.append(result_text.strip())

    metadata = invocation.metadata_lines()
    if metadata:
        parts.append("--- CLAUDE METADATA ---\n" + "\n".join(metadata))

    if stderr.strip():
        parts.append(f"--- STDERR ---\n{stderr.strip()}")

    return "\n\n".join(parts)


def invoke_claude(
    project_path: Path,
    prompt: str,
    timeout_minutes: int,
    log_file: Path,
    model: str | None = None,
) -> ClaudeInvocationResult:
    """Run ``claude`` CLI in *project_path* with the given *prompt*.

    Retries up to 3 times on transient errors (API overload, connection issues).
    Stdout and stderr are captured and written to *log_file*.
    Returns a structured result containing the text output plus any usage data
    exposed by Claude Code's JSON output mode.
    """
    log.info(
        "invoke_claude",
        project=str(project_path),
        timeout_minutes=timeout_minutes,
        log_file=str(log_file),
        model=model,
    )

    timeout_seconds = timeout_minutes * 60
    log_file.parent.mkdir(parents=True, exist_ok=True)
    last_output = ""

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            cmd = [
                "claude",
                "-p",
                prompt,
                "--dangerously-skip-permissions",
                "--output-format",
                "json",
            ]
            if model:
                cmd.extend(["--model", model])

            result = subprocess.run(
                cmd,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )

            parsed = _parse_invocation(result.stdout)
            if parsed is None:
                invocation = ClaudeInvocationResult(
                    success=result.returncode == 0,
                    output=_combine_output(result.stdout, result.stderr),
                )
                log_output = invocation.output
            else:
                log_output = _build_log_output(parsed.output, parsed, result.stderr)
                parsed.success = result.returncode == 0
                parsed.output = (
                    parsed.output
                    if result.returncode == 0
                    else _combine_output(parsed.output or result.stdout, result.stderr)
                )
                invocation = parsed

            last_output = log_output

            if result.returncode == 0:
                log_file.write_text(log_output, encoding="utf-8")
                log.info(
                    "claude_success",
                    attempt=attempt,
                    total_cost_usd=invocation.cost_usd,
                    duration_ms=invocation.duration_ms,
                    num_turns=invocation.num_turns,
                )
                return invocation

            # Non-zero exit — check if retryable
            if attempt < _MAX_RETRIES and _is_retryable(invocation.output):
                log.warning(
                    "claude_retryable_error",
                    attempt=attempt,
                    max_retries=_MAX_RETRIES,
                    delay=_RETRY_DELAY_SECONDS,
                    snippet=invocation.output[:200],
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
            log_file.write_text(log_output, encoding="utf-8")
            return invocation

        except subprocess.TimeoutExpired:
            msg = f"Claude timed out after {timeout_minutes} minutes (attempt {attempt}/{_MAX_RETRIES})"
            log.error("claude_timeout", timeout_minutes=timeout_minutes, attempt=attempt)
            last_output = msg
            # Timeouts are not retryable — task is genuinely too slow
            log_file.write_text(msg, encoding="utf-8")
            return ClaudeInvocationResult(success=False, output=msg)

        except FileNotFoundError:
            msg = "claude CLI not found on PATH"
            log.error("claude_not_found")
            log_file.write_text(msg, encoding="utf-8")
            return ClaudeInvocationResult(success=False, output=msg)

    # All retries exhausted
    log.error("claude_all_retries_exhausted", max_retries=_MAX_RETRIES)
    log_file.write_text(last_output, encoding="utf-8")
    return ClaudeInvocationResult(success=False, output=last_output)
