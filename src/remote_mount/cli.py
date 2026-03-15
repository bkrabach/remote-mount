import click

from remote_mount import __version__


@click.group()
@click.version_option(version=__version__, prog_name="remote-mount")
def cli():
    """Manage persistent remote filesystem mounts using rclone SFTP."""
