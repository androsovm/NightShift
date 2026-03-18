"""Entry point for `nightshift` CLI."""

from nightshift.cli.app import app


def main() -> None:
    app()


if __name__ == "__main__":
    main()
