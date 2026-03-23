"""Quality gate checks for NightShift executor."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import structlog

from nightshift.executor.git_ops import get_changed_files, get_diff_stats
from nightshift.models.config import ProjectLimits

log = structlog.get_logger(__name__)

_PYTEST_TIMEOUT = 300  # 5 minutes max for test suite
_LINTER_TIMEOUT = 60   # 1 minute max for linter


# ---------------------------------------------------------------------------
# Individual gates
# ---------------------------------------------------------------------------


def check_blast_radius(
    project_path: Path,
    max_files: int,
    max_lines: int,
) -> tuple[bool, str]:
    """Check that the diff does not exceed size limits.

    Returns ``(passed, message)``.
    """
    files_changed, lines_added, lines_removed = get_diff_stats(project_path)
    total_lines = lines_added + lines_removed

    violations: list[str] = []
    if files_changed > max_files:
        violations.append(
            f"files changed ({files_changed}) exceeds limit ({max_files})"
        )
    if total_lines > max_lines:
        violations.append(
            f"total lines changed ({total_lines}) exceeds limit ({max_lines})"
        )

    if violations:
        msg = "Blast-radius exceeded: " + "; ".join(violations)
        log.warning("blast_radius_fail", msg=msg)
        return False, msg

    msg = (
        f"Blast-radius OK: {files_changed} files, "
        f"+{lines_added}/-{lines_removed} lines"
    )
    log.info("blast_radius_ok", files=files_changed, added=lines_added, removed=lines_removed)
    return True, msg


def run_baseline_tests(project_path: Path) -> tuple[bool, int, int]:
    """Run ``pytest --tb=short -q`` and return ``(success, passed, failed)``.

    If pytest is not installed the gate is skipped (returns ``(True, 0, 0)``).
    """
    if not shutil.which("pytest"):
        log.warning("pytest_not_found")
        return True, 0, 0

    try:
        result = subprocess.run(
            ["pytest", "--tb=short", "-q"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=_PYTEST_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.error("baseline_tests_timeout", timeout=_PYTEST_TIMEOUT)
        return False, 0, 0

    passed, failed = _parse_pytest_summary(result.stdout)
    success = result.returncode == 0
    log.info("baseline_tests", success=success, passed=passed, failed=failed)
    return success, passed, failed


def run_linter(project_path: Path) -> tuple[bool, str]:
    """Auto-detect and run a linter on changed files only.

    Only files changed between ``main`` and ``HEAD`` are checked, so
    pre-existing linter errors in untouched files do not block the run.

    Returns ``(passed, output)``.
    """
    changed = get_changed_files(project_path)
    if not changed:
        log.info("linter_skip_no_changes")
        return True, "No changed files to lint."

    # Try linters in preference order.
    for linter, base_args in [
        ("ruff", ["ruff", "check"]),
        ("flake8", ["flake8"]),
        ("eslint", ["npx", "eslint"]),
    ]:
        if linter == "eslint":
            eslint_configs = list(project_path.glob(".eslintrc*")) + list(
                project_path.glob("eslint.config.*")
            )
            if not eslint_configs:
                continue
        else:
            if not shutil.which(linter):
                continue

        # Filter to changed files that still exist and match the linter's language.
        if linter in ("ruff", "flake8"):
            targets = [f for f in changed if f.endswith(".py") and (project_path / f).exists()]
        else:
            targets = [
                f for f in changed
                if f.endswith((".js", ".jsx", ".ts", ".tsx")) and (project_path / f).exists()
            ]

        if not targets:
            log.info("linter_skip_no_matching_files", linter=linter)
            return True, f"No changed files for {linter} to check."

        cmd = base_args + targets
        log.info("run_linter", linter=linter, files=len(targets))
        try:
            result = subprocess.run(
                cmd,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=_LINTER_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            log.error("linter_timeout", linter=linter, timeout=_LINTER_TIMEOUT)
            return False, f"{linter} timed out after {_LINTER_TIMEOUT}s"
        output = (result.stdout + "\n" + result.stderr).strip()
        passed = result.returncode == 0
        if not passed:
            log.warning("linter_fail", linter=linter, snippet=output[:500])
        return passed, output

    # No linter found – pass by default.
    log.info("no_linter_found")
    return True, "No linter detected; skipped."


def run_tests_vs_baseline(
    project_path: Path,
    baseline_passed: int,
    baseline_failed: int,
) -> tuple[bool, str]:
    """Run the test suite again and compare against the baseline.

    A regression is defined as:
    - fewer tests passing than before, **or**
    - more tests failing than before.

    Returns ``(passed, message)``.
    """
    try:
        result = subprocess.run(
            ["pytest", "--tb=short", "-q"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=_PYTEST_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.error("tests_vs_baseline_timeout", timeout=_PYTEST_TIMEOUT)
        return False, f"pytest timed out after {_PYTEST_TIMEOUT}s"

    current_passed, current_failed = _parse_pytest_summary(result.stdout)

    regressions: list[str] = []
    if current_passed < baseline_passed:
        regressions.append(
            f"passing tests decreased ({baseline_passed} -> {current_passed})"
        )
    if current_failed > baseline_failed:
        regressions.append(
            f"failing tests increased ({baseline_failed} -> {current_failed})"
        )

    if regressions:
        msg = "Test regression: " + "; ".join(regressions)
        log.warning("test_regression", msg=msg)
        return False, msg

    msg = f"Tests OK: {current_passed} passed, {current_failed} failed (baseline: {baseline_passed}/{baseline_failed})"
    log.info("tests_vs_baseline_ok", passed=current_passed, failed=current_failed)
    return True, msg


# ---------------------------------------------------------------------------
# Aggregate gate runner
# ---------------------------------------------------------------------------


def run_all_gates(
    project_path: Path,
    limits: ProjectLimits,
    baseline: tuple[int, int],
) -> tuple[bool, str]:
    """Run every quality gate in order.

    *baseline* is ``(baseline_passed, baseline_failed)`` from before the change.

    Returns ``(all_passed, combined_message)``.
    """
    messages: list[str] = []
    all_passed = True

    # 1. Blast radius
    ok, msg = check_blast_radius(
        project_path,
        max_files=limits.max_files_changed,
        max_lines=limits.max_lines_changed,
    )
    messages.append(msg)
    if not ok:
        all_passed = False

    # 2. Linter
    ok, msg = run_linter(project_path)
    messages.append(f"Linter: {msg[:300]}")
    if not ok:
        all_passed = False

    # 3. Test regression
    baseline_passed, baseline_failed = baseline
    if baseline_passed > 0 or baseline_failed > 0:
        ok, msg = run_tests_vs_baseline(
            project_path, baseline_passed, baseline_failed
        )
        messages.append(msg)
        if not ok:
            all_passed = False

    combined = "\n".join(messages)
    return all_passed, combined


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_PYTEST_SUMMARY_RE = re.compile(
    r"(\d+)\s+passed(?:.*?(\d+)\s+failed)?",
)


def _parse_pytest_summary(output: str) -> tuple[int, int]:
    """Extract (passed, failed) counts from pytest ``-q`` output."""
    for line in reversed(output.splitlines()):
        m = _PYTEST_SUMMARY_RE.search(line)
        if m:
            passed = int(m.group(1))
            failed = int(m.group(2)) if m.group(2) else 0
            return passed, failed
    return 0, 0
