"""Scan open NightShift PRs for review feedback and approval status."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import structlog
from slugify import slugify

from nightshift.config.secrets import get_secret
from nightshift.models.task import Task, TaskPriority
from nightshift.storage.task_queue import find_by_source_ref

log = structlog.get_logger(__name__)

API_BASE = "https://api.github.com"

_NIGHTSHIFT_PREFIX = "[NightShift]"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_token() -> str:
    token = get_secret("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN not configured. "
            "Run `nightshift secrets set GITHUB_TOKEN <token>`."
        )
    return token


async def _fetch_nightshift_prs(
    client: httpx.AsyncClient, repo: str, token: str
) -> list[dict]:
    """Return open PRs whose title starts with [NightShift]."""
    resp = await client.get(
        f"{API_BASE}/repos/{repo}/pulls",
        headers=_headers(token),
        params={"state": "open", "per_page": "100"},
    )
    resp.raise_for_status()
    return [pr for pr in resp.json() if pr["title"].startswith(_NIGHTSHIFT_PREFIX)]


def _format_review_intent(
    pr_number: int,
    pr_title: str,
    reviews: list[dict],
    comments: list[dict],
) -> str:
    """Build a structured intent string from review feedback."""
    parts: list[str] = []
    parts.append(f"## Review feedback on PR #{pr_number}: {pr_title}")
    parts.append("")

    # Collect review bodies (skip empty ones)
    for review in reviews:
        body = (review.get("body") or "").strip()
        if body:
            parts.append(f"### Review by {review['user']['login']}")
            parts.append(body)
            parts.append("")

    # File-specific comments
    if comments:
        parts.append("### File-specific comments")
        parts.append("")
        for comment in comments:
            path = comment.get("path", "unknown")
            line = comment.get("line") or comment.get("original_line") or "?"
            body = (comment.get("body") or "").strip()
            if body:
                parts.append(f"**{path}** (line {line}):")
                parts.append(f"> {body}")
                parts.append("")

    return "\n".join(parts)


async def fetch_review_tasks(project_path: str, repo: str) -> list[Task]:
    """Return tasks for NightShift PRs that have unaddressed review feedback.

    A review is considered unaddressed if:
    - The latest review is CHANGES_REQUESTED or COMMENTED with a non-empty body
    - There are no commits after the review timestamp (NightShift hasn't responded yet)
    - No pending review task already exists in the queue for this PR
    """
    token = _get_token()
    tasks: list[Task] = []

    async with httpx.AsyncClient(timeout=30) as client:
        prs = await _fetch_nightshift_prs(client, repo, token)

        for pr in prs:
            pr_number = pr["number"]
            pr_title = pr["title"]
            pr_branch = pr["head"]["ref"]
            source_ref = f"review:{repo}/pulls/{pr_number}"

            # Skip if a pending review task already exists
            existing = find_by_source_ref("github_review", source_ref)
            if existing and existing.status in ("pending", "running"):
                continue

            # Fetch reviews
            resp = await client.get(
                f"{API_BASE}/repos/{repo}/pulls/{pr_number}/reviews",
                headers=_headers(token),
            )
            resp.raise_for_status()
            reviews = resp.json()

            if not reviews:
                continue

            # Find the latest substantive review (not just approved/dismissed)
            actionable_reviews = [
                r for r in reviews
                if r["state"] in ("CHANGES_REQUESTED", "COMMENTED")
                and (r.get("body") or "").strip()
            ]
            if not actionable_reviews:
                continue

            latest_review = actionable_reviews[-1]
            review_submitted_at = datetime.fromisoformat(
                latest_review["submitted_at"].replace("Z", "+00:00")
            )

            # Check if there are commits after the review (already addressed)
            resp = await client.get(
                f"{API_BASE}/repos/{repo}/pulls/{pr_number}/commits",
                headers=_headers(token),
            )
            resp.raise_for_status()
            commits = resp.json()

            if commits:
                last_commit_date_str = (
                    commits[-1]["commit"]["committer"]["date"]
                )
                last_commit_date = datetime.fromisoformat(
                    last_commit_date_str.replace("Z", "+00:00")
                )
                if last_commit_date > review_submitted_at:
                    # Commits exist after the review — already addressed
                    continue

            # Fetch file-level review comments
            resp = await client.get(
                f"{API_BASE}/repos/{repo}/pulls/{pr_number}/comments",
                headers=_headers(token),
            )
            resp.raise_for_status()
            file_comments = resp.json()

            # Filter to comments after or at the review time
            relevant_comments = [
                c for c in file_comments
                if datetime.fromisoformat(
                    c["created_at"].replace("Z", "+00:00")
                ) >= review_submitted_at
            ]

            intent = _format_review_intent(
                pr_number, pr_title, actionable_reviews, relevant_comments
            )

            # Strip [NightShift] prefix for a cleaner title
            clean_title = pr_title.removeprefix(_NIGHTSHIFT_PREFIX).strip()
            task = Task(
                id=slugify(f"review-pr-{pr_number}-{clean_title}"[:80]),
                title=f"Address review: {clean_title}",
                source_type="github_review",
                source_ref=source_ref,
                project_path=project_path,
                priority=TaskPriority.HIGH,
                intent=intent,
                pr_branch=pr_branch,
                pr_number=pr_number,
            )
            tasks.append(task)

    log.info(
        "github_reviews.fetched",
        repo=repo,
        review_tasks=len(tasks),
    )
    return tasks


async def check_approved_prs(repo: str) -> list[tuple[int, str]]:
    """Return ``(pr_number, pr_url)`` for approved NightShift PRs."""
    token = _get_token()
    approved: list[tuple[int, str]] = []

    async with httpx.AsyncClient(timeout=30) as client:
        prs = await _fetch_nightshift_prs(client, repo, token)

        for pr in prs:
            pr_number = pr["number"]

            resp = await client.get(
                f"{API_BASE}/repos/{repo}/pulls/{pr_number}/reviews",
                headers=_headers(token),
            )
            resp.raise_for_status()
            reviews = resp.json()

            if not reviews:
                continue

            # Check if the latest review is APPROVED
            latest = reviews[-1]
            if latest["state"] == "APPROVED":
                approved.append((pr_number, pr["html_url"]))

    log.info(
        "github_reviews.approved_check",
        repo=repo,
        approved_count=len(approved),
    )
    return approved
