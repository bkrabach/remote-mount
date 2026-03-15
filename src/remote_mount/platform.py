"""Platform detection and OS-specific utilities."""

import sys
from abc import ABC, abstractmethod
from typing import Literal

Platform = Literal["macos", "linux", "wsl2", "windows"]


def detect_platform() -> Platform:
    """Detect the current operating system platform."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    # Linux — check for WSL
    try:
        with open("/proc/version") as f:
            content = f.read().lower()
        if "microsoft" in content or "wsl" in content:
            return "wsl2"
    except OSError:
        pass
    return "linux"


def get_fuse_package(platform: Platform) -> str:
    """Return the FUSE package name for the given platform."""
    if platform == "macos":
        return "fuse-t"
    if platform == "windows":
        return "winfsp"
    # linux and wsl2
    return "fuse3"


def get_install_command(platform: Platform) -> str:
    """Return the FUSE install command for the given platform."""
    if platform == "macos":
        return "brew install --cask fuse-t"
    if platform == "windows":
        return "winget install WinFsp.WinFsp"
    # linux and wsl2
    return "sudo apt install fuse3 libfuse3-dev"


def get_unmount_command(platform: Platform, mount_point: str) -> list[str]:
    """Return the unmount command for the given platform and mount point."""
    if platform == "macos":
        return ["umount", mount_point]
    # linux and wsl2
    return ["fusermount", "-uz", mount_point]


class ServiceManager(ABC):
    """Abstract base class for OS service managers."""

    @abstractmethod
    def install(self, watchdog_cmd: str) -> str:
        """Install the watchdog service. Returns the service name."""

    @abstractmethod
    def uninstall(self) -> None:
        """Uninstall the watchdog service."""

    @abstractmethod
    def start(self) -> None:
        """Start the watchdog service."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the watchdog service."""

    @abstractmethod
    def status(self) -> str:
        """Return the status of the watchdog service."""


def get_service_manager(platform: Platform) -> ServiceManager:
    """Return the appropriate ServiceManager for the given platform."""
    if platform == "macos":
        from remote_mount.service_macos import LaunchdManager  # type: ignore[import-not-found]

        return LaunchdManager()
    if platform in ("linux", "wsl2"):
        from remote_mount.service_linux import SystemdManager  # type: ignore[import-not-found]

        return SystemdManager()
    raise NotImplementedError(f"Service manager not supported on platform: {platform}")
