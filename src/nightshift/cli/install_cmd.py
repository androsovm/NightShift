"""nightshift install/uninstall -- set up system scheduling (launchd/systemd)."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

console = Console()

PLIST_LABEL = "com.nightshift.agent"
PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = PLIST_DIR / f"{PLIST_LABEL}.plist"

SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"
SERVICE_NAME = "nightshift"
SERVICE_PATH = SYSTEMD_USER_DIR / f"{SERVICE_NAME}.service"
TIMER_PATH = SYSTEMD_USER_DIR / f"{SERVICE_NAME}.timer"


def _get_schedule() -> tuple[str, str]:
    """Read schedule time and timezone from global config."""
    try:
        from nightshift.config.loader import load_global_config

        config = load_global_config()
        return config.schedule.time, config.schedule.timezone
    except Exception:
        return "04:00", "UTC"


def _find_nightshift_bin() -> str:
    """Locate the nightshift executable."""
    which = shutil.which("nightshift")
    if which:
        return which
    # Fallback: use the current Python interpreter with -m
    return f"{sys.executable} -m nightshift"


def _generate_plist(time: str, timezone: str) -> str:
    """Generate a launchd plist XML for macOS."""
    hour, minute = time.split(":")
    nightshift_bin = _find_nightshift_bin()

    # Split command into program and arguments for plist
    parts = nightshift_bin.split()
    program = parts[0]
    args = parts[1:] + ["run"]

    program_args = "\n".join(f"        <string>{a}</string>" for a in [program, *args])

    return dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{PLIST_LABEL}</string>

            <key>ProgramArguments</key>
            <array>
        {program_args}
            </array>

            <key>StartCalendarInterval</key>
            <dict>
                <key>Hour</key>
                <integer>{int(hour)}</integer>
                <key>Minute</key>
                <integer>{int(minute)}</integer>
            </dict>

            <key>StandardOutPath</key>
            <string>{Path.home() / ".nightshift" / "launchd-stdout.log"}</string>
            <key>StandardErrorPath</key>
            <string>{Path.home() / ".nightshift" / "launchd-stderr.log"}</string>

            <key>EnvironmentVariables</key>
            <dict>
                <key>TZ</key>
                <string>{timezone}</string>
                <key>PATH</key>
                <string>/usr/local/bin:/usr/bin:/bin:{Path(sys.executable).parent}</string>
            </dict>

            <key>RunAtLoad</key>
            <false/>
        </dict>
        </plist>""")


def _generate_service() -> str:
    """Generate a systemd user service unit."""
    nightshift_bin = _find_nightshift_bin()
    return dedent(f"""\
        [Unit]
        Description=NightShift automated task runner
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=oneshot
        ExecStart={nightshift_bin} run
        Environment=PATH=/usr/local/bin:/usr/bin:/bin:{Path(sys.executable).parent}

        [Install]
        WantedBy=default.target""")


def _generate_timer(time: str, timezone: str) -> str:
    """Generate a systemd user timer unit."""
    return dedent(f"""\
        [Unit]
        Description=NightShift nightly schedule

        [Timer]
        OnCalendar=*-*-* {time}:00
        Persistent=true
        Unit={SERVICE_NAME}.service

        [Install]
        WantedBy=timers.target""")


