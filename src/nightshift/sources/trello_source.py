"""Trello task source adapter."""

from __future__ import annotations

import httpx
import structlog
from slugify import slugify

from nightshift.config.secrets import get_secret
from nightshift.models.config import SourceConfig
from nightshift.models.task import Task, TaskPriority

log = structlog.get_logger(__name__)

API_BASE = "https://api.trello.com"


class TrelloSource:
    """Fetches tasks from a Trello list and moves cards to Done."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_credentials() -> tuple[str, str]:
        key = get_secret("TRELLO_API_KEY")
        token = get_secret("TRELLO_TOKEN")
        if not key or not token:
            raise RuntimeError(
                "TRELLO_KEY and TRELLO_TOKEN must both be configured. "
                "Run `nightshift secrets set TRELLO_API_KEY <key>` and "
                "`nightshift secrets set TRELLO_TOKEN <token>`."
            )
        return key, token

    def _auth_params(self, key: str, token: str) -> dict[str, str]:
        return {"key": key, "token": token}

    @staticmethod
    def _priority_from_labels(labels: list[dict]) -> TaskPriority:
        names = {l.get("name", "").lower() for l in labels}
        if "high" in names or "urgent" in names:
            return TaskPriority.HIGH
        if "low" in names:
            return TaskPriority.LOW
        return TaskPriority.MEDIUM

    # ------------------------------------------------------------------
    # List resolution
    # ------------------------------------------------------------------

    async def _find_list_id(
        self,
        client: httpx.AsyncClient,
        board_id: str,
        list_name: str,
        auth: dict[str, str],
    ) -> str:
        """Find the ID of the list named *list_name* on *board_id*."""
        url = f"{API_BASE}/1/boards/{board_id}/lists"
        resp = await client.get(url, params={**auth, "fields": "name"})
        resp.raise_for_status()
        lists = resp.json()

        for lst in lists:
            if lst["name"].lower() == list_name.lower():
                return lst["id"]

        available = [l["name"] for l in lists]
        raise RuntimeError(
            f"List '{list_name}' not found on board {board_id}. "
            f"Available lists: {available}"
        )

    async def _find_or_create_done_list(
        self,
        client: httpx.AsyncClient,
        board_id: str,
        auth: dict[str, str],
    ) -> str:
        """Return the ID of a list named 'Done', creating it if needed."""
        url = f"{API_BASE}/1/boards/{board_id}/lists"
        resp = await client.get(url, params={**auth, "fields": "name"})
        resp.raise_for_status()
        lists = resp.json()

        for lst in lists:
            if lst["name"].lower() == "done":
                return lst["id"]

        # Create the list
        resp = await client.post(
            f"{API_BASE}/1/lists",
            params={**auth, "name": "Done", "idBoard": board_id, "pos": "bottom"},
        )
        resp.raise_for_status()
        new_list = resp.json()
        log.info("trello_source.created_done_list", board_id=board_id)
        return new_list["id"]

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def fetch_tasks(
        self, project_path: str, config: SourceConfig
    ) -> list[Task]:
        key, token = self._get_credentials()
        auth = self._auth_params(key, token)

        if not config.board_id:
            raise RuntimeError(
                "Trello source requires 'board_id' in config."
            )

        list_name = config.list_name

        async with httpx.AsyncClient(timeout=30) as client:
            list_id = await self._find_list_id(
                client, config.board_id, list_name, auth
            )

            url = f"{API_BASE}/1/lists/{list_id}/cards"
            resp = await client.get(
                url,
                params={
                    **auth,
                    "fields": "name,desc,labels,shortUrl",
                },
            )
            resp.raise_for_status()
            cards = resp.json()

        tasks: list[Task] = []
        for card in cards:
            task = Task(
                id=slugify(f"trello-{card['name']}"[:80]),
                title=card["name"],
                source_type="trello",
                source_ref=card.get("shortUrl", ""),
                project_path=project_path,
                priority=self._priority_from_labels(card.get("labels", [])),
                intent=card.get("desc") or None,
            )
            tasks.append(task)

        log.info(
            "trello_source.fetched",
            board_id=config.board_id,
            list_name=list_name,
            count=len(tasks),
        )
        return tasks

    async def mark_done(self, task: Task, pr_url: str) -> None:
        """Move the card to the 'Done' list and add a comment."""
        key, token = self._get_credentials()
        auth = self._auth_params(key, token)
        card_url = task.source_ref
        if not card_url:
            log.warning("trello_source.mark_done.no_ref", task_id=task.id)
            return

        # Extract card short ID from shortUrl: https://trello.com/c/<shortLink>
        short_link = card_url.rstrip("/").rsplit("/", 1)[-1]

        async with httpx.AsyncClient(timeout=30) as client:
            # Resolve card to get its full ID and board ID
            card_resp = await client.get(
                f"{API_BASE}/1/cards/{short_link}",
                params={**auth, "fields": "id,idBoard"},
            )
            card_resp.raise_for_status()
            card = card_resp.json()
            card_id = card["id"]
            board_id = card["idBoard"]

            # Find or create the Done list
            done_list_id = await self._find_or_create_done_list(
                client, board_id, auth
            )

            # Move card to Done
            resp = await client.put(
                f"{API_BASE}/1/cards/{card_id}",
                params={**auth, "idList": done_list_id},
            )
            resp.raise_for_status()

            # Add a comment
            comment_text = (
                f"Completed by NightShift.\n\nPull request: {pr_url}"
            )
            resp = await client.post(
                f"{API_BASE}/1/cards/{card_id}/actions/comments",
                params={**auth, "text": comment_text},
            )
            resp.raise_for_status()

        log.info(
            "trello_source.marked_done",
            task_id=task.id,
            card_url=card_url,
            pr_url=pr_url,
        )
