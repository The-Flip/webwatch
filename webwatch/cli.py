"""The ``webwatch`` command-line interface.

This is the scaffold: the command surface is defined here, but the check
registry, sources, and notification wiring are filled in by later phases (see
``docs/plans/``). Commands that have nothing to do yet say so and exit cleanly
rather than pretending to work.
"""

from __future__ import annotations

import sys

import click

from webwatch import __version__
from webwatch.result import exit_code


@click.group()
@click.version_option(__version__, prog_name="webwatch")
def cli() -> None:
    """Monitor where The Flip appears on the web and report out-of-sync info."""


@cli.command()
@click.option("--site", "site", default=None, help="Only run checks for this site.")
@click.option("--fact", "fact", default=None, help="Only run this fact/check.")
@click.option("--all", "run_all", is_flag=True, help="Run every registered check.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Report format.",
)
def check(site: str | None, fact: str | None, run_all: bool, output_format: str) -> None:
    """Run checks, print a report, and set the exit code.

    Exit codes: 0 all OK, 1 a MISMATCH (data out of sync), 2 a checker condition
    (could not read/fetch). See ``webwatch.result``.
    """
    # No checks are registered yet (Phase B/C). Report honestly and exit OK.
    results: list = []
    if not results:
        click.echo("No checks registered yet.")
    raise SystemExit(exit_code(results))


@cli.command(name="list")
def list_checks() -> None:
    """List the registered sites and checks."""
    click.echo("No checks registered yet.")


@cli.command()
@click.option("--validate", is_flag=True, help="Validate the facts file and exit.")
def facts(validate: bool) -> None:
    """Show or validate the loaded facts.yaml and rules."""
    click.echo("Facts loading is not implemented yet.")


@cli.command()
@click.option("--dry-run/--send", default=True, help="Print the email instead of sending it.")
def notify(dry_run: bool) -> None:
    """Preview or send the problem-notification email."""
    click.echo("Notification is not implemented yet.")


def main() -> None:
    """Console-script entry point (see ``[project.scripts]`` in pyproject.toml)."""
    cli()


if __name__ == "__main__":
    sys.exit(0)
