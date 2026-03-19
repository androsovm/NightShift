"""Git operations for NightShift executor."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

# Every git command goes through this base to disable GPG signing.
_GIT_BASE = ["git", "-c", "commit.gpgsign=false"]


_GIT_TIMEOUT = 120  # seconds — prevent hanging on network issues
_GH_TIMEOUT = 60

def _run(
    args: list[str],
    cwd: Path,
    *,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command, logging it first."""
    cmd = _GIT_BASE + args if args[0] != "gh" else args
    timeout = _GH_TIMEOUT if args[0] == "gh" else _GIT_TIMEOUT
    log.debug("git_ops.run", cmd=" ".join(cmd), cwd=str(cwd))
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        capture_output=capture,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def prepare_repo(project_path: Path) -> None:
    """Fetch origin, checkout main, pull latest changes.

    Network failures on fetch/pull are logged but do not abort — the run
    continues with whatever local state is available.
    """
    log.info("prepare_repo", project=str(project_path))
    try:
        _run(["fetch", "origin"], cwd=project_path)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.warning("prepare_repo.fetch_failed", error=str(exc))

    # checkout main is mandatory — if this fails, the project is broken
    _run(["checkout", "main"], cwd=project_path)

    try:
        _run(["pull", "--ff-only"], cwd=project_path)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.warning("prepare_repo.pull_failed", error=str(exc))


def create_branch(project_path: Path, slug: str) -> str:
    """Create and checkout a ``nightshift/{slug}-{YYYYMMDD}`` branch.

    Returns the branch name.
    """
    date_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    branch = f"nightshift/{slug}-{date_str}"
    log.info("create_branch", branch=branch)
    _run(["checkout", "-b", branch], cwd=project_path)
    return branch


def push_branch(project_path: Path, branch: str) -> None:
    """Push branch to origin and set upstream tracking."""
    log.info("push_branch", branch=branch)
    _run(["push", "-u", "origin", branch], cwd=project_path)


def create_pr(
    project_path: Path,
    branch: str,
    title: str,
    body: str,
) -> tuple[str, int]:
    """Create a draft pull request via ``gh pr create``.

    Returns ``(pr_url, pr_number)``.
    """
    log.info("create_pr", branch=branch, title=title)
    result = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--draft",
            "--title",
            title,
            "--body",
            body,
            "--head",
            branch,
        ],
        cwd=project_path,
        check=True,
        capture_output=True,
        text=True,
    )
    pr_url = result.stdout.strip()

    # Extract the PR number from the URL (last path segment).
    pr_number = int(pr_url.rstrip("/").rsplit("/", 1)[-1])
    return pr_url, pr_number


def cleanup_branch(project_path: Path, branch: str) -> None:
    """Return to main and delete the local feature branch."""
    log.info("cleanup_branch", branch=branch)
    _run(["checkout", "main"], cwd=project_path)
    _run(["branch", "-D", branch], cwd=project_path, check=False)


def get_diff_stats(project_path: Path) -> tuple[int, int, int]:
    """Return ``(files_changed, lines_added, lines_removed)`` for staged + unstaged changes vs main."""
    result = _run(["diff", "--stat", "main...HEAD"], cwd=project_path)
    stdout = result.stdout.strip()

    if not stdout:
        return 0, 0, 0

    # The last line of ``git diff --stat`` looks like:
    #   3 files changed, 10 insertions(+), 2 deletions(-)
    summary_line = stdout.splitlines()[-1]

    files_changed = 0
    lines_added = 0
    lines_removed = 0

    for part in summary_line.split(","):
        part = part.strip()
        if "file" in part:
            files_changed = int(part.split()[0])
        elif "insertion" in part:
            lines_added = int(part.split()[0])
        elif "deletion" in part:
            lines_removed = int(part.split()[0])

    return files_changed, lines_added, lines_removed
