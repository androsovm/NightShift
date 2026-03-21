"""Run result persistence."""

import json
from pathlib import Path

import structlog
from pydantic import ValidationError

from nightshift.models.run import RunResult

log = structlog.get_logger()

RUNS_DIR = Path.home() / ".nightshift" / "runs"
LOGS_DIR = Path.home() / ".nightshift" / "logs"


def save_run(result: RunResult) -> Path:
    """Save a RunResult as JSON to runs/{run_id}.json."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"{result.run_id}.json"
    path.write_text(result.model_dump_json(indent=2))
    return path


def load_run(run_id: str) -> RunResult | None:
    """Load a specific run by its ID."""
    path = RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        return RunResult.model_validate_json(path.read_text())
    except (json.JSONDecodeError, ValidationError):
        log.warning("corrupted_run_file", path=str(path), run_id=run_id)
        return None


def load_latest_run() -> RunResult | None:
    """Find and load the most recent run file."""
    if not RUNS_DIR.exists():
        return None
    files = sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            return RunResult.model_validate_json(path.read_text())
        except (json.JSONDecodeError, ValidationError):
            log.warning("corrupted_run_file", path=str(path))
            continue
    return None


def load_runs(limit: int = 10) -> list[RunResult]:
    """Load the N most recent runs, sorted newest first."""
    if not RUNS_DIR.exists():
        return []
    files = sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    results: list[RunResult] = []
    for path in files[:limit]:
        try:
            results.append(RunResult.model_validate_json(path.read_text()))
        except (json.JSONDecodeError, ValidationError):
            log.warning("corrupted_run_file", path=str(path))
            continue
    return results


def get_log_dir(run_id: str) -> Path:
    """Return the logs/{run_id}/ directory, creating it if needed."""
    log_dir = LOGS_DIR / run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir
