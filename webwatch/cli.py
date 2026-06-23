"""The ``webwatch`` command-line interface.

Thin layer: parse arguments, call :mod:`webwatch.run`, render with
:mod:`webwatch.report`, and exit with the code from :func:`webwatch.result.exit_code`.
Notification on state transitions is wired in a later phase; for now ``check``
reports and exits.
"""

from __future__ import annotations

import click

from webwatch import __version__
from webwatch import facts as facts_module
from webwatch.checks import registry as checks_registry
from webwatch.facts import FactsError
from webwatch.report import render_json, render_text
from webwatch.result import exit_code
from webwatch.run import register_builtins, run_checks
from webwatch.sources import registry as sources_registry


@click.group()
@click.version_option(__version__, prog_name="webwatch")
def cli() -> None:
    """Monitor where The Flip appears on the web and report out-of-sync info."""


@cli.command()
@click.option("--site", "site", default=None, help="Only run checks for this site.")
@click.option("--fact", "fact", default=None, help="Only run this fact/check field.")
@click.option("--all", "run_all", is_flag=True, help="Run every registered check (the default).")
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
    try:
        facts = facts_module.load_facts()
    except FactsError as err:
        raise click.ClickException(str(err)) from err

    results = run_checks(facts, site=site, fact=fact)
    output = render_json(results) if output_format == "json" else render_text(results)
    click.echo(output)
    raise SystemExit(exit_code(results))


@cli.command(name="list")
def list_checks() -> None:
    """List the registered sites and their checks."""
    register_builtins()
    sources = sources_registry.all_sources()
    if not sources:
        click.echo("No sources registered.")
        return
    for source in sources:
        click.echo(f"{source.name}  ({source.url})")
        for check_spec in checks_registry.checks_for(source.name):
            click.echo(f"  - {check_spec.field}")


@cli.command()
@click.option("--validate", is_flag=True, help="Validate the facts file and exit.")
def facts(validate: bool) -> None:
    """Show or validate the loaded facts.yaml and rules."""
    try:
        loaded = facts_module.load_facts()
    except FactsError as err:
        raise click.ClickException(str(err)) from err

    if validate:
        click.echo(
            f"facts.yaml is valid: organization {loaded.organization.name!r}, {len(loaded.rules)} rule(s)."
        )
        return

    org = loaded.organization
    click.echo(f"Organization: {org.name}")
    click.echo(
        f"  address: {org.address.street}, {org.address.city}, {org.address.region} {org.address.postal_code}"
    )
    click.echo(f"  phone: {org.phone or '(unset)'}    email: {org.email or '(unset)'}")
    click.echo(f"Rules: {len(loaded.rules)}")
    for rule in loaded.rules:
        state = "enabled" if rule.enabled else "disabled"
        click.echo(f"  - {rule.id} ({rule.type}, {state})")


def main() -> None:
    """Console-script entry point (see ``[project.scripts]`` in pyproject.toml)."""
    cli()


if __name__ == "__main__":
    main()
