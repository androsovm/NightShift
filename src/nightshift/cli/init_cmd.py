"""nightshift init / add -- interactive setup wizard."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import questionary
import typer
import yaml
from rich.console import Console
from rich.panel import Panel

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

console = Console()

NIGHTSHIFT_DIR = Path.home() / ".nightshift"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scan_git_repos(base: Path) -> list[Path]:
    """Scan a directory for git repositories (one level deep)."""
    repos: list[Path] = []
    if not base.is_dir():
        return repos
    for entry in sorted(base.iterdir()):
        if entry.is_dir() and (entry / ".git").is_dir():
            repos.append(entry)
    return repos


def _collect_repo_paths() -> list[Path]:
    """Scan ~/Projects by default, then let user add custom paths."""
    default_dir = Path.home() / "Projects"
    repos: list[Path] = []

    if default_dir.is_dir():
        repos.extend(_scan_git_repos(default_dir))

    while True:
        add_more = questionary.confirm(
            "Add a custom project path?",
            default=False,
        ).ask()
        if not add_more:
            break

        custom = questionary.path(
            "Path to project or directory to scan:",
            only_directories=True,
        ).ask()
        if not custom:
            continue

        custom_path = Path(custom).expanduser().resolve()
        if (custom_path / ".git").is_dir():
            if custom_path not in repos:
                repos.append(custom_path)
                console.print(f"  [green]+[/green] {custom_path}")
        elif custom_path.is_dir():
            found = _scan_git_repos(custom_path)
            for r in found:
                if r not in repos:
                    repos.append(r)
                    console.print(f"  [green]+[/green] {r}")
            if not found:
                console.print(f"  [yellow]No git repos found in {custom_path}[/yellow]")
        else:
            console.print(f"  [red]Not a directory: {custom_path}[/red]")

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
            "GitHub label for tasks:",
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
    from nightshift.config.secrets import get_secret

    tokens: dict[str, str] = {}
    source_types = {s.type for s in sources}

    if "github" in source_types:
        existing = get_secret("GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
        if existing:
            console.print("[dim]GITHUB_TOKEN already configured.[/dim]")
            replace = questionary.confirm(
                "Replace existing GITHUB_TOKEN?", default=False
            ).ask()
            if not replace:
                pass
            else:
                token = questionary.password("GitHub personal access token:").ask()
                if token:
                    tokens["GITHUB_TOKEN"] = token
        else:
            token = questionary.password("GitHub personal access token:").ask()
            if token:
                tokens["GITHUB_TOKEN"] = token

    if "youtrack" in source_types:
        existing = get_secret("YOUTRACK_TOKEN")
        if existing:
            console.print("[dim]YOUTRACK_TOKEN already configured.[/dim]")
            replace = questionary.confirm(
                "Replace existing YOUTRACK_TOKEN?", default=False
            ).ask()
            if replace:
                token = questionary.password("YouTrack API token:").ask()
                if token:
                    tokens["YOUTRACK_TOKEN"] = token
        else:
            token = questionary.password("YouTrack API token:").ask()
            if token:
                tokens["YOUTRACK_TOKEN"] = token

    if "trello" in source_types:
        existing_key = get_secret("TRELLO_API_KEY")
        if existing_key:
            console.print("[dim]Trello tokens already configured.[/dim]")
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


def _configure_limits() -> ProjectLimits:
    """Interactively configure global project limits."""
    defaults = ProjectLimits()

    console.print("\n[bold]Global Limits[/bold]")
    console.print("[dim]These apply to all projects. Press Enter for defaults.[/dim]")

    max_tasks = questionary.text(
        f"Max tasks per run per project:",
        default=str(defaults.max_tasks_per_run),
    ).ask()
    task_timeout = questionary.text(
        f"Task timeout (minutes):",
        default=str(defaults.task_timeout_minutes),
    ).ask()
    max_files = questionary.text(
        f"Max files changed per task:",
        default=str(defaults.max_files_changed),
    ).ask()
    max_lines = questionary.text(
        f"Max lines changed per task:",
        default=str(defaults.max_lines_changed),
    ).ask()

    return ProjectLimits(
        max_tasks_per_run=int(max_tasks) if max_tasks else defaults.max_tasks_per_run,
        task_timeout_minutes=int(task_timeout) if task_timeout else defaults.task_timeout_minutes,
        max_files_changed=int(max_files) if max_files else defaults.max_files_changed,
        max_lines_changed=int(max_lines) if max_lines else defaults.max_lines_changed,
    )


def _source_type_choices() -> list[questionary.Choice]:
    """Build checkbox choices for available source types."""
    from nightshift.sources import available_sources

    labels = {
        "yaml": "YAML (local task list)",
        "github": "GitHub Issues",
        "youtrack": "YouTrack",
        "trello": "Trello",
    }
    return [
        questionary.Choice(labels.get(name, name), value=name)
        for name in available_sources()
    ]


def _configure_project(
    project_path: Path,
    limits: ProjectLimits,
) -> tuple[ProjectRef, ProjectConfig, list[SourceConfig]] | None:
    """Interactively configure a single project. Returns None if skipped."""
    console.print(f"\n[bold]Configuring [cyan]{project_path.name}[/cyan][/bold]")

    selected_sources: list[str] = questionary.checkbox(
        f"Task sources for {project_path.name}:",
        choices=_source_type_choices(),
    ).ask()
    if not selected_sources:
        console.print(f"[yellow]Skipping {project_path.name} (no sources).[/yellow]")
        return None

    sources: list[SourceConfig] = []
    for st in selected_sources:
        src = _configure_source(st, project_path)
        sources.append(src)

    pc = ProjectConfig(sources=sources, limits=limits)
    ref = ProjectRef(path=project_path, sources=list(selected_sources))
    return ref, pc, sources


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def init() -> None:
    """Interactive setup wizard for NightShift."""
    console.print(
        Panel(
            "[bold cyan]NightShift Init Wizard[/bold cyan]\n"
            "This will configure NightShift for your projects.",
            expand=False,
        )
    )

    # --- Discover projects ---
    repos = _collect_repo_paths()
    if not repos:
        console.print("[red]No git repositories found.[/red]")
        raise typer.Exit(1)

    choices = [questionary.Choice(title=str(r), value=r) for r in repos]
    selected_projects: list[Path] = questionary.checkbox(
        "Select projects to configure:",
        choices=choices,
    ).ask()
    if not selected_projects:
        console.print("[yellow]No projects selected. Exiting.[/yellow]")
        raise typer.Exit(0)

    # --- Global limits ---
    limits = _configure_limits()

    # --- Configure each project ---
    project_refs: list[ProjectRef] = []
    project_configs: dict[Path, ProjectConfig] = {}
    all_sources: list[SourceConfig] = []

    for project_path in selected_projects:
        result = _configure_project(project_path, limits)
        if result is None:
            continue
        ref, pc, sources = result
        project_refs.append(ref)
        project_configs[project_path] = pc
        all_sources.extend(sources)

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
        "Run time (HH:MM, 24h format):", default="02:00"
    ).ask()
    timezone = questionary.text("Timezone:", default="UTC").ask()
    max_duration = questionary.text(
        "Max run duration (hours):", default="4"
    ).ask()
    max_prs = questionary.text(
        "Max PRs per night (across all projects):", default="10"
    ).ask()

    schedule = ScheduleConfig(
        time=schedule_time or "02:00",
        timezone=timezone or "UTC",
        max_duration_hours=int(max_duration) if max_duration else 4,
    )

    # --- Save configs ---
    global_config = GlobalConfig(
        schedule=schedule,
        projects=project_refs,
        max_prs_per_night=int(max_prs) if max_prs else 10,
    )
    save_global_config(global_config)
    console.print(f"[green]Saved global config to {GLOBAL_CONFIG_PATH}[/green]")

    for project_path, pc in project_configs.items():
        save_project_config(project_path, pc)
        console.print(f"[green]Saved project config to {project_path / '.nightshift.yaml'}[/green]")

    # --- Next steps ---
    console.print(
        Panel(
            "[bold green]Setup complete![/bold green]\n\n"
            "Next steps:\n"
            "  1. [cyan]nightshift doctor[/cyan]   - verify your environment\n"
            "  2. [cyan]nightshift run --dry-run[/cyan] - preview what would happen\n"
            "  3. [cyan]nightshift install[/cyan]  - set up automatic scheduling\n\n"
            "[dim]To add more projects later: nightshift add[/dim]",
            expand=False,
        )
    )


def add() -> None:
    """Add a project to an existing NightShift configuration."""
    if not GLOBAL_CONFIG_PATH.exists():
        console.print("[red]NightShift not initialized. Run 'nightshift init' first.[/red]")
        raise typer.Exit(1)

    global_config = load_global_config()
    existing_paths = {ref.path.resolve() for ref in global_config.projects}

    console.print(
        Panel(
            "[bold cyan]Add Project[/bold cyan]\n"
            f"Currently configured: {len(existing_paths)} project(s)",
            expand=False,
        )
    )

    # --- Pick project path ---
    project_input = questionary.path(
        "Path to project (git repo):",
        only_directories=True,
    ).ask()
    if not project_input:
        raise typer.Abort()

    project_path = Path(project_input).expanduser().resolve()

    if not (project_path / ".git").is_dir():
        console.print(f"[red]Not a git repository: {project_path}[/red]")
        raise typer.Exit(1)

    if project_path in existing_paths:
        console.print(f"[yellow]{project_path.name} is already configured.[/yellow]")
        reconfigure = questionary.confirm("Reconfigure it?", default=False).ask()
        if not reconfigure:
            raise typer.Exit(0)
        # Remove old ref so we can replace it
        global_config.projects = [
            ref for ref in global_config.projects
            if ref.path.resolve() != project_path
        ]

    # --- Use existing limits from first project, or defaults ---
    if global_config.projects:
        from nightshift.config.loader import load_project_config
        existing_pc = load_project_config(global_config.projects[0].path)
        limits = existing_pc.limits
        console.print(
            f"[dim]Using limits from existing config: "
            f"max_tasks={limits.max_tasks_per_run}, "
            f"timeout={limits.task_timeout_minutes}m, "
            f"max_files={limits.max_files_changed}, "
            f"max_lines={limits.max_lines_changed}[/dim]"
        )
        customize = questionary.confirm("Customize limits for this project?", default=False).ask()
        if customize:
            limits = _configure_limits()
    else:
        limits = _configure_limits()

    # --- Configure sources ---
    result = _configure_project(project_path, limits)
    if result is None:
        raise typer.Exit(0)

    ref, pc, sources = result

    # --- API tokens (only for new source types) ---
    tokens = _collect_api_tokens(sources)
    if tokens:
        _save_env(tokens)

    # --- Save ---
    global_config.projects.append(ref)
    save_global_config(global_config)
    console.print(f"[green]Updated global config: {GLOBAL_CONFIG_PATH}[/green]")

    save_project_config(project_path, pc)
    console.print(f"[green]Saved project config: {project_path / '.nightshift.yaml'}[/green]")

    console.print(
        Panel(
            f"[bold green]Added {project_path.name}![/bold green]\n\n"
            f"Run [cyan]nightshift run --dry-run -p {project_path.name}[/cyan] to preview.",
            expand=False,
        )
    )
