"""nightshift doctor -- verify environment and configuration."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

NIGHTSHIFT_DIR = Path.home() / ".nightshift"
GLOBAL_CONFIG_PATH = NIGHTSHIFT_DIR / "config.yaml"
ENV_PATH = NIGHTSHIFT_DIR / ".env"


def _check_command(name: str, args: list[str]) -> tuple[bool, str]:
    """Run a command and return (ok, version_or_error)."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            output = result.stdout.strip() or result.stderr.strip()
            # Take first line only
            first_line = output.splitlines()[0] if output else "ok"
            return True, first_line
        return False, result.stderr.strip().splitlines()[0] if result.stderr.strip() else f"exit code {result.returncode}"
    except FileNotFoundError:
        return False, "not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as exc:
        return False, str(exc)


def _check_git_push_dry_run() -> tuple[bool, str]:
    """Test that git push --dry-run works (checks auth and remote)."""
    # Find a project with a git repo
    try:
        from nightshift.config.loader import load_global_config

        config = load_global_config()
        for pref in config.projects:
            if (pref.path / ".git").is_dir():
                result = subprocess.run(
                    ["git", "-C", str(pref.path), "push", "--dry-run"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if result.returncode == 0:
                    return True, "push access OK"
                err = result.stderr.strip().splitlines()[0] if result.stderr.strip() else "failed"
                return False, err
        return False, "no configured project with git remote"
    except Exception as exc:
        return False, str(exc)


def _check_gpg_signing() -> tuple[bool, str]:
    """Check if GPG signing is configured and not blocking."""
    try:
        # Check if commit.gpgsign is enabled
        result = subprocess.run(
            ["git", "config", "--global", "commit.gpgsign"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        gpg_enabled = result.stdout.strip().lower() == "true"
        if not gpg_enabled:
            return True, "GPG signing not enabled (OK)"

        # If enabled, check that gpg agent is available
        gpg_result = subprocess.run(
            ["gpg", "--list-secret-keys", "--keyid-format=long"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if gpg_result.returncode == 0 and gpg_result.stdout.strip():
            return True, "GPG signing enabled, keys available"
        return False, "GPG signing enabled but no secret keys found"
    except FileNotFoundError:
        return False, "GPG signing enabled but gpg not found"
    except Exception as exc:
        return False, str(exc)


def _check_api_tokens() -> list[tuple[str, bool, str]]:
    """Validate that expected API tokens exist in .env or environment."""
    results: list[tuple[str, bool, str]] = []

    # Load .env file
    env_tokens: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_tokens[k.strip()] = v.strip()

    # Determine which tokens we need based on configured sources
    needed_tokens: dict[str, str] = {}  # token_name -> reason
    try:
        from nightshift.config.loader import load_global_config, load_project_config

        config = load_global_config()
        for pref in config.projects:
            try:
                pc = load_project_config(pref.path)
                for src in pc.sources:
                    if str(src.type) == "github":
                        needed_tokens["GITHUB_TOKEN"] = "GitHub source"
                    elif str(src.type) == "youtrack":
                        needed_tokens["YOUTRACK_TOKEN"] = "YouTrack source"
                    elif str(src.type) == "trello":
                        needed_tokens["TRELLO_API_KEY"] = "Trello source"
                        needed_tokens["TRELLO_TOKEN"] = "Trello source"
            except Exception:
                pass
    except Exception:
        # Config not yet set up; check common tokens
        for token_name in ("GITHUB_TOKEN", "YOUTRACK_TOKEN", "TRELLO_API_KEY", "TRELLO_TOKEN"):
            if token_name in env_tokens or token_name in os.environ:
                needed_tokens[token_name] = "found in env"

    if not needed_tokens:
        results.append(("API Tokens", True, "no tokens required (no remote sources)"))
        return results

    for token_name, reason in needed_tokens.items():
        value = env_tokens.get(token_name) or os.environ.get(token_name)
        if value:
            masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
            results.append((f"{token_name}", True, f"set ({masked}) - {reason}"))
        else:
            results.append((f"{token_name}", False, f"missing - needed for {reason}"))

    return results


def _check_sleep_prevention() -> tuple[bool, str]:
    """Check if the machine is configured to stay awake overnight."""
    system = platform.system()

    if system == "Darwin":
        try:
            result = subprocess.run(
                ["pmset", "-g"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False, "could not read pmset settings"

            output = result.stdout
            # Check for disablesleep first
            for line in output.splitlines():
                if "disablesleep" in line.lower():
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[1] == "1":
                        return True, "disablesleep is enabled"

            # Check sleep timer value
            # pmset format: "  sleep          1 (sleep prevented by ...)"
            # parts[0] = key, parts[1] = value, rest is optional comment
            for line in output.splitlines():
                stripped = line.strip()
                if stripped.startswith("sleep") and "displaysleep" not in stripped.lower():
                    parts = stripped.split()
                    if len(parts) >= 2:
                        try:
                            sleep_val = int(parts[1])
                            if sleep_val == 0:
                                return True, "sleep timer disabled (set to 0)"
                            return (
                                False,
                                f"machine may sleep after {sleep_val} min — "
                                "run: sudo pmset -c disablesleep 1",
                            )
                        except ValueError:
                            pass

            return False, "could not determine sleep setting — check System Settings → Energy"
        except FileNotFoundError:
            return False, "pmset not found"
        except Exception as exc:
            return False, str(exc)

    elif system == "Linux":
        try:
            targets_to_check = ["sleep.target", "suspend.target"]
            unmasked: list[str] = []
            for target in targets_to_check:
                result = subprocess.run(
                    ["systemctl", "is-enabled", target],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                status = result.stdout.strip()
                if status not in ("masked", "masked-runtime"):
                    unmasked.append(f"{target} ({status or 'active'})")
            if not unmasked:
                return True, "sleep.target and suspend.target are masked"
            return (
                False,
                f"{', '.join(unmasked)} not masked — "
                "run: systemctl mask sleep.target suspend.target",
            )
        except FileNotFoundError:
            return False, "systemctl not found — cannot verify sleep prevention"
        except Exception as exc:
            return False, str(exc)

    else:
        return True, f"sleep check not applicable on {system}"


def _check_config_files() -> list[tuple[str, bool, str]]:
    """Check that config files exist and parse correctly."""
    results: list[tuple[str, bool, str]] = []

    # Global config
    if not GLOBAL_CONFIG_PATH.exists():
        results.append(("Global config", False, f"{GLOBAL_CONFIG_PATH} not found"))
        return results

    try:
        from nightshift.config.loader import load_global_config

        config = load_global_config()
        n_projects = len(config.projects)
        results.append((
            "Global config",
            True,
            f"{n_projects} project(s), schedule={config.schedule.time} {config.schedule.timezone}",
        ))

        # Per-project configs
        for pref in config.projects:
            cfg_path = pref.path / ".nightshift.yaml"
            if not cfg_path.exists():
                results.append((f"  {pref.path.name}", False, ".nightshift.yaml not found"))
                continue
            try:
                from nightshift.config.loader import load_project_config

                pc = load_project_config(pref.path)
                sources = ", ".join(str(s.type) for s in pc.sources)
                results.append((f"  {pref.path.name}", True, f"sources: {sources}"))
            except Exception as exc:
                results.append((f"  {pref.path.name}", False, f"parse error: {exc}"))
    except Exception as exc:
        results.append(("Global config", False, f"parse error: {exc}"))

    return results


def doctor() -> None:
    """Check that NightShift's environment and configuration are healthy."""
    console.print(
        Panel("[bold cyan]NightShift Doctor[/bold cyan]", expand=False)
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Check", min_width=25)
    table.add_column("Status", width=6, justify="center")
    table.add_column("Details", min_width=30)

    issues = 0

    # --- Tool checks ---
    tool_checks = [
        ("claude", ["claude", "--version"]),
        ("gh (GitHub CLI)", ["gh", "--version"]),
        ("git", ["git", "--version"]),
    ]

    for name, args in tool_checks:
        ok, detail = _check_command(name, args)
        status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        table.add_row(name, status, detail)
        if not ok:
            issues += 1

    # --- Git push ---
    ok, detail = _check_git_push_dry_run()
    status = "[green]OK[/green]" if ok else "[yellow]WARN[/yellow]"
    table.add_row("git push (dry-run)", status, detail)
    if not ok:
        issues += 1

    # --- GPG ---
    ok, detail = _check_gpg_signing()
    status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
    table.add_row("GPG signing", status, detail)
    if not ok:
        issues += 1

    # --- .env file ---
    if ENV_PATH.exists():
        table.add_row(".env file", "[green]OK[/green]", str(ENV_PATH))
    else:
        table.add_row(".env file", "[yellow]WARN[/yellow]", "not found (may not be needed)")

    # --- API tokens ---
    token_results = _check_api_tokens()
    for name, ok, detail in token_results:
        status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        table.add_row(name, status, detail)
        if not ok:
            issues += 1

    # --- Config files ---
    config_results = _check_config_files()
    for name, ok, detail in config_results:
        status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        table.add_row(name, status, detail)
        if not ok:
            issues += 1

    # --- Sleep prevention ---
    ok, detail = _check_sleep_prevention()
    status = "[green]OK[/green]" if ok else "[yellow]WARN[/yellow]"
    table.add_row("Sleep prevention", status, detail)
    if not ok:
        issues += 1

    console.print(table)

    if issues == 0:
        console.print("\n[bold green]All checks passed![/bold green]")
    else:
        console.print(f"\n[bold yellow]{issues} issue(s) found.[/bold yellow]")
        console.print("[dim]Fix the issues above and run 'nightshift doctor' again.[/dim]")
        raise typer.Exit(1)
