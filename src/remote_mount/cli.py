import click

from remote_mount import __version__
from remote_mount.doctor import print_results, prompt_install, run_checks
from remote_mount.platform import detect_platform


@click.group()
@click.version_option(version=__version__, prog_name="remote-mount")
def cli():
    """Manage persistent remote filesystem mounts using rclone SFTP."""


@cli.command()
def doctor():
    """Check prerequisites and system readiness."""
    platform = detect_platform()
    click.echo(f"Platform: {platform}\n")
    results = run_checks(platform)
    print_results(results)
    failures = [r for r in results if not r.passed]
    if failures:
        click.echo("")
        for result in failures:
            if result.install_cmd:
                action = prompt_install(result)
                if action == "auto":
                    click.echo(f"  Run: {result.install_cmd}")
                elif action == "manual":
                    click.echo(f"  Manual install: {result.install_cmd}")
    else:
        click.echo("\nAll checks passed.")
