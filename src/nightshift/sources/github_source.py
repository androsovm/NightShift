"""GitHub Issues task source adapter."""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import structlog
from slugify import slugify

from nightshift.config.secrets import get_secret
from nightshift.models.config import SourceConfig
from nightshift.models.task import Task, TaskPriority

log = structlog.get_logger(__name__)

API_BASE = "https://api.github.com"


class GitHubSource:
    """Fetches tasks from GitHub Issues and closes them on completion."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_token() -> str:
        token = get_secret("GITHUB_TOKEN")
        if not token:
            raise RuntimeError(
                "GITHUB_TOKEN not configured. "
                "Run `nightshift secrets set GITHUB_TOKEN <token>`."
            )
        return token

    @staticmethod
    def _detect_repo() -> str | None:
        """Try to derive ``owner/repo`` from the current git remote."""
        return GitHubSource._detect_repo_from(None)

    @staticmethod
    def _detect_repo_from(cwd: "Path | None") -> str | None:
        """Try to derive ``owner/repo`` from the git remote in *cwd*."""
        try:
            cmd = ["git", "remote", "get-url", "origin"]
            url = subprocess.check_output(
                cmd,
                text=True,
                stderr=subprocess.DEVNULL,
                cwd=cwd,
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

        # SSH: git@github.com:owner/repo.git
        if url.startswith("git@github.com:"):
            return url.removeprefix("git@github.com:").removesuffix(".git")

        # HTTPS: https://github.com/owner/repo.git
        if "github.com/" in url:
            path = url.split("github.com/", 1)[1]
            return path.removesuffix(".git")

        return None

    @staticmethod
    def _resolve_repo(config: SourceConfig) -> str:
        """Return ``owner/repo`` from config or auto-detection."""
        repo = config.repo or GitHubSource._detect_repo()
        if not repo:
            raise RuntimeError(
                "Cannot determine GitHub repo. "
                "Set 'repo' in source config or ensure a GitHub remote exists."
            )
        return repo

    @staticmethod
    def _priority_from_labels(label_names: list[str]) -> TaskPriority:
        lowered = {name.lower() for name in label_names}
        if "priority:high" in lowered or "p1" in lowered:
            return TaskPriority.HIGH
        if "priority:low" in lowered or "p3" in lowered:
            return TaskPriority.LOW
        return TaskPriority.MEDIUM

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def fetch_tasks(
        self, project_path: str, config: SourceConfig
    ) -> list[Task]:
        token = self._get_token()
        repo = self._resolve_repo(config)
        labels = ",".join(config.labels) if config.labels else "nightshift"

        url = f"{API_BASE}/repos/{repo}/issues"
        params: dict[str, str] = {
            "state": "open",
            "labels": labels,
            "per_page": "100",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url, headers=self._headers(token), params=params
            )
            resp.raise_for_status()
            issues = resp.json()

        tasks: list[Task] = []
        for issue in issues:
            # Skip pull requests (they also show up in /issues)
            if "pull_request" in issue:
                continue

            label_names = [lbl["name"] for lbl in issue.get("labels", [])]
            task = Task(
                id=slugify(f"gh-{issue['number']}-{issue['title']}"[:80]),
                title=issue["title"],
                source_type="github",
                source_ref=issue["html_url"],
                project_path=project_path,
                priority=self._priority_from_labels(label_names),
                intent=issue.get("body"),
            )
            tasks.append(task)

        log.info(
            "github_source.fetched",
            repo=repo,
            labels=labels,
            count=len(tasks),
        )
        return tasks

    async def mark_done(self, task: Task, pr_url: str) -> None:
        """Post a comment linking the PR, then close the issue."""
        token = self._get_token()
        issue_url = task.source_ref
        if not issue_url:
            log.warning("github_source.mark_done.no_ref", task_id=task.id)
            return

        # Derive API URL from the HTML URL
        # https://github.com/owner/repo/issues/42  ->
        # https://api.github.com/repos/owner/repo/issues/42
        api_url = issue_url.replace(
            "https://github.com/", f"{API_BASE}/repos/"
        )
        headers = self._headers(token)

        async with httpx.AsyncClient(timeout=30) as client:
            # Post a comment
            comment_body = (
                f"Completed by NightShift.\n\nPull request: {pr_url}"
            )
            resp = await client.post(
                f"{api_url}/comments",
                headers=headers,
                json={"body": comment_body},
            )
            resp.raise_for_status()

            # Close the issue
            resp = await client.patch(
                api_url,
                headers=headers,
                json={"state": "closed", "state_reason": "completed"},
            )
            resp.raise_for_status()

        log.info(
            "github_source.marked_done",
            task_id=task.id,
            issue_url=issue_url,
            pr_url=pr_url,
        )
