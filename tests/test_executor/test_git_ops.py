"""Tests for nightshift.executor.git_ops."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nightshift.executor.git_ops import (
    _GIT_BASE,
    cleanup_branch,
    create_branch,
    create_pr,
    get_diff_stats,
    prepare_repo,
    push_branch,
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path / "repo"


def _ok(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=""
    )


# ---------------------------------------------------------------------------
# prepare_repo
# ---------------------------------------------------------------------------


class TestPrepareRepo:
    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_calls_fetch_checkout_pull(
        self, mock_run: MagicMock, project: Path
    ) -> None:
        mock_run.return_value = _ok()
        prepare_repo(project)

        assert mock_run.call_count == 3
        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert cmds[0] == [*_GIT_BASE, "fetch", "origin"]
        assert cmds[1] == [*_GIT_BASE, "checkout", "main"]
        assert cmds[2] == [*_GIT_BASE, "pull", "--ff-only"]

        for c in mock_run.call_args_list:
            assert c.kwargs["cwd"] == project


class TestPrepareRepoErrorHandling:
    """Tests for network-failure resilience in prepare_repo()."""

    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_prepare_repo_fetch_failure_continues(
        self, mock_run: MagicMock, project: Path
    ) -> None:
        """If fetch fails, checkout and pull are still called."""

        def side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if "fetch" in cmd:
                raise subprocess.CalledProcessError(1, cmd)
            return _ok()

        mock_run.side_effect = side_effect
        prepare_repo(project)

        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert any("checkout" in c for c in cmds)
        assert any("pull" in c for c in cmds)

    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_prepare_repo_pull_failure_continues(
        self, mock_run: MagicMock, project: Path
    ) -> None:
        """If pull fails, no exception propagates."""

        def side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if "pull" in cmd:
                raise subprocess.CalledProcessError(1, cmd)
            return _ok()

        mock_run.side_effect = side_effect
        # Should not raise
        prepare_repo(project)

    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_prepare_repo_checkout_failure_raises(
        self, mock_run: MagicMock, project: Path
    ) -> None:
        """If checkout main fails, the exception propagates."""

        def side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if "checkout" in cmd:
                raise subprocess.CalledProcessError(1, cmd)
            return _ok()

        mock_run.side_effect = side_effect
        with pytest.raises(subprocess.CalledProcessError):
            prepare_repo(project)


# ---------------------------------------------------------------------------
# create_branch
# ---------------------------------------------------------------------------


class TestCreateBranch:
    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_branch_name_format(self, mock_run: MagicMock, project: Path) -> None:
        mock_run.return_value = _ok()
        branch, reused = create_branch(project, "fix-imports")

        assert branch.startswith("nightshift/fix-imports-")
        assert not reused
        # Date suffix is 8 digits.
        date_part = branch.rsplit("-", 1)[-1]
        assert len(date_part) == 8
        assert date_part.isdigit()

    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_runs_checkout_B(self, mock_run: MagicMock, project: Path) -> None:
        mock_run.return_value = _ok()
        branch, _reused = create_branch(project, "slug")

        # Uses -B (create-or-reset) instead of -b.
        checkout_call = mock_run.call_args_list[-1][0][0]
        assert checkout_call == [*_GIT_BASE, "checkout", "-B", branch]

    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_reused_flag_when_branch_exists(self, mock_run: MagicMock, project: Path) -> None:
        # First call (branch --list) returns matching branch name; second call (checkout -B) succeeds.
        mock_run.side_effect = [_ok("  nightshift/slug-20260323\n"), _ok()]
        _branch, reused = create_branch(project, "slug")

        assert reused is True


# ---------------------------------------------------------------------------
# push_branch
# ---------------------------------------------------------------------------


class TestPushBranch:
    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_push_command(self, mock_run: MagicMock, project: Path) -> None:
        mock_run.return_value = _ok()
        push_branch(project, "nightshift/feature-20260318")

        cmd = mock_run.call_args[0][0]
        assert cmd == [
            *_GIT_BASE,
            "push",
            "-u",
            "origin",
            "nightshift/feature-20260318",
        ]

    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_push_force_with_lease(self, mock_run: MagicMock, project: Path) -> None:
        mock_run.return_value = _ok()
        push_branch(project, "nightshift/feature-20260318", force_with_lease=True)

        cmd = mock_run.call_args[0][0]
        assert cmd == [
            *_GIT_BASE,
            "push",
            "--force-with-lease",
            "-u",
            "origin",
            "nightshift/feature-20260318",
        ]


# ---------------------------------------------------------------------------
# create_pr
# ---------------------------------------------------------------------------


class TestCreatePR:
    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_creates_draft_pr(self, mock_run: MagicMock, project: Path) -> None:
        # First call: gh pr view (no existing PR), second: gh pr create
        no_pr = _ok(stdout="")
        no_pr.returncode = 1
        mock_run.side_effect = [
            no_pr,
            _ok(stdout="https://github.com/user/repo/pull/42\n"),
        ]
        url, number = create_pr(project, "nightshift/fix-20260318", "Title", "Body")

        assert url == "https://github.com/user/repo/pull/42"
        assert number == 42

        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "--draft" in cmd
        assert "--title" in cmd
        assert "Title" in cmd

    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_pr_number_extraction(self, mock_run: MagicMock, project: Path) -> None:
        no_pr = _ok(stdout="")
        no_pr.returncode = 1
        mock_run.side_effect = [
            no_pr,
            _ok(stdout="https://github.com/org/repo/pull/999\n"),
        ]
        _, number = create_pr(project, "branch", "T", "B")
        assert number == 999

    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_updates_existing_pr(self, mock_run: MagicMock, project: Path) -> None:
        """When a PR already exists for the branch, update it instead of creating."""
        mock_run.side_effect = [
            _ok(stdout='{"url": "https://github.com/org/repo/pull/17", "number": 17, "state": "OPEN"}'),
            _ok(stdout=""),
        ]
        url, number = create_pr(project, "branch", "New Title", "New Body")

        assert url == "https://github.com/org/repo/pull/17"
        assert number == 17
        edit_cmd = mock_run.call_args_list[1][0][0]
        assert "edit" in edit_cmd
        assert "17" in edit_cmd


# ---------------------------------------------------------------------------
# cleanup_branch
# ---------------------------------------------------------------------------


class TestCleanupBranch:
    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_checkouts_main_and_deletes_branch(
        self, mock_run: MagicMock, project: Path
    ) -> None:
        mock_run.return_value = _ok()
        cleanup_branch(project, "nightshift/old-branch")

        assert mock_run.call_count == 2
        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert cmds[0] == [*_GIT_BASE, "checkout", "main"]
        assert cmds[1] == [*_GIT_BASE, "branch", "-D", "nightshift/old-branch"]

    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_delete_uses_check_false(
        self, mock_run: MagicMock, project: Path
    ) -> None:
        mock_run.return_value = _ok()
        cleanup_branch(project, "branch")

        # The branch delete call should have check=False.
        delete_call = mock_run.call_args_list[1]
        assert delete_call.kwargs.get("check") is False


# ---------------------------------------------------------------------------
# get_diff_stats
# ---------------------------------------------------------------------------


class TestGetDiffStats:
    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_parses_full_summary(self, mock_run: MagicMock, project: Path) -> None:
        mock_run.return_value = _ok(
            stdout=(
                " file1.py | 5 +++++\n"
                " file2.py | 3 +--\n"
                " file3.py | 1 -\n"
                " 3 files changed, 10 insertions(+), 2 deletions(-)\n"
            )
        )
        files, added, removed = get_diff_stats(project)
        assert files == 3
        assert added == 10
        assert removed == 2

    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_empty_diff(self, mock_run: MagicMock, project: Path) -> None:
        mock_run.return_value = _ok(stdout="")
        files, added, removed = get_diff_stats(project)
        assert (files, added, removed) == (0, 0, 0)

    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_insertions_only(self, mock_run: MagicMock, project: Path) -> None:
        mock_run.return_value = _ok(
            stdout=" 1 file changed, 5 insertions(+)\n"
        )
        files, added, removed = get_diff_stats(project)
        assert files == 1
        assert added == 5
        assert removed == 0

    @patch("nightshift.executor.git_ops.subprocess.run")
    def test_deletions_only(self, mock_run: MagicMock, project: Path) -> None:
        mock_run.return_value = _ok(
            stdout=" 2 files changed, 8 deletions(-)\n"
        )
        files, added, removed = get_diff_stats(project)
        assert files == 2
        assert added == 0
        assert removed == 8
