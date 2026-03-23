"""Tests for nightshift.executor.quality_gates."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nightshift.executor.quality_gates import (
    _parse_pytest_summary,
    check_blast_radius,
    run_all_gates,
    run_baseline_tests,
    run_linter,
    run_tests_vs_baseline,
)
from nightshift.models.config import ProjectLimits


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path / "repo"


def _ok(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=""
    )


# ---------------------------------------------------------------------------
# _parse_pytest_summary
# ---------------------------------------------------------------------------


class TestParsePytestSummary:
    def test_passed_and_failed(self) -> None:
        output = "5 passed, 2 failed in 1.23s"
        assert _parse_pytest_summary(output) == (5, 2)

    def test_passed_only(self) -> None:
        output = "12 passed in 3.45s"
        assert _parse_pytest_summary(output) == (12, 0)

    def test_no_match(self) -> None:
        assert _parse_pytest_summary("") == (0, 0)
        assert _parse_pytest_summary("no summary here") == (0, 0)

    def test_multiline_output(self) -> None:
        output = (
            "test_a.py ...\n"
            "test_b.py .F.\n"
            "10 passed, 1 failed in 5.0s\n"
        )
        assert _parse_pytest_summary(output) == (10, 1)


# ---------------------------------------------------------------------------
# check_blast_radius
# ---------------------------------------------------------------------------


class TestCheckBlastRadius:
    @patch("nightshift.executor.quality_gates.get_diff_stats")
    def test_within_limits(self, mock_stats: MagicMock, project: Path) -> None:
        mock_stats.return_value = (3, 50, 10)
        ok, msg = check_blast_radius(project, max_files=20, max_lines=500)
        assert ok is True
        assert "OK" in msg

    @patch("nightshift.executor.quality_gates.get_diff_stats")
    def test_files_exceeded(self, mock_stats: MagicMock, project: Path) -> None:
        mock_stats.return_value = (25, 10, 5)
        ok, msg = check_blast_radius(project, max_files=20, max_lines=500)
        assert ok is False
        assert "files changed (25)" in msg

    @patch("nightshift.executor.quality_gates.get_diff_stats")
    def test_lines_exceeded(self, mock_stats: MagicMock, project: Path) -> None:
        mock_stats.return_value = (2, 400, 200)
        ok, msg = check_blast_radius(project, max_files=20, max_lines=500)
        assert ok is False
        assert "total lines changed (600)" in msg

    @patch("nightshift.executor.quality_gates.get_diff_stats")
    def test_both_exceeded(self, mock_stats: MagicMock, project: Path) -> None:
        mock_stats.return_value = (30, 400, 200)
        ok, msg = check_blast_radius(project, max_files=20, max_lines=500)
        assert ok is False
        assert "files changed" in msg
        assert "total lines" in msg

    @patch("nightshift.executor.quality_gates.get_diff_stats")
    def test_exactly_at_limit_passes(
        self, mock_stats: MagicMock, project: Path
    ) -> None:
        mock_stats.return_value = (20, 250, 250)
        ok, _ = check_blast_radius(project, max_files=20, max_lines=500)
        assert ok is True


# ---------------------------------------------------------------------------
# run_baseline_tests
# ---------------------------------------------------------------------------


class TestRunBaselineTests:
    @patch("nightshift.executor.quality_gates.subprocess.run")
    @patch("nightshift.executor.quality_gates.shutil.which", return_value="/usr/bin/pytest")
    def test_passing_tests(
        self, mock_which: MagicMock, mock_run: MagicMock, project: Path
    ) -> None:
        mock_run.return_value = _ok(
            stdout="8 passed in 2.0s\n", returncode=0
        )
        success, passed, failed = run_baseline_tests(project)
        assert success is True
        assert passed == 8
        assert failed == 0

    @patch("nightshift.executor.quality_gates.subprocess.run")
    @patch("nightshift.executor.quality_gates.shutil.which", return_value="/usr/bin/pytest")
    def test_failing_tests(
        self, mock_which: MagicMock, mock_run: MagicMock, project: Path
    ) -> None:
        mock_run.return_value = _ok(
            stdout="5 passed, 3 failed in 4.0s\n", returncode=1
        )
        success, passed, failed = run_baseline_tests(project)
        assert success is False
        assert passed == 5
        assert failed == 3

    @patch("nightshift.executor.quality_gates.shutil.which", return_value=None)
    def test_pytest_not_installed(
        self, mock_which: MagicMock, project: Path
    ) -> None:
        success, passed, failed = run_baseline_tests(project)
        assert success is True
        assert passed == 0
        assert failed == 0


# ---------------------------------------------------------------------------
# run_linter
# ---------------------------------------------------------------------------


class TestRunLinter:
    @patch("nightshift.executor.quality_gates.subprocess.run")
    @patch("nightshift.executor.quality_gates.shutil.which")
    @patch("nightshift.executor.quality_gates.get_changed_files")
    def test_ruff_passes(
        self, mock_changed: MagicMock, mock_which: MagicMock, mock_run: MagicMock, project: Path
    ) -> None:
        project.mkdir(parents=True, exist_ok=True)
        (project / "main.py").touch()
        mock_changed.return_value = ["main.py"]
        mock_which.side_effect = lambda name: "/usr/bin/ruff" if name == "ruff" else None
        mock_run.return_value = _ok(stdout="All checks passed!\n")
        ok, output = run_linter(project)
        assert ok is True
        assert "All checks passed" in output

        cmd = mock_run.call_args[0][0]
        assert cmd == ["ruff", "check", "main.py"]

    @patch("nightshift.executor.quality_gates.subprocess.run")
    @patch("nightshift.executor.quality_gates.shutil.which")
    @patch("nightshift.executor.quality_gates.get_changed_files")
    def test_ruff_fails(
        self, mock_changed: MagicMock, mock_which: MagicMock, mock_run: MagicMock, project: Path
    ) -> None:
        project.mkdir(parents=True, exist_ok=True)
        (project / "main.py").touch()
        mock_changed.return_value = ["main.py"]
        mock_which.side_effect = lambda name: "/usr/bin/ruff" if name == "ruff" else None
        mock_run.return_value = _ok(
            stdout="Found 3 errors\n", returncode=1
        )
        ok, output = run_linter(project)
        assert ok is False

    @patch("nightshift.executor.quality_gates.subprocess.run")
    @patch("nightshift.executor.quality_gates.shutil.which")
    @patch("nightshift.executor.quality_gates.get_changed_files")
    def test_falls_back_to_flake8(
        self, mock_changed: MagicMock, mock_which: MagicMock, mock_run: MagicMock, project: Path
    ) -> None:
        project.mkdir(parents=True, exist_ok=True)
        (project / "main.py").touch()
        mock_changed.return_value = ["main.py"]
        mock_which.side_effect = lambda name: (
            "/usr/bin/flake8" if name == "flake8" else None
        )
        mock_run.return_value = _ok(stdout="OK\n")
        ok, output = run_linter(project)
        assert ok is True
        cmd = mock_run.call_args[0][0]
        assert cmd == ["flake8", "main.py"]

    @patch("nightshift.executor.quality_gates.shutil.which", return_value=None)
    @patch("nightshift.executor.quality_gates.get_changed_files")
    def test_no_linter_available(
        self, mock_changed: MagicMock, mock_which: MagicMock, project: Path
    ) -> None:
        project.mkdir(parents=True, exist_ok=True)
        mock_changed.return_value = ["main.py"]
        (project / "main.py").touch()
        ok, output = run_linter(project)
        assert ok is True
        assert "skipped" in output.lower()

    @patch("nightshift.executor.quality_gates.get_changed_files")
    def test_no_changed_files(
        self, mock_changed: MagicMock, project: Path
    ) -> None:
        mock_changed.return_value = []
        ok, output = run_linter(project)
        assert ok is True
        assert "No changed files" in output


# ---------------------------------------------------------------------------
# run_tests_vs_baseline
# ---------------------------------------------------------------------------


class TestRunTestsVsBaseline:
    @patch("nightshift.executor.quality_gates.subprocess.run")
    def test_no_regression(self, mock_run: MagicMock, project: Path) -> None:
        mock_run.return_value = _ok(stdout="10 passed in 2.0s\n")
        ok, msg = run_tests_vs_baseline(project, baseline_passed=8, baseline_failed=0)
        assert ok is True
        assert "OK" in msg

    @patch("nightshift.executor.quality_gates.subprocess.run")
    def test_fewer_passing(self, mock_run: MagicMock, project: Path) -> None:
        mock_run.return_value = _ok(
            stdout="5 passed, 1 failed in 2.0s\n", returncode=1
        )
        ok, msg = run_tests_vs_baseline(project, baseline_passed=8, baseline_failed=0)
        assert ok is False
        assert "passing tests decreased" in msg

    @patch("nightshift.executor.quality_gates.subprocess.run")
    def test_more_failing(self, mock_run: MagicMock, project: Path) -> None:
        mock_run.return_value = _ok(
            stdout="8 passed, 3 failed in 2.0s\n", returncode=1
        )
        ok, msg = run_tests_vs_baseline(project, baseline_passed=8, baseline_failed=1)
        assert ok is False
        assert "failing tests increased" in msg


# ---------------------------------------------------------------------------
# run_all_gates
# ---------------------------------------------------------------------------


class TestRunAllGates:
    @patch("nightshift.executor.quality_gates.run_tests_vs_baseline")
    @patch("nightshift.executor.quality_gates.run_linter")
    @patch("nightshift.executor.quality_gates.check_blast_radius")
    def test_all_pass(
        self,
        mock_blast: MagicMock,
        mock_lint: MagicMock,
        mock_tests: MagicMock,
        project: Path,
    ) -> None:
        mock_blast.return_value = (True, "Blast OK")
        mock_lint.return_value = (True, "Lint OK")
        mock_tests.return_value = (True, "Tests OK")

        limits = ProjectLimits()
        ok, msg = run_all_gates(project, limits, baseline=(10, 0))
        assert ok is True
        assert "Blast OK" in msg
        assert "Lint OK" in msg
        assert "Tests OK" in msg

    @patch("nightshift.executor.quality_gates.run_tests_vs_baseline")
    @patch("nightshift.executor.quality_gates.run_linter")
    @patch("nightshift.executor.quality_gates.check_blast_radius")
    def test_linter_fails(
        self,
        mock_blast: MagicMock,
        mock_lint: MagicMock,
        mock_tests: MagicMock,
        project: Path,
    ) -> None:
        mock_blast.return_value = (True, "Blast OK")
        mock_lint.return_value = (False, "3 errors found")
        mock_tests.return_value = (True, "Tests OK")

        limits = ProjectLimits()
        ok, msg = run_all_gates(project, limits, baseline=(5, 0))
        assert ok is False

    @patch("nightshift.executor.quality_gates.run_linter")
    @patch("nightshift.executor.quality_gates.check_blast_radius")
    def test_skips_test_regression_when_no_baseline(
        self,
        mock_blast: MagicMock,
        mock_lint: MagicMock,
        project: Path,
    ) -> None:
        mock_blast.return_value = (True, "OK")
        mock_lint.return_value = (True, "OK")

        limits = ProjectLimits()
        ok, msg = run_all_gates(project, limits, baseline=(0, 0))
        assert ok is True
