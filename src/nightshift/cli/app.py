"""NightShift CLI application."""

import typer

from nightshift.cli.doctor_cmd import doctor
from nightshift.cli.init_cmd import init
from nightshift.cli.install_cmd import install, uninstall
from nightshift.cli.log_cmd import log
from nightshift.cli.run_cmd import run
from nightshift.cli.status_cmd import status

app = typer.Typer(
    name="nightshift",
    help="Automated overnight task runner for Claude Code.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.command()(init)
app.command()(run)
app.command()(status)
app.command()(log)
app.command()(install)
app.command()(uninstall)
app.command()(doctor)
