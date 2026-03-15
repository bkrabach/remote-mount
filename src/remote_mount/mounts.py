"""Mount and unmount operations for remote-mount."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from remote_mount.config import MountConfig, RcloneConfig, load_config
from remote_mount.platform import Platform, detect_platform, get_unmount_command

logger = logging.getLogger(__name__)


@dataclass
class WatchdogState:
    """Per-mount state for the watchdog health-check loop."""

    backoff: int = 5
    action: str = field(default="")


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


def watchdog_tick(
    mount: MountConfig,
    state: WatchdogState,
    rclone: RcloneConfig,
    platform: Platform,
    backoff_base: int = 5,
    backoff_max: int = 300,
) -> None:
    """Execute a single watchdog health-check tick for one mount.

    Mutates state.backoff and state.action in place.

    - If mounted and healthy: reset backoff to base, action='healthy'
    - If not mounted:
      - Attempt unmount cleanup (stale)
      - If host unreachable: action='unreachable', double backoff (capped at max)
      - If host reachable: attempt remount
        - On error: action='mount_failed', double backoff (capped at max)
        - On success: action='remounted', reset backoff to base
    """
    if is_mounted(mount.mount_point):
        state.backoff = backoff_base
        state.action = "healthy"
        return

    # Not mounted — clean up stale mount point then check connectivity
    do_unmount(mount.mount_point, platform)

    if not check_host_reachable(mount.host):
        state.action = "unreachable"
        state.backoff = min(state.backoff * 2, backoff_max)
        return

    # Host reachable — attempt remount
    err = do_mount(mount, rclone)
    if err:
        state.action = "mount_failed"
        state.backoff = min(state.backoff * 2, backoff_max)
    else:
        state.action = "remounted"
        state.backoff = backoff_base


def trim_log(
    log_path: Path | str, max_lines: int = 1000, keep_lines: int = 500
) -> None:
    """Trim a log file to keep_lines if it exceeds max_lines."""
    log_path = Path(log_path)
    if not log_path.exists():
        return
    lines = log_path.read_text().splitlines(keepends=True)
    if len(lines) > max_lines:
        log_path.write_text("".join(lines[-keep_lines:]))


def watchdog_loop(config_path: Path | str) -> None:
    """Run the watchdog health-check loop indefinitely.

    Each iteration:
    - Loads config fresh from disk
    - Filters mounts with watchdog=True
    - Maintains per-mount WatchdogState dict
    - Calls watchdog_tick for each enabled mount
    - Logs non-healthy actions
    - Sleeps for config.watchdog.check_interval seconds
    """
    config_path = Path(config_path)
    states: dict[str, WatchdogState] = {}
    platform = detect_platform()

    while True:
        config = load_config(config_path)
        watchdog_mounts = {
            name: mount for name, mount in config.mounts.items() if mount.watchdog
        }

        # Initialise state for newly added mounts
        for name in watchdog_mounts:
            if name not in states:
                states[name] = WatchdogState(backoff=config.watchdog.backoff_base)

        # Remove state for mounts that no longer have watchdog enabled
        for name in list(states.keys()):
            if name not in watchdog_mounts:
                del states[name]

        for name, mount in watchdog_mounts.items():
            state = states[name]
            watchdog_tick(
                mount,
                state,
                config.rclone,
                platform,
                backoff_base=config.watchdog.backoff_base,
                backoff_max=config.watchdog.backoff_max,
            )
            if state.action != "healthy":
                logger.warning(
                    "watchdog [%s]: %s (backoff=%s)", name, state.action, state.backoff
                )

        time.sleep(config.watchdog.check_interval)
