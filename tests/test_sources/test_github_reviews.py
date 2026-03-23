"""Tests for github_reviews module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from nightshift.models.task import TaskPriority, TaskStatus
from nightshift.sources.github_reviews import (
    _format_review_intent,
    check_approved_prs,
    fetch_review_tasks,
)


@pytest.fixture()
def _mock_token():
    with patch("nightshift.sources.github_reviews.get_secret", return_value="fake-token"):
        yield


def _make_response(json_data, status_code=200):
    resp = httpx.Response(status_code, json=json_data, request=httpx.Request("GET", "http://test"))
    return resp


class TestFormatReviewIntent:
    def test_formats_review_body(self):
        reviews = [
            {"user": {"login": "dev"}, "body": "Fix the typo in line 10"},
        ]
        result = _format_review_intent(42, "[NightShift] Fix bug", reviews, [])
        assert "PR #42" in result
        assert "Fix the typo in line 10" in result
        assert "dev" in result

    def test_formats_file_comments(self):
        comments = [
            {"path": "src/main.py", "line": 25, "original_line": None, "body": "Use snake_case here"},
        ]
        result = _format_review_intent(42, "Title", [], comments)
        assert "src/main.py" in result
        assert "line 25" in result
        assert "Use snake_case here" in result

    def test_skips_empty_bodies(self):
        reviews = [
            {"user": {"login": "dev"}, "body": ""},
            {"user": {"login": "dev2"}, "body": None},
        ]
        result = _format_review_intent(1, "Title", reviews, [])
        assert "dev" not in result


class TestFetchReviewTasks:
    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_token")
    async def test_creates_task_for_review_with_changes_requested(self):
        pr = {
            "number": 10,
            "title": "[NightShift] Fix auth",
            "head": {"ref": "nightshift/fix-auth-20260323"},
            "html_url": "https://github.com/user/repo/pull/10",
        }
        review = {
            "state": "CHANGES_REQUESTED",
            "body": "Please fix the getattr usage",
            "user": {"login": "reviewer"},
            "submitted_at": "2026-03-23T10:00:00Z",
        }
        commit = {
            "commit": {"committer": {"date": "2026-03-23T08:00:00Z"}},
        }

        responses = [
            _make_response([pr]),          # pulls
            _make_response([review]),      # reviews
            _make_response([commit]),      # commits
            _make_response([]),            # comments
        ]
        call_idx = 0

        async def mock_get(url, **kwargs):
            nonlocal call_idx
            resp = responses[call_idx]
            call_idx += 1
            return resp

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = mock_get

        with (
            patch("nightshift.sources.github_reviews.find_by_source_ref", return_value=None),
            patch("httpx.AsyncClient") as MockClient,
        ):
            MockClient.return_value.__aenter__ = lambda self: _async_return(mock_client)
            MockClient.return_value.__aexit__ = lambda self, *a: _async_return(None)

            tasks = await fetch_review_tasks("/tmp/proj", "user/repo")

        assert len(tasks) == 1
        task = tasks[0]
        assert task.source_type == "github_review"
        assert task.pr_branch == "nightshift/fix-auth-20260323"
        assert task.pr_number == 10
        assert task.priority == TaskPriority.HIGH
        assert "getattr" in task.intent

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_token")
    async def test_skips_if_commit_after_review(self):
        """If there's a commit after the review, the feedback was already addressed."""
        pr = {
            "number": 10,
            "title": "[NightShift] Fix auth",
            "head": {"ref": "nightshift/fix-auth-20260323"},
            "html_url": "https://github.com/user/repo/pull/10",
        }
        review = {
            "state": "CHANGES_REQUESTED",
            "body": "Fix this",
            "user": {"login": "reviewer"},
            "submitted_at": "2026-03-23T10:00:00Z",
        }
        # Commit AFTER the review
        commit = {
            "commit": {"committer": {"date": "2026-03-23T12:00:00Z"}},
        }

        responses = [
            _make_response([pr]),
            _make_response([review]),
            _make_response([commit]),
        ]
        call_idx = 0

        async def mock_get(url, **kwargs):
            nonlocal call_idx
            resp = responses[call_idx]
            call_idx += 1
            return resp

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = mock_get

        with (
            patch("nightshift.sources.github_reviews.find_by_source_ref", return_value=None),
            patch("httpx.AsyncClient") as MockClient,
        ):
            MockClient.return_value.__aenter__ = lambda self: _async_return(mock_client)
            MockClient.return_value.__aexit__ = lambda self, *a: _async_return(None)

            tasks = await fetch_review_tasks("/tmp/proj", "user/repo")

        assert len(tasks) == 0

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_token")
    async def test_skips_if_pending_review_task_exists(self):
        pr = {
            "number": 10,
            "title": "[NightShift] Fix auth",
            "head": {"ref": "nightshift/fix-auth-20260323"},
            "html_url": "https://github.com/user/repo/pull/10",
        }

        responses = [
            _make_response([pr]),
        ]
        call_idx = 0

        async def mock_get(url, **kwargs):
            nonlocal call_idx
            resp = responses[call_idx]
            call_idx += 1
            return resp

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = mock_get

        existing = MagicMock()
        existing.status = TaskStatus.PENDING

        with (
            patch("nightshift.sources.github_reviews.find_by_source_ref", return_value=existing),
            patch("httpx.AsyncClient") as MockClient,
        ):
            MockClient.return_value.__aenter__ = lambda self: _async_return(mock_client)
            MockClient.return_value.__aexit__ = lambda self, *a: _async_return(None)

            tasks = await fetch_review_tasks("/tmp/proj", "user/repo")

        assert len(tasks) == 0


class TestCheckApprovedPrs:
    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_token")
    async def test_returns_approved_prs(self):
        pr = {
            "number": 10,
            "title": "[NightShift] Fix auth",
            "head": {"ref": "nightshift/fix-auth-20260323"},
            "html_url": "https://github.com/user/repo/pull/10",
        }
        review = {"state": "APPROVED", "body": "LGTM"}

        responses = [
            _make_response([pr]),
            _make_response([review]),
        ]
        call_idx = 0

        async def mock_get(url, **kwargs):
            nonlocal call_idx
            resp = responses[call_idx]
            call_idx += 1
            return resp

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = mock_get

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = lambda self: _async_return(mock_client)
            MockClient.return_value.__aexit__ = lambda self, *a: _async_return(None)

            approved = await check_approved_prs("user/repo")

        assert len(approved) == 1
        assert approved[0] == (10, "https://github.com/user/repo/pull/10")


async def _async_return(value):
    return value
