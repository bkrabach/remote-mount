"""Service management for the remote-mount watchdog background service."""

import os
import subprocess
from pathlib import Path

from remote_mount.platform import ServiceManager

# Service identifiers
LABEL = "com.remote-mount.watchdog"
UNIT_NAME = "remote-mount-watchdog"

# Plist XML template
_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{watchdog_cmd}</string>
        <string>_watchdog</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""

# Systemd unit template
_UNIT_TEMPLATE = """\
[Unit]
Description=remote-mount watchdog service
After=network-online.target

[Service]
Type=simple
ExecStart={watchdog_cmd} _watchdog
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""


class LaunchdManager(ServiceManager):
    """macOS launchd-based service manager for the remote-mount watchdog."""

    def __init__(self, plist_dir: Path | None = None) -> None:
        if plist_dir is None:
            plist_dir = Path.home() / "Library" / "LaunchAgents"
        self.plist_dir = Path(plist_dir)

    @property
    def _plist_path(self) -> Path:
        return self.plist_dir / f"{LABEL}.plist"

    @property
    def _uid(self) -> int:
        return os.getuid()

    def install(self, watchdog_cmd: str) -> str:
        """Generate and write the launchd plist file."""
        self.plist_dir.mkdir(parents=True, exist_ok=True)
        content = _PLIST_TEMPLATE.format(label=LABEL, watchdog_cmd=watchdog_cmd)
        self._plist_path.write_text(content)
        return LABEL

    def start(self) -> None:
        """Bootstrap the service with launchctl."""
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{self._uid}", str(self._plist_path)],
            check=True,
        )

    def stop(self) -> None:
        """Bootout (unload) the service with launchctl."""
        subprocess.run(
            ["launchctl", "bootout", f"gui/{self._uid}/{LABEL}"],
            check=True,
        )

    def uninstall(self) -> None:
        """Stop the service and remove the plist file."""
        try:
            self.stop()
        except subprocess.CalledProcessError:
            pass
        if self._plist_path.exists():
            self._plist_path.unlink()

    def status(self) -> str:
        """Return output of launchctl print for the service."""
        result = subprocess.run(
            ["launchctl", "print", f"gui/{self._uid}/{LABEL}"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout


class SystemdManager(ServiceManager):
    """Linux systemd-based service manager for the remote-mount watchdog."""

    def __init__(self, unit_dir: Path | None = None) -> None:
        if unit_dir is None:
            unit_dir = Path.home() / ".config" / "systemd" / "user"
        self.unit_dir = Path(unit_dir)

    @property
    def _unit_path(self) -> Path:
        return self.unit_dir / f"{UNIT_NAME}.service"

    def install(self, watchdog_cmd: str) -> str:
        """Generate and write the systemd unit file."""
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        content = _UNIT_TEMPLATE.format(watchdog_cmd=watchdog_cmd)
        self._unit_path.write_text(content)
        return UNIT_NAME

    def start(self) -> None:
        """Reload systemd daemon and start the service."""
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "start", UNIT_NAME], check=True)

    def stop(self) -> None:
        """Stop the systemd service."""
        subprocess.run(["systemctl", "--user", "stop", UNIT_NAME], check=True)

    def uninstall(self) -> None:
        """Stop the service, remove the unit file, and reload the daemon."""
        try:
            self.stop()
        except subprocess.CalledProcessError:
            pass
        if self._unit_path.exists():
            self._unit_path.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)

    def status(self) -> str:
        """Return the is-active status of the service."""
        result = subprocess.run(
            ["systemctl", "--user", "is-active", UNIT_NAME],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
