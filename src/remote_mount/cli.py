from pathlib import Path

import click

from remote_mount import __version__
from remote_mount.config import MountConfig, get_config_path, load_config, save_config
from remote_mount.doctor import print_results, prompt_install, run_checks
from remote_mount.mounts import do_mount, do_unmount, is_mounted, watchdog_loop
from remote_mount.platform import detect_platform, get_service_manager
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
                    import subprocess as _sp  # noqa: PLC0415

                    click.echo(f"  Running: {result.install_cmd}")
                    ret = _sp.run(result.install_cmd, shell=True)
                    if ret.returncode != 0:
                        click.echo(
                            f"  Failed (exit {ret.returncode}). "
                            f"Try manually: {result.install_cmd}",
                            err=True,
                        )
                elif action == "manual":
                    click.echo(f"  Run manually: {result.install_cmd}")
    else:
        click.echo("\nAll checks passed.")


@cli.command()
@click.argument("name", required=False)
@click.option("--all", "all_mounts", is_flag=True, help="Mount all configured mounts.")
def mount(name, all_mounts):
    """Mount remote filesystem(s)."""
    config = load_config(get_config_path())
    rclone = config.rclone
    platform = detect_platform()

    if not name and not all_mounts:
        raise click.UsageError("Provide a mount NAME or use --all.")

    targets = list(config.mounts.items()) if all_mounts else []
    if name:
        if name not in config.mounts:
            raise click.ClickException(f"Mount '{name}' not found in config.")
        targets = [(name, config.mounts[name])]

    for mount_name, mount_cfg in targets:
        click.echo(f"Mounting {mount_name}...")
        err = do_mount(mount_cfg, rclone, platform)
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


@cli.command(name="list")
def list_mounts():
    """Show all configured mounts with their current status."""
    config = load_config(get_config_path())

    if not config.mounts:
        click.echo("No mounts configured. Use 'remote-mount add' to add a mount.")
        return

    for name, mount_cfg in config.mounts.items():
        mounted = is_mounted(mount_cfg.resolved_mount_point)
        status_str = (
            click.style("mounted", fg="green")
            if mounted
            else click.style("not mounted", fg="red")
        )

        flags = []
        if mount_cfg.auto_mount:
            flags.append("auto")
        if mount_cfg.watchdog:
            flags.append("watchdog")
        flags_str = f"[{', '.join(flags)}]" if flags else ""

        click.echo(f"{name}")
        click.echo(
            f"  {mount_cfg.host}:{mount_cfg.remote_path} -> {mount_cfg.mount_point}"
        )
        click.echo(f"  {status_str}  {flags_str}".rstrip())


@cli.command()
def status():
    """Show mount health and watchdog service state."""
    config = load_config(get_config_path())
    platform = detect_platform()

    for name, mount_cfg in config.mounts.items():
        mounted = is_mounted(mount_cfg.resolved_mount_point)
        if mounted:
            bullet = click.style("●", fg="green")
            state = click.style("mounted", fg="green")
        else:
            bullet = click.style("○", fg="red")
            state = click.style("not mounted", fg="red")
        click.echo(f"{bullet} {name}: {state}  {mount_cfg.mount_point}")

    try:
        manager = get_service_manager(platform)
        svc_status = manager.status()
        click.echo(f"\nWatchdog service: {svc_status}")
    except NotImplementedError:
        click.echo("\nWatchdog service: not supported on this platform")


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


@cli.group(invoke_without_command=True)
@click.pass_context
def config(ctx):
    """Manage configuration file."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(edit)


@config.command()
def path():
    """Print the path to the config file."""
    click.echo(get_config_path())


@config.command()
def edit():
    """Open config file in $EDITOR."""
    config_path = get_config_path()
    if not config_path.exists():
        click.echo("No config file found. Run 'remote-mount add' to create one.")
        return

    content = config_path.read_text()
    new_content = click.edit(content, extension=".yaml")
    if new_content is not None and new_content != content:
        config_path.write_text(new_content)


@cli.group()
def service():
    """Manage the remote-mount watchdog background service."""


def _get_service_manager():
    """Return the appropriate service manager for the current platform."""
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
