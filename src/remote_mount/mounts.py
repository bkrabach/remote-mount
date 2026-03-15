"""Mount and unmount operations for remote-mount."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from remote_mount.config import MountConfig, RcloneConfig
from remote_mount.platform import Platform, get_unmount_command


def build_rclone_command(mount: MountConfig, rclone: RcloneConfig) -> list[str]:
    """Build the rclone mount command for a given mount and rclone config."""
    cmd = [
        "rclone",
        "mount",
        f":sftp:{mount.remote_path}",
        mount.mount_point,
        "--sftp-host",
        mount.host,
        "--vfs-cache-mode",
        rclone.cache_mode,
        "--buffer-size",
        rclone.buffer_size,
        "--daemon",
    ]
    cmd.extend(rclone.extra_args)
    return cmd


def do_mount(mount: MountConfig, rclone: RcloneConfig) -> str | None:
    """Create mount point directory and run rclone mount command.

    Returns None on success, or an error string on failure.
    """
    Path(mount.mount_point).mkdir(parents=True, exist_ok=True)
    cmd = build_rclone_command(mount, rclone)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return result.stderr or f"rclone exited with code {result.returncode}"
    return None


def do_unmount(mount_point: str, platform: Platform) -> str | None:
    """Unmount the given mount point using the platform-appropriate command.

    Returns None on success, or an error string on failure.
    """
    cmd = get_unmount_command(platform, mount_point)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return "unmount timed out after 10 seconds"
    if result.returncode != 0:
        return result.stderr or f"unmount exited with code {result.returncode}"
    return None


def is_mounted(mount_point: str) -> bool:
    """Check if a mount point is mounted and responsive."""
    try:
        p = Path(mount_point)
        if not p.exists():
            return False
        os.stat(mount_point)
        list(p.iterdir())
        return True
    except OSError:
        return False


def check_host_reachable(host: str) -> bool:
    """Check if a remote host is reachable via SSH."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, "true"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except OSError:
        return False
