"""nightshift init -- interactive setup wizard."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import questionary
import typer
import yaml
from rich.console import Console
from rich.panel import Panel

from nightshift.models import (
    GlobalConfig,
    ProjectConfig,
    ProjectLimits,
    ProjectRef,
    ScheduleConfig,
    SourceConfig,
)

console = Console()

NIGHTSHIFT_DIR = Path.home() / ".nightshift"
GLOBAL_CONFIG_PATH = NIGHTSHIFT_DIR / "config.yaml"


def _scan_git_repos(base: Path) -> list[Path]:
    """Scan a directory for git repositories (one level deep)."""
    repos: list[Path] = []
    if not base.is_dir():
        return repos
    for entry in sorted(base.iterdir()):
        if entry.is_dir() and (entry / ".git").is_dir():
            repos.append(entry)
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
        # Handle SSH: git@github.com:owner/repo.git
        if url.startswith("git@"):
            parts = url.split(":")[-1]
            return parts.removesuffix(".git")
        # Handle HTTPS: https://github.com/owner/repo.git
        if "github.com" in url:
            parts = url.split("github.com/")[-1]
            return parts.removesuffix(".git")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _configure_source(source_type: str, project_path: Path) -> SourceConfig:
    """Interactively configure a single source."""
    if source_type == "yaml":
        return SourceConfig(type="yaml")

    if source_type == "github":
        detected = _detect_github_remote(project_path)
        default_repo = detected or ""
        repo = questionary.text(
            "GitHub owner/repo:",
            default=default_repo,
        ).ask()
        label = questionary.text(
            "GitHub label for NightShift tasks:",
            default="nightshift",
        ).ask()
        return SourceConfig(
            type="github",
            repo=repo,
            labels=[label] if label else ["nightshift"],
        )

    if source_type == "youtrack":
        base_url = questionary.text("YouTrack base URL (e.g. https://youtrack.example.com):").ask()
        project_id = questionary.text("YouTrack project ID:").ask()
        tag = questionary.text("YouTrack tag for tasks:", default="nightshift").ask()
        return SourceConfig(
            type="youtrack",
            base_url=base_url,
            project_id=project_id,
            tag=tag,
        )

    if source_type == "trello":
        board_id = questionary.text("Trello board ID:").ask()
        list_name = questionary.text(
            "Trello list name for tasks:",
            default="NightShift Queue",
        ).ask()
        return SourceConfig(
            type="trello",
            board_id=board_id,
            list_name=list_name,
        )

    # Unknown / plugin source — collect generic key=value options
    console.print(f"[dim]Configuring plugin source: {source_type}[/dim]")
    options: dict[str, str] = {}
    while True:
        kv = questionary.text(
            f"  Option for '{source_type}' (key=value, empty to finish):",
        ).ask()
        if not kv:
            break
        if "=" in kv:
            k, _, v = kv.partition("=")
            options[k.strip()] = v.strip()
    return SourceConfig(type=source_type, options=options)


def _collect_api_tokens(sources: list[SourceConfig]) -> dict[str, str]:
    """Ask user for API tokens required by the selected sources."""
    tokens: dict[str, str] = {}
    source_types = {s.type for s in sources}

    if "github" in source_types and "GITHUB_TOKEN" not in tokens:
        existing = os.environ.get("GITHUB_TOKEN", "")
        if existing:
            console.print("[dim]GITHUB_TOKEN detected in environment.[/dim]")
            use_existing = questionary.confirm(
                "Use existing GITHUB_TOKEN from environment?", default=True
            ).ask()
            if use_existing:
                tokens["GITHUB_TOKEN"] = existing
        if "GITHUB_TOKEN" not in tokens:
            token = questionary.password("GitHub personal access token:").ask()
            if token:
                tokens["GITHUB_TOKEN"] = token

    if "youtrack" in source_types:
        token = questionary.password("YouTrack API token:").ask()
        if token:
            tokens["YOUTRACK_TOKEN"] = token

    if "trello" in source_types:
        key = questionary.password("Trello API key:").ask()
        token = questionary.password("Trello API token:").ask()
        if key:
            tokens["TRELLO_API_KEY"] = key
        if token:
            tokens["TRELLO_TOKEN"] = token

    return tokens


def _save_env(tokens: dict[str, str]) -> None:
    """Save tokens via the secrets module (ensures proper quoting and chmod 600)."""
    from nightshift.config.secrets import SECRETS_PATH, save_secret

    for key, value in tokens.items():
        save_secret(key, value)
    console.print(f"[green]Saved tokens to {SECRETS_PATH}[/green]")


def _save_global_config(config: GlobalConfig) -> None:
    """Write ~/.nightshift/config.yaml."""
    NIGHTSHIFT_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "schedule": {
            "time": config.schedule.time,
            "timezone": config.schedule.timezone,
            "max_duration_hours": config.schedule.max_duration_hours,
        },
        "projects": [
            {
                "path": str(p.path),
                "sources": [str(s) for s in p.sources],
            }
            for p in config.projects
        ],
        "max_prs_per_night": config.max_prs_per_night,
    }
    GLOBAL_CONFIG_PATH.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    console.print(f"[green]Saved global config to {GLOBAL_CONFIG_PATH}[/green]")


def _save_project_config(project_path: Path, config: ProjectConfig) -> None:
    """Write .nightshift.yaml into the project directory."""
    out = project_path / ".nightshift.yaml"
    data: dict = {
        "sources": [],
        "limits": {
            "max_tasks_per_run": config.limits.max_tasks_per_run,
            "task_timeout_minutes": config.limits.task_timeout_minutes,
            "max_files_changed": config.limits.max_files_changed,
            "max_lines_changed": config.limits.max_lines_changed,
        },
    }
    for s in config.sources:
        src: dict = {"type": str(s.type)}
        if s.type == "github":
            src["repo"] = s.repo
            src["labels"] = s.labels
        elif s.type == "youtrack":
            src["base_url"] = s.base_url
            src["project_id"] = s.project_id
            src["tag"] = s.tag
        elif s.type == "trello":
            src["board_id"] = s.board_id
            src["list_name"] = s.list_name
        if s.options:
            src["options"] = s.options
        data["sources"].append(src)
    if config.claude_system_prompt:
        data["claude_system_prompt"] = config.claude_system_prompt
    out.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    console.print(f"[green]Saved project config to {out}[/green]")


def init() -> None:
    """Interactive setup wizard for NightShift."""
    console.print(
        Panel(
            "[bold cyan]NightShift Init Wizard[/bold cyan]\n"
            "This will configure NightShift for your projects.",
            expand=False,
        )
    )

    # --- Scan for projects ---
    projects_dir = Path.home() / "Projects"
    scan_dir = questionary.text(
        "Directory to scan for git repos:",
        default=str(projects_dir),
    ).ask()
    if scan_dir is None:
        raise typer.Abort()

    repos = _scan_git_repos(Path(scan_dir))
    if not repos:
        console.print(f"[red]No git repositories found in {scan_dir}[/red]")
        raise typer.Exit(1)

    choices = [questionary.Choice(title=str(r.name), value=r) for r in repos]
    selected_projects: list[Path] = questionary.checkbox(
        "Select projects to configure:",
        choices=choices,
    ).ask()
    if not selected_projects:
        console.print("[yellow]No projects selected. Exiting.[/yellow]")
        raise typer.Exit(0)

    # --- Configure each project ---
    from nightshift.sources import available_sources

    _SOURCE_LABELS = {
        "yaml": "YAML (local task list)",
        "github": "GitHub Issues",
        "youtrack": "YouTrack",
        "trello": "Trello",
    }
    source_type_choices = [
        questionary.Choice(
            _SOURCE_LABELS.get(name, name),
            value=name,
        )
        for name in available_sources()
    ]

    project_refs: list[ProjectRef] = []
    project_configs: dict[Path, ProjectConfig] = {}
    all_sources: list[SourceConfig] = []

    for project_path in selected_projects:
        console.print(f"\n[bold]Configuring [cyan]{project_path.name}[/cyan][/bold]")

        selected_sources: list[str] = questionary.checkbox(
            f"Task sources for {project_path.name}:",
            choices=source_type_choices,
        ).ask()
        if not selected_sources:
            console.print(f"[yellow]Skipping {project_path.name} (no sources).[/yellow]")
            continue

        sources: list[SourceConfig] = []
        for st in selected_sources:
            src = _configure_source(st, project_path)
            sources.append(src)
            all_sources.append(src)

        pc = ProjectConfig(
            sources=sources,
            limits=ProjectLimits(),
        )
        project_configs[project_path] = pc
        project_refs.append(
            ProjectRef(path=project_path, sources=list(selected_sources))
        )

    if not project_refs:
        console.print("[yellow]No projects configured.[/yellow]")
        raise typer.Exit(0)

    # --- API tokens ---
    console.print("\n[bold]API Tokens[/bold]")
    tokens = _collect_api_tokens(all_sources)
    if tokens:
        _save_env(tokens)

    # --- Schedule ---
    console.print("\n[bold]Schedule[/bold]")
    schedule_time = questionary.text(
        "Run time (HH:MM, 24h format):", default="04:00"
    ).ask()
    timezone = questionary.text("Timezone:", default="UTC").ask()
    max_duration = questionary.text(
        "Max run duration (hours):", default="4"
    ).ask()

    schedule = ScheduleConfig(
        time=schedule_time or "04:00",
        timezone=timezone or "UTC",
        max_duration_hours=int(max_duration) if max_duration else 4,
    )

    # --- Save configs ---
    global_config = GlobalConfig(
        schedule=schedule,
        projects=project_refs,
    )
    _save_global_config(global_config)

    for project_path, pc in project_configs.items():
        _save_project_config(project_path, pc)

    # --- Next steps ---
    console.print(
        Panel(
            "[bold green]Setup complete![/bold green]\n\n"
            "Suggested next steps:\n"
            "  1. [cyan]nightshift doctor[/cyan]   - verify your environment\n"
            "  2. [cyan]nightshift run --dry-run[/cyan] - preview what would happen\n"
            "  3. [cyan]nightshift install[/cyan]  - set up automatic scheduling",
            expand=False,
        )
    )
