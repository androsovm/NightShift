"""NightShift CLI application."""


import typer

from nightshift.cli.doctor_cmd import doctor
from nightshift.cli.init_cmd import add, init
from nightshift.cli.install_cmd import install, uninstall
from nightshift.cli.log_cmd import log
from nightshift.cli.run_cmd import run
from nightshift.cli.status_cmd import status
from nightshift.cli.sync_cmd import sync
from nightshift.cli.tasks_cmd import tasks_app

app = typer.Typer(
    name="nightshift",
    help="Automated overnight task runner for Claude Code.",
    no_args_is_help=False,
    invoke_without_command=True,
    rich_markup_mode="rich",
)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging output."),
) -> None:
    """Automated overnight task runner for Claude Code.

    Run without arguments to launch the TUI dashboard.
    """
    from nightshift.logging import configure_logging

    configure_logging(verbose=verbose)

    if ctx.invoked_subcommand is None:
        from nightshift.tui.app import run_dashboard

        run_dashboard()


app.command()(init)
app.command()(add)
app.command()(sync)
app.command()(run)
app.command()(status)
app.command()(log)
app.command()(install)
app.command()(uninstall)
app.command()(doctor)
app.add_typer(tasks_app)
