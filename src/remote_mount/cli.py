from pathlib import Path

import click

from remote_mount import __version__
from remote_mount.config import MountConfig, get_config_path, load_config, save_config
from remote_mount.doctor import print_results, prompt_install, run_checks
from remote_mount.mounts import do_mount, do_unmount, watchdog_loop
from remote_mount.platform import detect_platform
from remote_mount.ssh_config import generate_host_block, write_host_block


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


@cli.command()
def add():
    """Interactively configure a new mount."""
    host = click.prompt("Host")
    remote_path = click.prompt("Remote path", default="/")
    mount_point = click.prompt("Mount point", default=f"~/mnt/{host}")
    auto_mount = click.confirm("Auto mount?", default=True)
    watchdog = click.confirm("Enable watchdog?", default=False)

    config_path = get_config_path()
    config = load_config(config_path)

    config.mounts[host] = MountConfig(
        host=host,
        remote_path=remote_path,
        mount_point=mount_point,
        auto_mount=auto_mount,
        watchdog=watchdog,
    )

    # Optionally configure Tailscale failover
    if click.confirm("Configure Tailscale SSH failover?", default=False):
        tailscale_ip = click.prompt("Tailscale IP", default="")
        lan_ip = click.prompt("LAN IP", default="")
        fqdn = click.prompt("FQDN", default="")
        user = click.prompt("SSH user")
        identity_file = click.prompt("Identity file", default="~/.ssh/id_ed25519")

        block = generate_host_block(
            host=host,
            user=user,
            identity_file=identity_file,
            tailscale_ip=tailscale_ip,
            lan_ip=lan_ip,
            fqdn=fqdn,
        )

        ssh_config_path = Path.home() / ".ssh" / "config"
        result = write_host_block(ssh_config_path, host, block)
        if result == "added":
            click.echo(f"SSH Host block for '{host}' added to {ssh_config_path}.")
        elif result == "updated":
            click.echo(f"SSH Host block for '{host}' updated in {ssh_config_path}.")
        elif result == "conflict":
            click.echo(
                f"Warning: unmanaged SSH Host block for '{host}' already exists in "
                f"{ssh_config_path}. Not modified.",
                err=True,
            )

    save_config(config, config_path)
    click.echo(f"Mount '{host}' added.")


@cli.command()
@click.argument("name")
def remove(name):
    """Remove a configured mount."""
    config_path = get_config_path()
    config = load_config(config_path)

    if name not in config.mounts:
        raise click.ClickException(f"Mount '{name}' not found in config.")

    if not click.confirm(f"Remove mount '{name}'?", default=False):
        click.echo("Aborted.")
        return

    del config.mounts[name]
    save_config(config, config_path)
    click.echo(f"Mount '{name}' removed.")


@cli.command(name="_watchdog", hidden=True)
@click.option(
    "--config",
    "config_path",
    default=None,
    help="Path to config file (defaults to standard location).",
)
def _watchdog_cmd(config_path):
    """[Internal] Run the watchdog health-check loop (service entry point)."""
    path = Path(config_path) if config_path else get_config_path()
    watchdog_loop(path)


@cli.group()
def service():
    """Manage the remote-mount watchdog background service."""


def _get_service_manager():
    """Return the appropriate service manager for the current platform."""
    from remote_mount.platform import get_service_manager  # noqa: PLC0415

    return get_service_manager(detect_platform())


def _get_watchdog_cmd() -> str:
    """Return the path to the remote-mount executable."""
    import shutil  # noqa: PLC0415

    path = shutil.which("remote-mount")
    if path:
        return path
    raise click.ClickException(
        "Cannot find 'remote-mount' in PATH. "
        "Install the package or activate the correct virtualenv before installing the service."
    )


@service.command()
def install():
    """Install the watchdog as a background service."""
    manager = _get_service_manager()
    watchdog_cmd = _get_watchdog_cmd()
    name = manager.install(watchdog_cmd)
    click.echo(f"Service '{name}' installed.")


@service.command()
def start():
    """Start the watchdog background service."""
    manager = _get_service_manager()
    manager.start()
    click.echo("Service started.")


@service.command()
def stop():
    """Stop the watchdog background service."""
    manager = _get_service_manager()
    manager.stop()
    click.echo("Service stopped.")


@service.command()
def uninstall():
    """Uninstall the watchdog background service."""
    manager = _get_service_manager()
    manager.uninstall()
    click.echo("Service uninstalled.")
