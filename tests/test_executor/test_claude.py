"""Tests for nightshift.executor.claude."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nightshift.executor.claude import build_prompt, invoke_claude
from nightshift.models.task import Task, TaskPriority


@pytest.fixture
def task() -> Task:
    return Task(
        id="refactor-utils",
        title="Refactor utils module",
        source_type="yaml",
        project_path="/tmp/proj",
        priority=TaskPriority.HIGH,
        intent="Simplify the utilities module",
        scope=["src/utils.py", "src/helpers.py"],
        constraints=["Keep backward compatibility", "Add docstrings"],
    )


@pytest.fixture
def minimal_task() -> Task:
    return Task(
        id="simple",
        title="Simple task",
        source_type="yaml",
        project_path="/tmp/proj",
    )


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_includes_title(self, task: Task) -> None:
        prompt = build_prompt(task)
        assert "# Task: Refactor utils module" in prompt

    def test_includes_intent(self, task: Task) -> None:
        prompt = build_prompt(task)
        assert "**Intent:** Simplify the utilities module" in prompt

    def test_includes_scope(self, task: Task) -> None:
        prompt = build_prompt(task)
        assert "- src/utils.py" in prompt
        assert "- src/helpers.py" in prompt

    def test_includes_constraints(self, task: Task) -> None:
        prompt = build_prompt(task)
        assert "- Keep backward compatibility" in prompt
        assert "- Add docstrings" in prompt

    def test_includes_implementation_instruction(self, task: Task) -> None:
        prompt = build_prompt(task)
        assert "Implement the changes described above" in prompt

    def test_system_prompt_prepended(self, task: Task) -> None:
        prompt = build_prompt(task, system_prompt="You are a code robot.")
        lines = prompt.split("\n")
        assert lines[0] == "You are a code robot."

    def test_no_system_prompt(self, task: Task) -> None:
        prompt = build_prompt(task, system_prompt=None)
        assert prompt.startswith("# Task:")

    def test_minimal_task_omits_optional_sections(
        self, minimal_task: Task
    ) -> None:
        prompt = build_prompt(minimal_task)
        assert "# Task: Simple task" in prompt
        assert "**Intent:**" not in prompt
        assert "**Scope" not in prompt
        assert "**Constraints:**" not in prompt

    def test_system_prompt_whitespace_stripped(self, minimal_task: Task) -> None:
        prompt = build_prompt(minimal_task, system_prompt="  padded  \n\n")
        assert prompt.startswith("padded")


# ---------------------------------------------------------------------------
# invoke_claude
# ---------------------------------------------------------------------------


class TestInvokeClaude:
    @patch("nightshift.executor.claude.subprocess.run")
    def test_successful_invocation(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="All done!", stderr=""
        )
        log_file = tmp_path / "logs" / "run.log"
        success, output = invoke_claude(tmp_path, "prompt", 30, log_file)

        assert success is True
        assert "All done!" in output
        assert log_file.exists()
        assert log_file.read_text(encoding="utf-8") == "All done!"

    @patch("nightshift.executor.claude.subprocess.run")
    def test_nonzero_exit(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="partial", stderr="error detail"
        )
        log_file = tmp_path / "run.log"
        success, output = invoke_claude(tmp_path, "prompt", 10, log_file)

        assert success is False
        assert "partial" in output
        assert "STDERR" in output
        assert "error detail" in output

    @patch("nightshift.executor.claude.subprocess.run")
    def test_timeout(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=600)
        log_file = tmp_path / "run.log"
        success, output = invoke_claude(tmp_path, "prompt", 10, log_file)

        assert success is False
        assert "timed out" in output
        assert log_file.exists()

    @patch("nightshift.executor.claude.subprocess.run")
    def test_claude_not_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.side_effect = FileNotFoundError()
        log_file = tmp_path / "run.log"
        success, output = invoke_claude(tmp_path, "prompt", 10, log_file)

        assert success is False
        assert "not found" in output
        assert log_file.exists()

    @patch("nightshift.executor.claude.subprocess.run")
    def test_passes_correct_args(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )
        log_file = tmp_path / "run.log"
        invoke_claude(tmp_path, "do stuff", 45, log_file)

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "do stuff" in cmd
        assert "--dangerously-skip-permissions" in cmd

        kwargs = mock_run.call_args[1]
        assert kwargs["timeout"] == 45 * 60
        assert kwargs["cwd"] == tmp_path

    @patch("nightshift.executor.claude.subprocess.run")
    def test_log_directory_created(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="output", stderr=""
        )
        log_file = tmp_path / "deep" / "nested" / "dir" / "run.log"
        invoke_claude(tmp_path, "prompt", 5, log_file)

        assert log_file.parent.exists()
        assert log_file.exists()

    @patch("nightshift.executor.claude.subprocess.run")
    def test_stderr_appended(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="out", stderr="warn"
        )
        log_file = tmp_path / "run.log"
        success, output = invoke_claude(tmp_path, "p", 5, log_file)

        assert success is True
        assert "out" in output
        assert "warn" in output
