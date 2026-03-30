"""nightshift init / add -- interactive setup wizard."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import questionary
import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from nightshift.config.loader import (
    GLOBAL_CONFIG_PATH,
    load_global_config,
    save_global_config,
    save_project_config,
)
from nightshift.models import (
    GlobalConfig,
    ProjectConfig,
    ProjectLimits,
    ProjectRef,
    ScheduleConfig,
    SourceConfig,
)
from nightshift.models.config import CLAUDE_MODELS, DEFAULT_CLAUDE_MODEL

console = Console()

NIGHTSHIFT_DIR = Path.home() / ".nightshift"

# Nord Aurora colors for Rich markup
_CYAN = "cyan"
_GREEN = "green"
_YELLOW = "yellow"
_DIM = "dim"

# Sentinel for "go back" in wizard steps
_BACK = "__back__"
_ADD_CUSTOM = "__add_custom__"


# ---------------------------------------------------------------------------
# Helpers — must be defined before WizardState
# ---------------------------------------------------------------------------


def _detect_local_timezone() -> str:
    """Detect the local system timezone, e.g. 'Europe/Nicosia'."""
    try:
        import datetime

        local_tz = datetime.datetime.now().astimezone().tzinfo
        if hasattr(local_tz, "key"):
            return local_tz.key  # type: ignore[union-attr]
        # Fallback: read macOS /etc/localtime symlink
        link = os.readlink("/etc/localtime")
        # /var/db/timezone/zoneinfo/Europe/Nicosia → Europe/Nicosia
        if "zoneinfo/" in link:
            return link.split("zoneinfo/")[-1]
    except Exception:
        pass
    return "UTC"


# ---------------------------------------------------------------------------
# Wizard state — collected across steps
# ---------------------------------------------------------------------------


@dataclass
class WizardState:
    """Mutable state bag passed between wizard steps."""

    selected_projects: list[Path] = field(default_factory=list)
    source_results: list[tuple[Path, str, SourceConfig]] = field(default_factory=list)
    limits: ProjectLimits = field(default_factory=ProjectLimits)
    tokens: dict[str, str] = field(default_factory=dict)
    default_model: str = DEFAULT_CLAUDE_MODEL
    schedule_time: str = "03:00"
    timezone: str = field(default_factory=_detect_local_timezone)
    max_duration: int = 4


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------


def _step(current: int, total: int, title: str) -> None:
    """Print a step header like: Step 1/5 · Projects"""
    console.print(f"\n[bold {_CYAN}]Step {current}/{total}[/bold {_CYAN}] · {title}")
    console.print(f"[{_DIM}]{'─' * 50}[/{_DIM}]")


def _shorten_path(p: Path) -> str:
    """~/Projects/foo instead of /Users/name/Projects/foo."""
    home = str(Path.home())
    s = str(p)
    if s.startswith(home):
        return "~" + s[len(home):]
    return s


def _back_choice() -> questionary.Choice:
    """Standard '← Back' choice for select/checkbox prompts."""
    return questionary.Choice(title="← Back", value=_BACK)


def _validate_time(val: str) -> bool | str:
    """Validate HH:MM format or 'back'."""
    v = val.strip()
    if v.lower() == "back":
        return True
    if len(v) != 5 or v[2] != ":":
        return "Use HH:MM format (e.g. 02:00)"
    try:
        h, m = int(v[:2]), int(v[3:])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return True
        return "Hours 00-23, minutes 00-59"
    except ValueError:
        return "Use HH:MM format (e.g. 02:00)"


def _validate_positive_int(val: str) -> bool | str:
    """Validate positive integer or 'back'."""
    v = val.strip()
    if v.lower() == "back":
        return True
    if not v:
        return True  # will use default
    try:
        n = int(v)
        if n > 0:
            return True
        return "Must be a positive number"
    except ValueError:
        return "Must be a number"


def _validate_timezone(val: str) -> bool | str:
    """Basic timezone validation or 'back'."""
    v = val.strip()
    if v.lower() == "back":
        return True
    if not v:
        return True
    # Accept common formats: UTC, Europe/Moscow, US/Eastern, etc.
    if "/" in v or v in ("UTC", "GMT") or v.startswith("Etc/"):
        return True
    return "Use timezone like UTC, Europe/Moscow, US/Eastern"


# ---------------------------------------------------------------------------
# Reusable helpers
# ---------------------------------------------------------------------------


def _scan_git_repos(base: Path) -> list[Path]:
    """Scan a directory for git repositories (up to two levels deep)."""
    repos: list[Path] = []
    if not base.is_dir():
        return repos
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        if (entry / ".git").is_dir():
            repos.append(entry)
        else:
            # Check one level deeper (e.g. Projects/otonfm/otonfm/.git)
            for sub in sorted(entry.iterdir()):
                if sub.is_dir() and (sub / ".git").is_dir():
                    repos.append(sub)
    return repos


def _detect_github_remote(project_path: Path) -> str | None:
    """Try to extract owner/repo from the git remote origin URL."""
    try:
        result = subprocess.run(
            ["git", "-C", str(project_path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        url = result.stdout.strip()
        if not url:
            return None
        if url.startswith("git@"):
            parts = url.split(":")[-1]
            return parts.removesuffix(".git")
        if "github.com" in url:
            parts = url.split("github.com/")[-1]
            return parts.removesuffix(".git")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _source_type_choices(*, with_back: bool = False) -> list[questionary.Choice]:
    """Build choices for available source types."""
    from nightshift.sources import available_sources

    labels = {
        "yaml": "YAML (local task list in .nightshift.yaml)",
        "github": "GitHub Issues (fetch tasks from labeled issues)",
        "youtrack": "YouTrack (fetch tasks by tag)",
        "trello": "Trello (fetch tasks from a board list)",
    }
    choices = [
        questionary.Choice(labels.get(name, name), value=name)
        for name in available_sources()
    ]
    if with_back:
        choices.append(_back_choice())
    return choices


def _configure_source(source_type: str, project_path: Path) -> SourceConfig:
    """Interactively configure a single source."""
    if source_type == "yaml":
        console.print(
            f"  [{_DIM}]Tasks will be read from .nightshift.yaml in the project[/{_DIM}]"
        )
        return SourceConfig(type="yaml")

    if source_type == "github":
        detected = _detect_github_remote(project_path)
        default_repo = detected or ""
        if detected:
            console.print(f"  [{_DIM}]Detected GitHub repo: {detected}[/{_DIM}]")
        repo = questionary.text("GitHub owner/repo:", default=default_repo).ask()
        label = questionary.text(
            "GitHub label to filter issues:", default="nightshift"
        ).ask()
        return SourceConfig(
            type="github",
            repo=repo,
            labels=[label] if label else ["nightshift"],
        )

    if source_type == "youtrack":
        base_url = questionary.text(
            "YouTrack base URL (e.g. https://youtrack.example.com):"
        ).ask()
        project_id = questionary.text("YouTrack project ID:").ask()
        tag = questionary.text("YouTrack tag for tasks:", default="nightshift").ask()
        states_input = questionary.text(
            "Filter by states (comma-separated, e.g. 'Ready for DEV, Open'; empty = all):",
            default="",
        ).ask()
        states = [s.strip() for s in (states_input or "").split(",") if s.strip()]
        return SourceConfig(
            type="youtrack", base_url=base_url, project_id=project_id, tag=tag, states=states
        )

    if source_type == "trello":
        board_id = questionary.text("Trello board ID:").ask()
        list_name = questionary.text(
            "Trello list name for tasks:", default="NightShift Queue"
        ).ask()
        return SourceConfig(type="trello", board_id=board_id, list_name=list_name)

    # Unknown / plugin source
    console.print(f"[{_DIM}]Configuring plugin source: {source_type}[/{_DIM}]")
    options: dict[str, str] = {}
    while True:
        kv = questionary.text(
            f"  Option for '{source_type}' (key=value, empty to finish):"
        ).ask()
        if not kv:
            break
        if "=" in kv:
            k, _, v = kv.partition("=")
            options[k.strip()] = v.strip()
    return SourceConfig(type=source_type, options=options)


def _collect_api_tokens(sources: list[SourceConfig]) -> dict[str, str]:
    """Ask user for API tokens required by the selected sources."""
    from nightshift.config.secrets import get_secret

    tokens: dict[str, str] = {}
    source_types = {s.type for s in sources}

    if "github" in source_types:
        existing = get_secret("GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
        if existing:
            console.print(f"[{_DIM}]GITHUB_TOKEN already configured.[/{_DIM}]")
            replace = questionary.confirm(
                "Replace existing GITHUB_TOKEN?", default=False
            ).ask()
            if replace:
                console.print(
                    f"[{_DIM}]Create at: github.com/settings/tokens → "
                    f"Fine-grained → repo:issues (read)[/{_DIM}]"
                )
                token = questionary.password("GitHub personal access token:").ask()
                if token:
                    tokens["GITHUB_TOKEN"] = token
        else:
            console.print(
                f"[{_DIM}]Create at: github.com/settings/tokens → "
                f"Fine-grained → repo:issues (read)\n"
                f"Press Enter to skip — you can add it later in ~/.nightshift/.env[/{_DIM}]"
            )
            token = questionary.password("GitHub personal access token:").ask()
            if token:
                tokens["GITHUB_TOKEN"] = token

    if "youtrack" in source_types:
        existing = get_secret("YOUTRACK_TOKEN")
        if existing:
            console.print(f"[{_DIM}]YOUTRACK_TOKEN already configured.[/{_DIM}]")
            replace = questionary.confirm(
                "Replace existing YOUTRACK_TOKEN?", default=False
            ).ask()
            if replace:
                token = questionary.password("YouTrack API token:").ask()
                if token:
                    tokens["YOUTRACK_TOKEN"] = token
        else:
            console.print(
                f"[{_DIM}]Create at: YouTrack → Profile → Authentication → New token\n"
                f"Press Enter to skip[/{_DIM}]"
            )
            token = questionary.password("YouTrack API token:").ask()
            if token:
                tokens["YOUTRACK_TOKEN"] = token

    if "trello" in source_types:
        existing_key = get_secret("TRELLO_API_KEY")
        if existing_key:
            console.print(f"[{_DIM}]Trello tokens already configured.[/{_DIM}]")
            replace = questionary.confirm(
                "Replace existing Trello tokens?", default=False
            ).ask()
            if replace:
                key = questionary.password("Trello API key:").ask()
                token = questionary.password("Trello API token:").ask()
                if key:
                    tokens["TRELLO_API_KEY"] = key
                if token:
                    tokens["TRELLO_TOKEN"] = token
        else:
            console.print(
                f"[{_DIM}]Create at: trello.com/power-ups/admin → API Key\n"
                f"Press Enter to skip[/{_DIM}]"
            )
            key = questionary.password("Trello API key:").ask()
            token = questionary.password("Trello API token:").ask()
            if key:
                tokens["TRELLO_API_KEY"] = key
            if token:
                tokens["TRELLO_TOKEN"] = token

    return tokens


def _save_env(tokens: dict[str, str]) -> None:
    """Save tokens via the secrets module."""
    from nightshift.config.secrets import SECRETS_PATH, save_secret

    for key, value in tokens.items():
        save_secret(key, value)
    console.print(f"[{_GREEN}]Saved tokens to {SECRETS_PATH}[/{_GREEN}]")


# ---------------------------------------------------------------------------
# Wizard steps — each returns True (continue) or False (go back)
# ---------------------------------------------------------------------------


def _step1_projects(state: WizardState) -> bool:
    """Step 1: Select projects."""
    _step(1, TOTAL_STEPS, "Select projects")
    console.print(
        f"[{_DIM}]Select repos from ~/Projects or add custom paths.\n"
        f"Use Space to toggle, Enter to confirm.[/{_DIM}]"
    )

    default_dir = Path.home() / "Projects"
    repos: list[Path] = []

    if default_dir.is_dir():
        found = _scan_git_repos(default_dir)
        repos.extend(found)
        if found:
            console.print(f"[{_DIM}]Found {len(found)} git repos in ~/Projects[/{_DIM}]")
        else:
            console.print(f"[{_YELLOW}]No git repos found in ~/Projects[/{_YELLOW}]")

    selected: set[Path] = {p for p in state.selected_projects if p in repos}

    while True:
        choices: list[questionary.Choice] = []
        for r in repos:
            choices.append(
                questionary.Choice(
                    title=f"{r.name}  [{_shorten_path(r)}]",
                    value=str(r),
                    checked=r in selected,
                )
            )
        choices.append(
            questionary.Choice(title="+ Add custom path...", value=_ADD_CUSTOM)
        )

        result: list[str] = questionary.checkbox(
            "Select projects (Space to toggle, Enter to confirm):",
            choices=choices,
        ).ask()

        if result is None:
            return False

        if _ADD_CUSTOM in result:
            selected = {Path(r) for r in result if r != _ADD_CUSTOM}
            custom = questionary.path(
                "Path to project or directory to scan:", only_directories=True
            ).ask()
            if custom:
                custom_path = Path(custom).expanduser().resolve()
                if (custom_path / ".git").is_dir():
                    if custom_path not in repos:
                        repos.append(custom_path)
                        selected.add(custom_path)
                        console.print(f"  [{_GREEN}]+[/{_GREEN}] {custom_path.name}")
                    else:
                        console.print(
                            f"  [{_DIM}]Already in list: {custom_path.name}[/{_DIM}]"
                        )
                elif custom_path.is_dir():
                    found = _scan_git_repos(custom_path)
                    for r in found:
                        if r not in repos:
                            repos.append(r)
                            selected.add(r)
                            console.print(f"  [{_GREEN}]+[/{_GREEN}] {r.name}")
                    if not found:
                        console.print(
                            f"  [{_YELLOW}]No git repos in {custom_path}[/{_YELLOW}]"
                        )
                else:
                    console.print(f"  [red]Not a directory: {custom_path}[/red]")
            continue

        picked = [Path(r) for r in result]
        if not picked:
            console.print(f"[{_YELLOW}]No projects selected. Select at least one.[/{_YELLOW}]")
            continue

        state.selected_projects = picked
        console.print(f"  [{_GREEN}]{len(picked)} project(s) selected[/{_GREEN}]")
        return True


def _step2_sources(state: WizardState) -> bool:
    """Step 2: Configure task sources per project."""
    _step(2, TOTAL_STEPS, "Configure task sources")
    console.print(
        f"[{_DIM}]For each project, choose where NightShift finds tasks.\n"
        f"YAML is simplest — define tasks in .nightshift.yaml.\n"
        f"GitHub/YouTrack/Trello fetch tasks from your tracker.[/{_DIM}]"
    )

    source_results: list[tuple[Path, str, SourceConfig]] = []

    for i, project_path in enumerate(state.selected_projects):
        console.print(
            f"\n  [{_CYAN}]Configuring[/{_CYAN}] [bold]{project_path.name}[/bold]"
            f" [{_DIM}]({i + 1}/{len(state.selected_projects)})[/{_DIM}]"
        )

        selected_source: str | None = questionary.select(
            f"Task source for {project_path.name}:",
            choices=_source_type_choices(with_back=True),
        ).ask()

        if selected_source == _BACK:
            return False

        if not selected_source:
            console.print(
                f"  [{_YELLOW}]Skipping {project_path.name}[/{_YELLOW}]"
            )
            continue

        src = _configure_source(selected_source, project_path)
        source_results.append((project_path, selected_source, src))

    if not source_results:
        console.print(f"[{_YELLOW}]No projects configured.[/{_YELLOW}]")
        return False

    state.source_results = source_results
    return True


def _step3_limits(state: WizardState) -> bool:
    """Step 3: Safety limits."""
    _step(3, TOTAL_STEPS, "Safety limits")
    console.print(
        f"[{_DIM}]Safety limits for Claude Code runs. Press Enter for defaults.\n"
        f"Type 'back' in any field to return to the previous step.[/{_DIM}]"
    )

    defaults = state.limits
    fields = [
        ("Max tasks per run per project:", "max_tasks_per_run"),
        ("Task timeout (minutes):", "task_timeout_minutes"),
        ("Max files changed per task:", "max_files_changed"),
        ("Max lines changed per task:", "max_lines_changed"),
    ]

    values: dict[str, int] = {}
    for prompt_text, field_name in fields:
        answer = questionary.text(
            prompt_text,
            default=str(getattr(defaults, field_name)),
            validate=_validate_positive_int,
        ).ask()
        if answer and answer.strip().lower() == "back":
            return False
        values[field_name] = int(answer) if answer else getattr(defaults, field_name)

    state.limits = ProjectLimits(**values)

    # Default model for Claude Code
    console.print(f"\n[{_DIM}]Which Claude model should NightShift use by default?[/{_DIM}]")
    model = questionary.select(
        "Default model:",
        choices=[
            questionary.Choice(m, value=m)
            for m in CLAUDE_MODELS
        ],
        default=state.default_model,
    ).ask()
    if model == _BACK:
        return False
    state.default_model = model or DEFAULT_CLAUDE_MODEL

    return True


def _step4_tokens(state: WizardState) -> bool:
    """Step 4: API tokens."""
    all_sources = [src for _, _, src in state.source_results]
    remote_sources = {s.type for s in all_sources} - {"yaml"}

    _step(4, TOTAL_STEPS, "API tokens")

    if not remote_sources:
        console.print(f"[{_DIM}]No remote sources — no tokens needed.[/{_DIM}]")
        # Offer back
        action = questionary.select(
            "Continue?",
            choices=[
                questionary.Choice("Continue to schedule →", value="continue"),
                _back_choice(),
            ],
        ).ask()
        return action != _BACK

    console.print(
        f"[{_DIM}]Tokens are stored in ~/.nightshift/.env (chmod 600).\n"
        f"Type 'back' to return to the previous step.[/{_DIM}]"
    )
    tokens = _collect_api_tokens(all_sources)
    state.tokens = tokens
    return True


def _step5_schedule(state: WizardState) -> bool:
    """Step 5: Schedule."""
    _step(5, TOTAL_STEPS, "Schedule")
    console.print(
        f"[{_DIM}]When should NightShift run automatically?\n"
        f"Local timezone detected: [{_CYAN}]{state.timezone}[/{_CYAN}]\n"
        f"You can install the schedule later with: nightshift install\n"
        f"Type 'back' in any field to return to the previous step.[/{_DIM}]"
    )

    # Run time + timezone on one line for clarity
    answer = questionary.text(
        f"Run time (HH:MM, your local time in {state.timezone}):",
        default=state.schedule_time,
        validate=_validate_time,
    ).ask()
    if answer and answer.strip().lower() == "back":
        return False
    schedule_time = answer or state.schedule_time

    # Timezone — only ask if user wants to change
    answer = questionary.text(
        "Timezone (Enter to keep):",
        default=state.timezone,
        validate=_validate_timezone,
    ).ask()
    if answer and answer.strip().lower() == "back":
        return False
    timezone = answer or state.timezone

    # Max duration
    answer = questionary.text(
        "Max run duration (hours):",
        default=str(state.max_duration),
        validate=_validate_positive_int,
    ).ask()
    if answer and answer.strip().lower() == "back":
        return False
    max_duration = int(answer) if answer else state.max_duration

    state.schedule_time = schedule_time
    state.timezone = timezone
    state.max_duration = max_duration
    return True


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

TOTAL_STEPS = 5

# Step functions in order. Each takes WizardState, returns True (forward) or False (back).
_STEPS = [_step1_projects, _step2_sources, _step3_limits, _step4_tokens, _step5_schedule]


def init() -> None:
    """Interactive setup wizard for NightShift."""
    console.print(
        Panel(
            "[bold cyan]NightShift Setup Wizard[/bold cyan]\n\n"
            "NightShift runs Claude Code overnight to close tech debt.\n"
            "It picks tasks from your queue, creates branches, runs Claude,\n"
            "validates changes, and opens draft PRs for your review.\n\n"
            "[dim]This wizard will walk you through 5 steps:\n"
            "  1. Select projects    — which repos to work on\n"
            "  2. Configure sources  — where tasks come from\n"
            "  3. Set safety limits  — max files, timeout, etc.\n"
            "  4. API tokens         — for GitHub/YouTrack/Trello\n"
            "  5. Schedule           — when to run automatically\n\n"
            "You can go back at any step.[/dim]",
            expand=False,
            border_style="cyan",
        )
    )

    state = WizardState()
    step_idx = 0

    while step_idx < len(_STEPS):
        ok = _STEPS[step_idx](state)
        if ok:
            step_idx += 1
        else:
            if step_idx == 0:
                console.print(f"[{_YELLOW}]Exiting wizard.[/{_YELLOW}]")
                raise typer.Exit(0)
            step_idx -= 1

    # ── Save ──────────────────────────────────────────────────────────
    schedule = ScheduleConfig(
        time=state.schedule_time,
        timezone=state.timezone,
        max_duration_hours=state.max_duration,
    )

    project_refs: list[ProjectRef] = []
    project_configs: dict[Path, ProjectConfig] = {}

    for project_path, selected_source, src in state.source_results:
        pc = ProjectConfig(sources=[src], limits=state.limits, default_model=state.default_model)
        ref = ProjectRef(path=project_path, sources=[selected_source])
        project_refs.append(ref)
        project_configs[project_path] = pc

    global_config = GlobalConfig(
        schedule=schedule,
        projects=project_refs,
        max_prs_per_night=state.limits.max_tasks_per_run * len(project_refs),
    )
    save_global_config(global_config)

    for project_path, pc in project_configs.items():
        save_project_config(project_path, pc)

    if state.tokens:
        _save_env(state.tokens)

    # ── Summary ───────────────────────────────────────────────────────
    summary = Text()
    summary.append("Projects:\n", style="bold")
    for ref in project_refs:
        summary.append(f"  {ref.path.name}", style="cyan")
        summary.append(f"  [{', '.join(ref.sources)}]\n", style="dim")
    summary.append(f"\nSchedule: ", style="bold")
    summary.append(f"{schedule.time} {schedule.timezone}\n")
    summary.append(f"Model: ", style="bold")
    summary.append(f"{state.default_model}\n")
    summary.append(f"Limits: ", style="bold")
    summary.append(
        f"{state.limits.max_tasks_per_run} tasks/run, "
        f"{state.limits.task_timeout_minutes}min timeout, "
        f"{state.limits.max_files_changed} files max\n"
    )
    summary.append(f"\nConfig: ", style="bold")
    summary.append(f"{GLOBAL_CONFIG_PATH}\n", style="dim")

    console.print(
        Panel(
            summary,
            title="[bold green]Setup complete[/bold green]",
            border_style="green",
            expand=False,
        )
    )

    console.print(
        f"\n[bold]Next steps:[/bold]\n"
        f"  [{_CYAN}]nightshift doctor[/{_CYAN}]        verify your environment\n"
        f"  [{_CYAN}]nightshift run --dry-run[/{_CYAN}] preview what would happen\n"
        f"  [{_CYAN}]nightshift install[/{_CYAN}]       set up automatic scheduling\n"
        f"  [{_CYAN}]nightshift[/{_CYAN}]               open TUI dashboard\n"
        f"\n[{_DIM}]To add more projects later: nightshift add[/{_DIM}]"
    )


def add() -> None:
    """Add a project to an existing NightShift configuration."""
    if not GLOBAL_CONFIG_PATH.exists():
        console.print(
            "[red]NightShift not initialized.[/red]\n"
            f"[{_DIM}]Run 'nightshift init' first to set up.[/{_DIM}]"
        )
        raise typer.Exit(1)

    global_config = load_global_config()
    existing_paths = {ref.path.resolve() for ref in global_config.projects}

    console.print(
        Panel(
            "[bold cyan]Add Project[/bold cyan]\n\n"
            f"Currently configured: {len(existing_paths)} project(s)\n"
            f"[{_DIM}]Add a git repository to NightShift's project list.[/{_DIM}]",
            expand=False,
            border_style="cyan",
        )
    )

    # --- Pick project path ---
    project_input = questionary.path(
        "Path to project (git repo):", only_directories=True
    ).ask()
    if not project_input:
        raise typer.Abort()

    project_path = Path(project_input).expanduser().resolve()

    if not (project_path / ".git").is_dir():
        console.print(f"[red]Not a git repository: {project_path}[/red]")
        raise typer.Exit(1)

    if project_path in existing_paths:
        console.print(
            f"[{_YELLOW}]{project_path.name} is already configured.[/{_YELLOW}]"
        )
        reconfigure = questionary.confirm("Reconfigure it?", default=False).ask()
        if not reconfigure:
            raise typer.Exit(0)
        global_config.projects = [
            ref
            for ref in global_config.projects
            if ref.path.resolve() != project_path
        ]

    # --- Limits ---
    if global_config.projects:
        from nightshift.config.loader import load_project_config

        existing_pc = load_project_config(global_config.projects[0].path)
        limits = existing_pc.limits
        console.print(
            f"[{_DIM}]Using existing limits: "
            f"{limits.max_tasks_per_run} tasks/run, "
            f"{limits.task_timeout_minutes}min timeout[/{_DIM}]"
        )
        customize = questionary.confirm(
            "Customize limits for this project?", default=False
        ).ask()
        if customize:
            defaults = ProjectLimits()
            max_tasks = questionary.text(
                "Max tasks per run:", default=str(limits.max_tasks_per_run)
            ).ask()
            task_timeout = questionary.text(
                "Task timeout (minutes):", default=str(limits.task_timeout_minutes)
            ).ask()
            max_files = questionary.text(
                "Max files changed:", default=str(limits.max_files_changed)
            ).ask()
            max_lines = questionary.text(
                "Max lines changed:", default=str(limits.max_lines_changed)
            ).ask()
            limits = ProjectLimits(
                max_tasks_per_run=int(max_tasks) if max_tasks else limits.max_tasks_per_run,
                task_timeout_minutes=int(task_timeout) if task_timeout else limits.task_timeout_minutes,
                max_files_changed=int(max_files) if max_files else limits.max_files_changed,
                max_lines_changed=int(max_lines) if max_lines else limits.max_lines_changed,
            )
    else:
        limits = ProjectLimits()

    # --- Source ---
    console.print(
        f"\n  [{_DIM}]Where should NightShift find tasks for {project_path.name}?[/{_DIM}]"
    )
    selected_source: str | None = questionary.select(
        f"Task source for {project_path.name}:",
        choices=_source_type_choices(),
    ).ask()
    if not selected_source:
        raise typer.Exit(0)

    src = _configure_source(selected_source, project_path)

    # --- API tokens ---
    if selected_source != "yaml":
        tokens = _collect_api_tokens([src])
        if tokens:
            _save_env(tokens)

    # --- Save ---
    pc = ProjectConfig(sources=[src], limits=limits)
    ref = ProjectRef(path=project_path, sources=[selected_source])
    global_config.projects.append(ref)
    save_global_config(global_config)
    save_project_config(project_path, pc)

    console.print(
        Panel(
            f"[bold green]Added {project_path.name}[/bold green]\n\n"
            f"Source: {selected_source}\n"
            f"\n[{_DIM}]Run: nightshift run --dry-run -p {project_path.name}[/{_DIM}]",
            expand=False,
            border_style="green",
        )
    )