def _install_macos(time: str, timezone: str) -> None:
    """Install launchd plist on macOS."""
    PLIST_DIR.mkdir(parents=True, exist_ok=True)

    # Unload existing if present
    if PLIST_PATH.exists():
        subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)],
            capture_output=True,
        )

    plist_content = _generate_plist(time, timezone)
    PLIST_PATH.write_text(plist_content)

    console.print(Syntax(plist_content, "xml", theme="monokai", line_numbers=True))
    console.print(f"\n[green]Written to {PLIST_PATH}[/green]")

    # Load the agent
    result = subprocess.run(
        ["launchctl", "load", str(PLIST_PATH)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        console.print("[green]launchd agent loaded successfully.[/green]")
    else:
        console.print(f"[red]Failed to load agent: {result.stderr.strip()}[/red]")
        console.print(f"[dim]Try manually: launchctl load {PLIST_PATH}[/dim]")


def _install_linux(time: str, timezone: str) -> None:
    """Install systemd user timer + service on Linux."""
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)

    service_content = _generate_service()
    timer_content = _generate_timer(time, timezone)

    SERVICE_PATH.write_text(service_content)
    TIMER_PATH.write_text(timer_content)

    console.print("[bold]Service unit:[/bold]")
    console.print(Syntax(service_content, "ini", theme="monokai", line_numbers=True))
    console.print(f"[green]Written to {SERVICE_PATH}[/green]\n")

    console.print("[bold]Timer unit:[/bold]")
    console.print(Syntax(timer_content, "ini", theme="monokai", line_numbers=True))
    console.print(f"[green]Written to {TIMER_PATH}[/green]\n")

    # Reload and enable
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    result = subprocess.run(
        ["systemctl", "--user", "enable", "--now", f"{SERVICE_NAME}.timer"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        console.print("[green]Timer enabled and started.[/green]")
        # Show timer status
        status_result = subprocess.run(
            ["systemctl", "--user", "status", f"{SERVICE_NAME}.timer"],
            capture_output=True,
            text=True,
        )
        if status_result.stdout:
            console.print(status_result.stdout)
    else:
        console.print(f"[red]Failed to enable timer: {result.stderr.strip()}[/red]")
        console.print(
            f"[dim]Try manually: systemctl --user enable --now {SERVICE_NAME}.timer[/dim]"
        )


def _uninstall_macos() -> None:
    """Remove launchd plist on macOS."""
    if not PLIST_PATH.exists():
        console.print("[yellow]No launchd agent found. Nothing to uninstall.[/yellow]")
        return

    result = subprocess.run(
        ["launchctl", "unload", str(PLIST_PATH)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        console.print("[green]launchd agent unloaded.[/green]")
    else:
        console.print(f"[yellow]launchctl unload: {result.stderr.strip()}[/yellow]")

    PLIST_PATH.unlink()
    console.print(f"[green]Removed {PLIST_PATH}[/green]")


def _uninstall_linux() -> None:
    """Remove systemd user timer + service on Linux."""
    if not TIMER_PATH.exists() and not SERVICE_PATH.exists():
        console.print("[yellow]No systemd units found. Nothing to uninstall.[/yellow]")
        return

    subprocess.run(
        ["systemctl", "--user", "disable", "--now", f"{SERVICE_NAME}.timer"],
        capture_output=True,
    )
    console.print("[green]Timer disabled.[/green]")

    for path in (TIMER_PATH, SERVICE_PATH):
        if path.exists():
            path.unlink()
            console.print(f"[green]Removed {path}[/green]")

    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    console.print("[green]systemd daemon reloaded.[/green]")


def install() -> None:
    """Install NightShift as a scheduled system service."""
    time, timezone = _get_schedule()
    system = platform.system()

    console.print(
        Panel(
            f"[bold cyan]Installing NightShift scheduler[/bold cyan]\n"
            f"Schedule: daily at {time} ({timezone})\n"
            f"Platform: {system}",
            expand=False,
        )
    )

    if system == "Darwin":
        _install_macos(time, timezone)
    elif system == "Linux":
        _install_linux(time, timezone)
    else:
        console.print(f"[red]Unsupported platform: {system}[/red]")
        console.print("[dim]NightShift scheduling supports macOS (launchd) and Linux (systemd).[/dim]")
        raise typer.Exit(1)

    console.print(
        f"\n[bold green]Installed![/bold green] NightShift will run daily at {time} {timezone}."
    )
    console.print("[dim]Use 'nightshift uninstall' to remove.[/dim]")


def uninstall() -> None:
    """Remove NightShift from system scheduling."""
    system = platform.system()

    console.print(
        Panel("[bold yellow]Uninstalling NightShift scheduler[/bold yellow]", expand=False)
    )

    if system == "Darwin":
        _uninstall_macos()
    elif system == "Linux":
        _uninstall_linux()
    else:
        console.print(f"[red]Unsupported platform: {system}[/red]")
        raise typer.Exit(1)

    console.print("\n[bold green]NightShift scheduler removed.[/bold green]")
