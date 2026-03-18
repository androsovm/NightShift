"""YouTrack task source adapter."""

from __future__ import annotations

import httpx
import structlog
from slugify import slugify

from nightshift.config.secrets import get_secret
from nightshift.models.config import SourceConfig
from nightshift.models.task import Task, TaskPriority

log = structlog.get_logger(__name__)


class YouTrackSource:
    """Fetches tasks from YouTrack issues by tag and marks them done."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_token() -> str:
        token = get_secret("YOUTRACK_TOKEN")
        if not token:
            raise RuntimeError(
                "YOUTRACK_TOKEN not configured. "
                "Run `nightshift secrets set YOUTRACK_TOKEN <token>`."
            )
        return token

    @staticmethod
    def _resolve_base_url(config: SourceConfig) -> str:
        if not config.base_url:
            raise RuntimeError(
                "YouTrack source requires 'base_url' in config "
                "(e.g. https://youtrack.example.com)."
            )
        return config.base_url.rstrip("/")

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _extract_priority(issue: dict) -> TaskPriority:
        """Attempt to map YouTrack priority custom field to TaskPriority."""
        for field in issue.get("customFields", []):
            if field.get("name", "").lower() == "priority":
                value = field.get("value", {})
                name = (value.get("name", "") if isinstance(value, dict) else "").lower()
                if name in ("critical", "show-stopper", "high"):
                    return TaskPriority.HIGH
                if name in ("low", "minor"):
                    return TaskPriority.LOW
        return TaskPriority.MEDIUM

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def fetch_tasks(
        self, project_path: str, config: SourceConfig
    ) -> list[Task]:
        token = self._get_token()
        base_url = self._resolve_base_url(config)
        tag = config.tag
        fields = "idReadable,summary,description,customFields(name,value(name))"

        url = f"{base_url}/api/issues"
        params: dict[str, str] = {
            "query": f"tag: {{{tag}}}",
            "fields": fields,
            "$top": "100",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url, headers=self._headers(token), params=params
            )
            resp.raise_for_status()
            issues = resp.json()

        tasks: list[Task] = []
        for issue in issues:
            readable_id = issue.get("idReadable", "")
            summary = issue.get("summary", "")
            task = Task(
                id=slugify(f"yt-{readable_id}-{summary}"[:80]),
                title=summary,
                source_type="youtrack",
                source_ref=f"{base_url}/issue/{readable_id}",
                project_path=project_path,
                priority=self._extract_priority(issue),
                intent=issue.get("description"),
            )
            tasks.append(task)

        log.info(
            "youtrack_source.fetched",
            base_url=base_url,
            tag=tag,
            count=len(tasks),
        )
        return tasks

    async def mark_done(self, task: Task, pr_url: str) -> None:
        """Remove the NightShift tag and post a comment with the PR link."""
        token = self._get_token()
        source_ref = task.source_ref or ""

        # Derive issue ID from source_ref (.../issue/PROJ-123)
        parts = source_ref.rstrip("/").rsplit("/issue/", 1)
        if len(parts) != 2:
            log.warning(
                "youtrack_source.mark_done.bad_ref",
                task_id=task.id,
                source_ref=source_ref,
            )
            return

        base_url = parts[0]
        issue_id = parts[1]
        headers = self._headers(token)

        async with httpx.AsyncClient(timeout=30) as client:
            # 1. Fetch current tags so we can identify the one to remove
            tags_resp = await client.get(
                f"{base_url}/api/issues/{issue_id}",
                headers=headers,
                params={"fields": "tags(id,name)"},
            )
            tags_resp.raise_for_status()
            tags = tags_resp.json().get("tags", [])

            # Remove the nightshift tag
            for tag_obj in tags:
                if tag_obj.get("name", "").lower() == "nightshift":
                    resp = await client.delete(
                        f"{base_url}/api/issues/{issue_id}/tags/{tag_obj['id']}",
                        headers=headers,
                    )
                    resp.raise_for_status()
                    break

            # 2. Post a comment
            comment_body = (
                f"Completed by NightShift.\n\nPull request: {pr_url}"
            )
            resp = await client.post(
                f"{base_url}/api/issues/{issue_id}/comments",
                headers=headers,
                json={"text": comment_body},
            )
            resp.raise_for_status()

        log.info(
            "youtrack_source.marked_done",
            task_id=task.id,
            issue_id=issue_id,
            pr_url=pr_url,
        )
