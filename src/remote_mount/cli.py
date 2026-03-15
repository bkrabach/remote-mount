import click

from remote_mount import __version__
from remote_mount.config import get_config_path, load_config
from remote_mount.doctor import print_results, prompt_install, run_checks
from remote_mount.mounts import do_mount, do_unmount
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


@cli.command()
@click.argument("name", required=False)
@click.option("--all", "all_mounts", is_flag=True, help="Mount all configured mounts.")
def mount(name, all_mounts):
    """Mount remote filesystem(s)."""
    config = load_config(get_config_path())
    rclone = config.rclone

    if not name and not all_mounts:
        raise click.UsageError("Provide a mount NAME or use --all.")

    targets = list(config.mounts.items()) if all_mounts else []
    if name:
        if name not in config.mounts:
            raise click.ClickException(f"Mount '{name}' not found in config.")
        targets = [(name, config.mounts[name])]

    for mount_name, mount_cfg in targets:
        click.echo(f"Mounting {mount_name}...")
        err = do_mount(mount_cfg, rclone)
        if err:
            click.echo(f"  Error: {err}", err=True)
        else:
            click.echo(f"  Mounted at {mount_cfg.mount_point}")


@cli.command()
@click.argument("name", required=False)
@click.option(
    "--all", "all_mounts", is_flag=True, help="Unmount all configured mounts."
)
def unmount(name, all_mounts):
    """Unmount remote filesystem(s)."""
    config = load_config(get_config_path())
    platform = detect_platform()

    if not name and not all_mounts:
        raise click.UsageError("Provide a mount NAME or use --all.")

    targets = list(config.mounts.items()) if all_mounts else []
    if name:
        if name not in config.mounts:
            raise click.ClickException(f"Mount '{name}' not found in config.")
        targets = [(name, config.mounts[name])]

    for mount_name, mount_cfg in targets:
        click.echo(f"Unmounting {mount_name}...")
        err = do_unmount(mount_cfg.mount_point, platform)
        if err:
            click.echo(f"  Error: {err}", err=True)
        else:
            click.echo(f"  Unmounted {mount_cfg.mount_point}")
