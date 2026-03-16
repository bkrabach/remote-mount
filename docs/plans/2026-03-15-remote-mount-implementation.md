# remote-mount Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Build `remote-mount`, a Python CLI tool that manages persistent remote filesystem mounts using rclone's SFTP backend — replacing unmaintained SSHFS with cross-platform mount configuration, health monitoring, auto-reconnect, and optional Tailscale VPN failover.

**Architecture:** Thin orchestrator pattern — `remote-mount` doesn't reimplement anything. It orchestrates rclone (SFTP mounts), platform-native services (launchd/systemd), and SSH (auth/config). A `platform.py` abstraction layer isolates all OS-specific logic behind a `ServiceManager` interface, making future Windows support a single new class.

**Tech Stack:** Python 3.10+, click (CLI), pyyaml (config), paramiko (SSH config parsing), pytest (testing), uv (packaging/install)

**Design document:** `docs/plans/2026-03-15-remote-mount-design.md`

---

## File Map

Every file this plan creates, and what it's responsible for:

```
remote-mount/
  pyproject.toml                    # Package metadata, deps, [project.scripts] entry point
  README.md                         # Install/usage instructions (Task 12 only)
  src/remote_mount/
    __init__.py                     # Version string only
    cli.py                          # Click CLI entry point — thin wrappers delegating to modules
    config.py                       # Load/save/validate YAML config, path resolution
    doctor.py                       # Prerequisite detection & hybrid install prompts
    mounts.py                       # Mount/unmount via rclone subprocess, health checks
    service.py                      # Watchdog service management (launchd/systemd)
    ssh_config.py                   # SSH config parsing/writing for Tailscale failover
    platform.py                     # Platform detection, FUSE info, ServiceManager base
  tests/
    __init__.py                     # Empty (makes tests a package)
    test_platform.py                # Platform detection with mocked sys.platform / /proc/version
    test_config.py                  # YAML round-trip, defaults, validation, path expansion
    test_doctor.py                  # Prerequisite checks with mocked shutil.which/subprocess
    test_mounts.py                  # rclone command building, mount/unmount with mocked subprocess
    test_service.py                 # Template generation verified against known-good output
    test_ssh_config.py              # Host block parsing, generation, three-case write logic
    test_cli.py                     # Click CliRunner tests for all commands
```

---

## Phase 1: Foundation (Tasks 1–5)

### Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/remote_mount/__init__.py`
- Create: `src/remote_mount/cli.py`
- Create: `tests/__init__.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "remote-mount"
version = "0.1.0"
description = "Persistent remote filesystem mounts using rclone SFTP"
requires-python = ">=3.10"
dependencies = [
    "click>=8.0",
    "pyyaml>=6.0",
    "paramiko>=3.0",
]

[project.scripts]
remote-mount = "remote_mount.cli:cli"

[project.optional-dependencies]
dev = ["pytest>=7.0"]
```

- [ ] **Step 2: Create `src/remote_mount/__init__.py`**

```python
"""remote-mount: persistent remote filesystem mounts using rclone SFTP."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Create `src/remote_mount/cli.py`**

```python
"""CLI entry point for remote-mount."""

import click

from remote_mount import __version__


@click.group()
@click.version_option(version=__version__, prog_name="remote-mount")
def cli() -> None:
    """Manage persistent remote filesystem mounts using rclone SFTP."""
```

- [ ] **Step 4: Create `tests/__init__.py`**

Empty file — just makes `tests/` a Python package.

```python
```

- [ ] **Step 5: Write CLI smoke tests in `tests/test_cli.py`**

```python
"""Tests for the CLI entry point."""

from click.testing import CliRunner

from remote_mount.cli import cli


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "remote filesystem mounts" in result.output.lower()


def test_cli_version() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output
```

- [ ] **Step 6: Install project and run tests**

```bash
cd /Users/brkrabac/dev/mount-spark-1
uv venv
uv pip install -e ".[dev]"
uv run pytest tests/test_cli.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 7: Verify CLI entry point works**

```bash
uv run remote-mount --help
uv run remote-mount --version
```

Expected: Help text shows "Manage persistent remote filesystem mounts using rclone SFTP." and version shows "remote-mount, version 0.1.0".

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "feat: project scaffold with CLI entry point"
```

---

### Task 2: Platform Detection

**Files:**
- Create: `src/remote_mount/platform.py`
- Create: `tests/test_platform.py`

- [ ] **Step 1: Write failing tests in `tests/test_platform.py`**

```python
"""Tests for platform detection and abstraction."""

from unittest.mock import patch, mock_open

from remote_mount.platform import (
    detect_platform,
    get_fuse_package,
    get_install_command,
    get_unmount_command,
)


class TestDetectPlatform:
    def test_macos(self) -> None:
        with patch("sys.platform", "darwin"):
            assert detect_platform() == "macos"

    def test_linux(self) -> None:
        with patch("sys.platform", "linux"):
            with patch(
                "builtins.open", mock_open(read_data="Linux version 6.1.0")
            ):
                assert detect_platform() == "linux"

    def test_wsl2(self) -> None:
        with patch("sys.platform", "linux"):
            with patch(
                "builtins.open",
                mock_open(read_data="Linux version 5.15.0-microsoft-standard-WSL2"),
            ):
                assert detect_platform() == "wsl2"

    def test_wsl2_microsoft_lowercase(self) -> None:
        with patch("sys.platform", "linux"):
            with patch(
                "builtins.open",
                mock_open(read_data="Linux version 5.4.0-Microsoft"),
            ):
                assert detect_platform() == "wsl2"

    def test_linux_no_proc_version(self) -> None:
        with patch("sys.platform", "linux"):
            with patch("builtins.open", side_effect=FileNotFoundError):
                assert detect_platform() == "linux"

    def test_windows(self) -> None:
        with patch("sys.platform", "win32"):
            assert detect_platform() == "windows"


class TestFusePackage:
    def test_macos(self) -> None:
        assert get_fuse_package("macos") == "fuse-t"

    def test_linux(self) -> None:
        assert get_fuse_package("linux") == "fuse3"

    def test_wsl2(self) -> None:
        assert get_fuse_package("wsl2") == "fuse3"


class TestInstallCommand:
    def test_macos(self) -> None:
        assert get_install_command("macos") == "brew install --cask fuse-t"

    def test_linux(self) -> None:
        assert get_install_command("linux") == "sudo apt install fuse3 libfuse3-dev"

    def test_wsl2(self) -> None:
        assert get_install_command("wsl2") == "sudo apt install fuse3 libfuse3-dev"


class TestUnmountCommand:
    def test_macos(self) -> None:
        cmd = get_unmount_command("macos", "/mnt/test")
        assert cmd == ["umount", "/mnt/test"]

    def test_linux(self) -> None:
        cmd = get_unmount_command("linux", "/mnt/test")
        assert cmd == ["fusermount", "-uz", "/mnt/test"]

    def test_wsl2(self) -> None:
        cmd = get_unmount_command("wsl2", "/mnt/test")
        assert cmd == ["fusermount", "-uz", "/mnt/test"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_platform.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'remote_mount.platform'`

- [ ] **Step 3: Implement `src/remote_mount/platform.py`**

```python
"""Platform detection and OS-specific abstraction layer.

This module is the seam for cross-platform support. All other modules
call through here for anything OS-specific.
"""

from __future__ import annotations

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
    # Linux — check for WSL2
    try:
        with open("/proc/version") as f:
            version_info = f.read().lower()
        if "microsoft" in version_info or "wsl" in version_info:
            return "wsl2"
    except FileNotFoundError:
        pass
    return "linux"


def get_fuse_package(platform: Platform) -> str:
    """Return the FUSE package name for the given platform."""
    if platform == "macos":
        return "fuse-t"
    if platform in ("linux", "wsl2"):
        return "fuse3"
    return "winfsp"


def get_install_command(platform: Platform) -> str:
    """Return the shell command to install the FUSE package."""
    if platform == "macos":
        return "brew install --cask fuse-t"
    if platform in ("linux", "wsl2"):
        return "sudo apt install fuse3 libfuse3-dev"
    return "winget install WinFsp.WinFsp"


def get_unmount_command(platform: Platform, mount_point: str) -> list[str]:
    """Return the command to unmount a FUSE mount."""
    if platform == "macos":
        return ["umount", mount_point]
    # Linux and WSL2 use fusermount with lazy unmount
    return ["fusermount", "-uz", mount_point]


class ServiceManager(ABC):
    """Abstract base for platform-native service managers."""

    @abstractmethod
    def install(self, watchdog_cmd: str) -> str:
        """Install the watchdog service. Returns path to the service file."""

    @abstractmethod
    def uninstall(self) -> None:
        """Stop and remove the watchdog service."""

    @abstractmethod
    def start(self) -> None:
        """Start the watchdog service."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the watchdog service."""

    @abstractmethod
    def status(self) -> str:
        """Return the current status of the watchdog service."""


def get_service_manager(platform: Platform) -> ServiceManager:
    """Return the appropriate ServiceManager for the platform.

    Imports are deferred to avoid circular dependencies —
    LaunchdManager and SystemdManager live in service.py.
    """
    from remote_mount.service import LaunchdManager, SystemdManager

    if platform == "macos":
        return LaunchdManager()
    if platform in ("linux", "wsl2"):
        return SystemdManager()
    raise NotImplementedError(f"No service manager for platform: {platform}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_platform.py -v
```

Expected: All 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/remote_mount/platform.py tests/test_platform.py
git commit -m "feat: platform detection and OS abstraction layer"
```

---

### Task 3: Config Management

**Files:**
- Create: `src/remote_mount/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests in `tests/test_config.py`**

```python
"""Tests for configuration loading, saving, and validation."""

import os
from pathlib import Path

import yaml

from remote_mount.config import (
    Config,
    MountConfig,
    get_config_path,
    load_config,
    save_config,
    get_log_path,
)


class TestConfigPath:
    def test_default_path(self) -> None:
        path = get_config_path()
        assert path.name == "config.yaml"
        assert "remote-mount" in str(path)

    def test_xdg_override(self, tmp_path: Path, monkeypatch: object) -> None:
        import pytest

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))  # type: ignore[attr-defined]
        path = get_config_path()
        assert path == tmp_path / "remote-mount" / "config.yaml"


class TestLogPath:
    def test_default_log_path(self) -> None:
        path = get_log_path()
        assert path.name == "remote-mount.log"


class TestLoadConfig:
    def test_load_missing_returns_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config = load_config(config_file)
        assert config.mounts == {}
        assert config.rclone.cache_mode == "writes"
        assert config.watchdog.check_interval == 10

    def test_load_existing_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "mounts": {
                        "spark-1": {
                            "host": "spark-1",
                            "remote_path": "/",
                            "mount_point": "~/mnt/spark-1",
                            "auto_mount": True,
                            "watchdog": True,
                        }
                    }
                }
            )
        )
        config = load_config(config_file)
        assert "spark-1" in config.mounts
        assert config.mounts["spark-1"].host == "spark-1"
        assert config.mounts["spark-1"].remote_path == "/"
        assert config.mounts["spark-1"].auto_mount is True
        assert config.mounts["spark-1"].watchdog is True

    def test_mount_point_tilde_expansion(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "mounts": {
                        "test": {
                            "host": "test",
                            "remote_path": "/",
                            "mount_point": "~/mnt/test",
                        }
                    }
                }
            )
        )
        config = load_config(config_file)
        mount_path = config.mounts["test"].resolved_mount_point
        assert "~" not in str(mount_path)
        assert str(mount_path).startswith("/")


class TestSaveConfig:
    def test_round_trip(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config = Config()
        config.mounts["spark-1"] = MountConfig(
            host="spark-1",
            remote_path="/",
            mount_point="~/mnt/spark-1",
            auto_mount=True,
            watchdog=True,
        )
        save_config(config, config_file)

        loaded = load_config(config_file)
        assert "spark-1" in loaded.mounts
        assert loaded.mounts["spark-1"].host == "spark-1"
        assert loaded.mounts["spark-1"].mount_point == "~/mnt/spark-1"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        config_file = tmp_path / "deep" / "nested" / "config.yaml"
        config = Config()
        save_config(config, config_file)
        assert config_file.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'remote_mount.config'`

- [ ] **Step 3: Implement `src/remote_mount/config.py`**

```python
"""Configuration loading, saving, and validation.

Config lives at ~/.config/remote-mount/config.yaml.
The add wizard creates and updates it, or the user can hand-edit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def get_config_path() -> Path:
    """Return the path to the config file, respecting XDG_CONFIG_HOME."""
    config_home = os.environ.get("XDG_CONFIG_HOME", "")
    if config_home:
        base = Path(config_home)
    else:
        base = Path.home() / ".config"
    return base / "remote-mount" / "config.yaml"


def get_log_path() -> Path:
    """Return the path to the watchdog log file."""
    return Path.home() / ".local" / "log" / "remote-mount.log"


@dataclass
class MountConfig:
    """Configuration for a single named mount."""

    host: str
    remote_path: str = "/"
    mount_point: str = ""
    auto_mount: bool = True
    watchdog: bool = False

    @property
    def resolved_mount_point(self) -> Path:
        """Return mount_point with ~ expanded to an absolute path."""
        return Path(self.mount_point).expanduser()


@dataclass
class RcloneConfig:
    """Global rclone settings."""

    cache_mode: str = "writes"
    buffer_size: str = "64M"
    extra_args: list[str] = field(default_factory=list)


@dataclass
class TailscaleHostConfig:
    """Per-host Tailscale connection info."""

    tailscale_ip: str = ""
    lan_ip: str = ""
    fqdn: str = ""


@dataclass
class TailscaleConfig:
    """Global Tailscale settings."""

    enabled: bool = False
    hosts: dict[str, TailscaleHostConfig] = field(default_factory=dict)


@dataclass
class WatchdogConfig:
    """Watchdog timing settings."""

    check_interval: int = 10
    backoff_base: int = 5
    backoff_max: int = 300


@dataclass
class Config:
    """Top-level configuration."""

    mounts: dict[str, MountConfig] = field(default_factory=dict)
    rclone: RcloneConfig = field(default_factory=RcloneConfig)
    tailscale: TailscaleConfig = field(default_factory=TailscaleConfig)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)


def load_config(config_path: Path | None = None) -> Config:
    """Load config from YAML file. Returns defaults if file doesn't exist."""
    if config_path is None:
        config_path = get_config_path()

    if not config_path.exists():
        return Config()

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    config = Config()

    # Parse mounts
    for name, mount_data in raw.get("mounts", {}).items():
        config.mounts[name] = MountConfig(
            host=mount_data.get("host", name),
            remote_path=mount_data.get("remote_path", "/"),
            mount_point=mount_data.get("mount_point", f"~/mnt/{name}"),
            auto_mount=mount_data.get("auto_mount", True),
            watchdog=mount_data.get("watchdog", False),
        )

    # Parse rclone settings
    rclone_data = raw.get("rclone", {})
    if rclone_data:
        config.rclone = RcloneConfig(
            cache_mode=rclone_data.get("cache_mode", "writes"),
            buffer_size=rclone_data.get("buffer_size", "64M"),
            extra_args=rclone_data.get("extra_args", []),
        )

    # Parse tailscale settings
    ts_data = raw.get("tailscale", {})
    if ts_data:
        hosts = {}
        for host_name, host_data in ts_data.get("hosts", {}).items():
            hosts[host_name] = TailscaleHostConfig(
                tailscale_ip=host_data.get("tailscale_ip", ""),
                lan_ip=host_data.get("lan_ip", ""),
                fqdn=host_data.get("fqdn", ""),
            )
        config.tailscale = TailscaleConfig(
            enabled=ts_data.get("enabled", False),
            hosts=hosts,
        )

    # Parse watchdog settings
    wd_data = raw.get("watchdog", {})
    if wd_data:
        config.watchdog = WatchdogConfig(
            check_interval=wd_data.get("check_interval", 10),
            backoff_base=wd_data.get("backoff_base", 5),
            backoff_max=wd_data.get("backoff_max", 300),
        )

    return config


def save_config(config: Config, config_path: Path | None = None) -> None:
    """Save config to YAML file. Creates parent directories if needed."""
    if config_path is None:
        config_path = get_config_path()

    config_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {}

    # Serialize mounts
    if config.mounts:
        data["mounts"] = {}
        for name, mount in config.mounts.items():
            data["mounts"][name] = {
                "host": mount.host,
                "remote_path": mount.remote_path,
                "mount_point": mount.mount_point,
                "auto_mount": mount.auto_mount,
                "watchdog": mount.watchdog,
            }

    # Serialize rclone
    data["rclone"] = {
        "cache_mode": config.rclone.cache_mode,
        "buffer_size": config.rclone.buffer_size,
        "extra_args": config.rclone.extra_args,
    }

    # Serialize tailscale
    ts: dict = {"enabled": config.tailscale.enabled}
    if config.tailscale.hosts:
        ts["hosts"] = {}
        for host_name, host_cfg in config.tailscale.hosts.items():
            ts["hosts"][host_name] = {
                "tailscale_ip": host_cfg.tailscale_ip,
                "lan_ip": host_cfg.lan_ip,
                "fqdn": host_cfg.fqdn,
            }
    data["tailscale"] = ts

    # Serialize watchdog
    data["watchdog"] = {
        "check_interval": config.watchdog.check_interval,
        "backoff_base": config.watchdog.backoff_base,
        "backoff_max": config.watchdog.backoff_max,
    }

    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_config.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/remote_mount/config.py tests/test_config.py
git commit -m "feat: config management with YAML load/save and defaults"
```

---

### Task 4: Doctor Command

**Files:**
- Create: `src/remote_mount/doctor.py`
- Create: `tests/test_doctor.py`
- Modify: `src/remote_mount/cli.py` (add `doctor` command)

- [ ] **Step 1: Write failing tests in `tests/test_doctor.py`**

```python
"""Tests for the doctor prerequisite checker."""

import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from remote_mount.doctor import (
    check_rclone,
    check_ssh_key,
    check_fuse,
    CheckResult,
)


class TestCheckRclone:
    def test_rclone_found(self) -> None:
        with patch("shutil.which", return_value="/usr/local/bin/rclone"):
            with patch(
                "subprocess.run",
                return_value=MagicMock(
                    returncode=0, stdout="rclone v1.68.2\n"
                ),
            ):
                result = check_rclone()
                assert result.passed is True
                assert "v1.68.2" in result.detail

    def test_rclone_missing(self) -> None:
        with patch("shutil.which", return_value=None):
            result = check_rclone()
            assert result.passed is False
            assert result.install_cmd is not None


class TestCheckSshKey:
    def test_key_exists(self, tmp_path: Path) -> None:
        key_file = tmp_path / ".ssh" / "id_ed25519"
        key_file.parent.mkdir()
        key_file.write_text("fake key")
        with patch("pathlib.Path.home", return_value=tmp_path):
            result = check_ssh_key()
            assert result.passed is True
            assert "id_ed25519" in result.detail

    def test_no_key(self, tmp_path: Path) -> None:
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        with patch("pathlib.Path.home", return_value=tmp_path):
            result = check_ssh_key()
            assert result.passed is False


class TestCheckFuse:
    def test_fuse_t_found_macos(self) -> None:
        with patch(
            "subprocess.run",
            return_value=MagicMock(returncode=0, stdout="/usr/local/lib/libfuse-t.dylib\n"),
        ):
            result = check_fuse("macos")
            assert result.passed is True

    def test_fuse_missing_macos(self) -> None:
        with patch(
            "subprocess.run",
            return_value=MagicMock(returncode=1, stdout=""),
        ):
            result = check_fuse("macos")
            assert result.passed is False
            assert "brew install" in (result.install_cmd or "")

    def test_fuse3_found_linux(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/fusermount3"):
            result = check_fuse("linux")
            assert result.passed is True

    def test_fuse_missing_linux(self) -> None:
        with patch("shutil.which", return_value=None):
            result = check_fuse("linux")
            assert result.passed is False
            assert "apt install" in (result.install_cmd or "")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_doctor.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'remote_mount.doctor'`

- [ ] **Step 3: Implement `src/remote_mount/doctor.py`**

```python
"""Prerequisite detection and hybrid install prompts.

`remote-mount doctor` checks prerequisites and offers to fix what's missing.
Each check is independent — a failure in one doesn't stop the others.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import click

from remote_mount.platform import Platform, get_install_command


@dataclass
class CheckResult:
    """Result of a single prerequisite check."""

    name: str
    passed: bool
    detail: str = ""
    install_cmd: str | None = None


def check_rclone() -> CheckResult:
    """Check if rclone is installed and get its version."""
    path = shutil.which("rclone")
    if not path:
        return CheckResult(
            name="rclone",
            passed=False,
            detail="not found",
            install_cmd="brew install rclone",
        )
    try:
        result = subprocess.run(
            ["rclone", "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        version = result.stdout.split("\n")[0].replace("rclone ", "")
        return CheckResult(name="rclone", passed=True, detail=version)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return CheckResult(name="rclone", passed=False, detail="error running rclone")


def check_ssh_key() -> CheckResult:
    """Check if an SSH key exists in ~/.ssh/."""
    ssh_dir = Path.home() / ".ssh"
    if not ssh_dir.exists():
        return CheckResult(
            name="SSH key",
            passed=False,
            detail="~/.ssh directory not found",
            install_cmd='ssh-keygen -t ed25519 -C "your_email@example.com"',
        )
    key_patterns = ["id_ed25519", "id_rsa", "id_ecdsa", "id_dsa"]
    for pattern in key_patterns:
        key_file = ssh_dir / pattern
        if key_file.exists():
            return CheckResult(
                name="SSH key", passed=True, detail=str(key_file.name)
            )
    return CheckResult(
        name="SSH key",
        passed=False,
        detail="no key found in ~/.ssh",
        install_cmd='ssh-keygen -t ed25519 -C "your_email@example.com"',
    )


def check_ssh_agent() -> CheckResult:
    """Check if the SSH agent is running with a loaded key."""
    try:
        result = subprocess.run(
            ["ssh-add", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            count = len(result.stdout.strip().split("\n"))
            return CheckResult(
                name="SSH agent",
                passed=True,
                detail=f"{count} key(s) loaded",
            )
        return CheckResult(
            name="SSH agent",
            passed=False,
            detail="no keys loaded",
            install_cmd="ssh-add",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return CheckResult(
            name="SSH agent",
            passed=False,
            detail="agent not running",
            install_cmd="eval $(ssh-agent -s) && ssh-add",
        )


def check_fuse(platform: Platform) -> CheckResult:
    """Check if a FUSE layer is installed."""
    if platform == "macos":
        # Check for FUSE-T (preferred) or macFUSE
        try:
            result = subprocess.run(
                ["brew", "list", "--cask", "fuse-t"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return CheckResult(name="FUSE layer", passed=True, detail="fuse-t")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return CheckResult(
            name="FUSE layer",
            passed=False,
            detail="not found",
            install_cmd=get_install_command("macos"),
        )
    else:
        # Linux/WSL2: check for fusermount3
        if shutil.which("fusermount3") or shutil.which("fusermount"):
            return CheckResult(name="FUSE layer", passed=True, detail="fuse3")
        return CheckResult(
            name="FUSE layer",
            passed=False,
            detail="not found",
            install_cmd=get_install_command(platform),
        )


def run_checks(platform: Platform) -> list[CheckResult]:
    """Run all prerequisite checks and return results."""
    results = [
        check_rclone(),
        check_ssh_key(),
        check_ssh_agent(),
        check_fuse(platform),
    ]
    return results


def print_results(results: list[CheckResult]) -> None:
    """Print check results in the doctor output format."""
    for result in results:
        status = click.style("[PASS]", fg="green") if result.passed else click.style("[FAIL]", fg="red")
        name = result.name.ljust(20, ".")
        click.echo(f"{status} {name} {result.detail}")


def prompt_install(result: CheckResult) -> None:
    """Prompt the user to install a missing prerequisite."""
    if result.passed or not result.install_cmd:
        return

    choice = click.prompt(
        f"       Install automatically? [Y/n/manual]",
        type=click.Choice(["Y", "n", "manual"], case_sensitive=False),
        default="Y",
        show_choices=False,
    )
    if choice.lower() == "y":
        click.echo(f"       Running: {result.install_cmd}")
        subprocess.run(result.install_cmd, shell=True)
    elif choice.lower() == "manual":
        click.echo(f"       Run manually: {result.install_cmd}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_doctor.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 5: Wire `doctor` into CLI**

Add to `src/remote_mount/cli.py`:

```python
"""CLI entry point for remote-mount."""

import click

from remote_mount import __version__


@click.group()
@click.version_option(version=__version__, prog_name="remote-mount")
def cli() -> None:
    """Manage persistent remote filesystem mounts using rclone SFTP."""


@cli.command()
def doctor() -> None:
    """Check and install prerequisites."""
    from remote_mount.doctor import run_checks, print_results, prompt_install
    from remote_mount.platform import detect_platform

    platform = detect_platform()
    click.echo(f"Platform: {platform}\n")

    results = run_checks(platform)
    print_results(results)

    # Offer to install anything that's missing
    failed = [r for r in results if not r.passed and r.install_cmd]
    if failed:
        click.echo()
        for result in failed:
            prompt_install(result)
    elif all(r.passed for r in results):
        click.echo("\nAll prerequisites satisfied!")
```

- [ ] **Step 6: Add a CLI test for the doctor command**

Append to `tests/test_cli.py`:

```python
from unittest.mock import patch, MagicMock
from remote_mount.doctor import CheckResult


def test_doctor_command_runs() -> None:
    """Doctor command runs and produces output."""
    mock_results = [
        CheckResult(name="rclone", passed=True, detail="v1.68.2"),
        CheckResult(name="SSH key", passed=True, detail="id_ed25519"),
        CheckResult(name="SSH agent", passed=True, detail="1 key(s) loaded"),
        CheckResult(name="FUSE layer", passed=True, detail="fuse-t"),
    ]
    runner = CliRunner()
    with patch("remote_mount.cli.detect_platform", return_value="macos"):
        with patch("remote_mount.cli.run_checks", return_value=mock_results):
            # Import after patching to avoid issues
            pass
    # Test via direct import patching
    with patch("remote_mount.doctor.run_checks", return_value=mock_results):
        with patch("remote_mount.platform.detect_platform", return_value="macos"):
            result = runner.invoke(cli, ["doctor"])
            assert result.exit_code == 0
            assert "Platform" in result.output
```

- [ ] **Step 7: Run all tests**

```bash
uv run pytest tests/test_cli.py tests/test_doctor.py -v
```

Expected: All tests PASS.

- [ ] **Step 8: Commit**

```bash
git add src/remote_mount/doctor.py src/remote_mount/cli.py tests/test_doctor.py tests/test_cli.py
git commit -m "feat: doctor command with prerequisite checks and install prompts"
```

---

### Task 5: Mount / Unmount

**Files:**
- Create: `src/remote_mount/mounts.py`
- Create: `tests/test_mounts.py`
- Modify: `src/remote_mount/cli.py` (add `mount` and `unmount` commands)

- [ ] **Step 1: Write failing tests in `tests/test_mounts.py`**

```python
"""Tests for mount/unmount operations."""

from pathlib import Path
from unittest.mock import patch, MagicMock, call

from remote_mount.config import MountConfig, RcloneConfig
from remote_mount.mounts import build_rclone_command, do_mount, do_unmount, is_mounted


class TestBuildRcloneCommand:
    def test_basic_mount_command(self) -> None:
        mount = MountConfig(
            host="spark-1",
            remote_path="/",
            mount_point="/home/user/mnt/spark-1",
        )
        rclone = RcloneConfig()
        cmd = build_rclone_command(mount, rclone)
        assert cmd[0] == "rclone"
        assert cmd[1] == "mount"
        assert ":sftp:/" in cmd
        assert "/home/user/mnt/spark-1" in cmd
        assert "--sftp-host" in cmd
        assert "spark-1" in cmd
        assert "--vfs-cache-mode" in cmd
        assert "writes" in cmd
        assert "--daemon" in cmd

    def test_custom_remote_path(self) -> None:
        mount = MountConfig(
            host="spark-2",
            remote_path="/home/bkrabach",
            mount_point="/home/user/mnt/spark-2",
        )
        rclone = RcloneConfig()
        cmd = build_rclone_command(mount, rclone)
        assert ":sftp:/home/bkrabach" in cmd

    def test_extra_args_passed_through(self) -> None:
        mount = MountConfig(
            host="test",
            remote_path="/",
            mount_point="/mnt/test",
        )
        rclone = RcloneConfig(extra_args=["--transfers", "4"])
        cmd = build_rclone_command(mount, rclone)
        assert "--transfers" in cmd
        assert "4" in cmd

    def test_buffer_size(self) -> None:
        mount = MountConfig(host="test", remote_path="/", mount_point="/mnt/test")
        rclone = RcloneConfig(buffer_size="128M")
        cmd = build_rclone_command(mount, rclone)
        assert "--buffer-size" in cmd
        assert "128M" in cmd


class TestDoMount:
    def test_creates_mount_point_dir(self, tmp_path: Path) -> None:
        mount_dir = tmp_path / "mnt" / "test"
        mount = MountConfig(
            host="test",
            remote_path="/",
            mount_point=str(mount_dir),
        )
        rclone = RcloneConfig()
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")):
            do_mount(mount, rclone)
        assert mount_dir.exists()

    def test_returns_error_on_failure(self, tmp_path: Path) -> None:
        mount = MountConfig(
            host="test",
            remote_path="/",
            mount_point=str(tmp_path / "mnt"),
        )
        rclone = RcloneConfig()
        with patch(
            "subprocess.run",
            return_value=MagicMock(returncode=1, stderr="mount failed: connection refused"),
        ):
            error = do_mount(mount, rclone)
        assert error is not None
        assert "connection refused" in error


class TestDoUnmount:
    def test_calls_unmount_command(self) -> None:
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            do_unmount("/mnt/test", "macos")
            mock_run.assert_called_once_with(
                ["umount", "/mnt/test"],
                capture_output=True,
                text=True,
                timeout=10,
            )

    def test_linux_uses_fusermount(self) -> None:
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            do_unmount("/mnt/test", "linux")
            mock_run.assert_called_once_with(
                ["fusermount", "-uz", "/mnt/test"],
                capture_output=True,
                text=True,
                timeout=10,
            )


class TestIsMounted:
    def test_mounted_and_responsive(self, tmp_path: Path) -> None:
        mount_point = tmp_path / "mnt"
        mount_point.mkdir()
        (mount_point / "testfile").write_text("hello")
        assert is_mounted(str(mount_point)) is True

    def test_not_mounted(self, tmp_path: Path) -> None:
        mount_point = tmp_path / "nonexistent"
        assert is_mounted(str(mount_point)) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_mounts.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'remote_mount.mounts'`

- [ ] **Step 3: Implement `src/remote_mount/mounts.py`**

```python
"""Mount and unmount operations using rclone's SFTP backend.

Builds rclone commands using CLI flags (`:sftp:` backend syntax)
instead of managing rclone.conf.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from remote_mount.config import MountConfig, RcloneConfig
from remote_mount.platform import Platform, get_unmount_command


def build_rclone_command(mount: MountConfig, rclone: RcloneConfig) -> list[str]:
    """Build the rclone mount command for a given mount config."""
    remote = f":sftp:{mount.remote_path}"
    mount_point = str(Path(mount.mount_point).expanduser())

    cmd = [
        "rclone",
        "mount",
        remote,
        mount_point,
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
    """Mount a remote filesystem. Returns None on success, error string on failure."""
    mount_point = Path(mount.mount_point).expanduser()
    mount_point.mkdir(parents=True, exist_ok=True)

    cmd = build_rclone_command(mount, rclone)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        return result.stderr.strip() or f"rclone exited with code {result.returncode}"
    return None


def do_unmount(mount_point: str, platform: Platform) -> str | None:
    """Unmount a FUSE mount. Returns None on success, error string on failure."""
    cmd = get_unmount_command(platform, mount_point)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return result.stderr.strip() or f"unmount exited with code {result.returncode}"
    except subprocess.TimeoutExpired:
        return "unmount timed out"
    return None


def is_mounted(mount_point: str) -> bool:
    """Check if a mount point is mounted and responsive."""
    path = Path(mount_point)
    if not path.exists():
        return False
    try:
        # Try to stat something inside the mount — this will hang/fail if stale
        os.stat(mount_point)
        list(path.iterdir())
        return True
    except (OSError, PermissionError):
        return False


def check_host_reachable(host: str) -> bool:
    """Check if a host is reachable via SSH in batch mode."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, "true"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_mounts.py -v
```

Expected: All 9 tests PASS.

- [ ] **Step 5: Wire `mount` and `unmount` into CLI**

Add to `src/remote_mount/cli.py` (after the `doctor` command):

```python
@cli.command()
@click.argument("name", required=False)
@click.option("--all", "mount_all", is_flag=True, help="Mount all auto_mount entries.")
def mount(name: str | None, mount_all: bool) -> None:
    """Mount a remote filesystem (or all with --all)."""
    from remote_mount.config import load_config
    from remote_mount.mounts import do_mount, is_mounted
    from remote_mount.platform import detect_platform

    config = load_config()
    if not config.mounts:
        click.echo("No mounts configured. Run 'remote-mount add' first.")
        return

    if mount_all:
        targets = {n: m for n, m in config.mounts.items() if m.auto_mount}
    elif name:
        if name not in config.mounts:
            click.echo(f"Mount '{name}' not found in config.")
            return
        targets = {name: config.mounts[name]}
    else:
        click.echo("Specify a mount name or use --all.")
        return

    for mount_name, mount_cfg in targets.items():
        mount_point = str(mount_cfg.resolved_mount_point)
        if is_mounted(mount_point):
            click.echo(f"{mount_name}: already mounted at {mount_point}")
            continue
        click.echo(f"{mount_name}: mounting {mount_cfg.host}:{mount_cfg.remote_path} -> {mount_point}")
        error = do_mount(mount_cfg, config.rclone)
        if error:
            click.echo(f"  FAILED: {error}", err=True)
        else:
            click.echo(f"  OK")


@cli.command()
@click.argument("name", required=False)
@click.option("--all", "unmount_all", is_flag=True, help="Unmount all mounts.")
def unmount(name: str | None, unmount_all: bool) -> None:
    """Unmount a remote filesystem (or all with --all)."""
    from remote_mount.config import load_config
    from remote_mount.mounts import do_unmount, is_mounted
    from remote_mount.platform import detect_platform

    config = load_config()
    platform = detect_platform()

    if unmount_all:
        targets = config.mounts
    elif name:
        if name not in config.mounts:
            click.echo(f"Mount '{name}' not found in config.")
            return
        targets = {name: config.mounts[name]}
    else:
        click.echo("Specify a mount name or use --all.")
        return

    for mount_name, mount_cfg in targets.items():
        mount_point = str(mount_cfg.resolved_mount_point)
        if not is_mounted(mount_point):
            click.echo(f"{mount_name}: not mounted")
            continue
        click.echo(f"{mount_name}: unmounting {mount_point}")
        error = do_unmount(mount_point, platform)
        if error:
            click.echo(f"  FAILED: {error}", err=True)
        else:
            click.echo(f"  OK")
```

- [ ] **Step 6: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: All tests across all test files PASS.

- [ ] **Step 7: Commit**

```bash
git add src/remote_mount/mounts.py src/remote_mount/cli.py tests/test_mounts.py
git commit -m "feat: mount and unmount commands via rclone SFTP backend"
```

---

## Phase 2: Features (Tasks 6–9)

### Task 6: SSH Config Management

**Files:**
- Create: `src/remote_mount/ssh_config.py`
- Create: `tests/test_ssh_config.py`

- [ ] **Step 1: Write failing tests in `tests/test_ssh_config.py`**

```python
"""Tests for SSH config parsing and Tailscale failover Host block management."""

from pathlib import Path

from remote_mount.ssh_config import (
    generate_host_block,
    find_host_block,
    write_host_block,
    MANAGED_MARKER,
)


SAMPLE_CONFIG = """\
Host github.com
    User git
    IdentityFile ~/.ssh/id_ed25519

# managed by remote-mount
Host spark-1
    User bkrabach
    IdentityFile ~/.ssh/id_ed25519
    ProxyCommand bash -c 'for addr in 100.124.126.19 192.168.1.5 spark-1.tail8f3c4e.ts.net; do nc -z -G 3 "$addr" 22 2>/dev/null && exec nc "$addr" 22; done; echo "spark-1: all addresses unreachable" >&2; exit 1'
"""


class TestGenerateHostBlock:
    def test_basic_block(self) -> None:
        block = generate_host_block(
            host="spark-1",
            user="bkrabach",
            identity_file="~/.ssh/id_ed25519",
            tailscale_ip="100.124.126.19",
            lan_ip="192.168.1.5",
            fqdn="spark-1.tail8f3c4e.ts.net",
        )
        assert "# managed by remote-mount" in block
        assert "Host spark-1" in block
        assert "User bkrabach" in block
        assert "IdentityFile ~/.ssh/id_ed25519" in block
        assert "100.124.126.19" in block
        assert "192.168.1.5" in block
        assert "spark-1.tail8f3c4e.ts.net" in block

    def test_no_lan_ip(self) -> None:
        block = generate_host_block(
            host="spark-2",
            user="bkrabach",
            identity_file="~/.ssh/id_ed25519",
            tailscale_ip="100.93.134.115",
            lan_ip="",
            fqdn="spark-2.tail8f3c4e.ts.net",
        )
        assert "100.93.134.115" in block
        assert "spark-2.tail8f3c4e.ts.net" in block
        # LAN IP should not appear as an empty string between other addrs
        assert "  " not in block.split("for addr in")[1].split(";")[0]


class TestFindHostBlock:
    def test_find_managed_block(self) -> None:
        result = find_host_block(SAMPLE_CONFIG, "spark-1")
        assert result is not None
        assert result["managed"] is True
        assert "spark-1" in result["content"]

    def test_find_unmanaged_block(self) -> None:
        result = find_host_block(SAMPLE_CONFIG, "github.com")
        assert result is not None
        assert result["managed"] is False

    def test_not_found(self) -> None:
        result = find_host_block(SAMPLE_CONFIG, "nonexistent")
        assert result is None


class TestWriteHostBlock:
    def test_append_new_block(self, tmp_path: Path) -> None:
        ssh_config = tmp_path / "config"
        ssh_config.write_text("Host github.com\n    User git\n")
        new_block = "# managed by remote-mount\nHost spark-1\n    User bkrabach\n"
        result = write_host_block(ssh_config, "spark-1", new_block)
        assert result == "added"
        content = ssh_config.read_text()
        assert "github.com" in content
        assert "spark-1" in content
        assert "# managed by remote-mount" in content

    def test_update_managed_block(self, tmp_path: Path) -> None:
        ssh_config = tmp_path / "config"
        ssh_config.write_text(SAMPLE_CONFIG)
        new_block = "# managed by remote-mount\nHost spark-1\n    User newuser\n"
        result = write_host_block(ssh_config, "spark-1", new_block)
        assert result == "updated"
        content = ssh_config.read_text()
        assert "newuser" in content
        assert "bkrabach" not in content
        # Unmanaged block should be untouched
        assert "github.com" in content

    def test_warn_on_unmanaged_block(self, tmp_path: Path) -> None:
        ssh_config = tmp_path / "config"
        ssh_config.write_text("Host myhost\n    User existing\n")
        new_block = "# managed by remote-mount\nHost myhost\n    User new\n"
        result = write_host_block(ssh_config, "myhost", new_block)
        assert result == "conflict"
        # File should NOT be modified
        content = ssh_config.read_text()
        assert "existing" in content
        assert "# managed by remote-mount" not in content

    def test_creates_file_if_missing(self, tmp_path: Path) -> None:
        ssh_config = tmp_path / "config"
        new_block = "# managed by remote-mount\nHost spark-1\n    User bkrabach\n"
        result = write_host_block(ssh_config, "spark-1", new_block)
        assert result == "added"
        assert ssh_config.exists()
        assert "spark-1" in ssh_config.read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_ssh_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'remote_mount.ssh_config'`

- [ ] **Step 3: Implement `src/remote_mount/ssh_config.py`**

```python
"""SSH config parsing and writing for Tailscale failover.

Manages Host blocks in ~/.ssh/config with `# managed by remote-mount`
markers. Only touches blocks it owns — never modifies unmanaged blocks.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

MANAGED_MARKER = "# managed by remote-mount"


class HostBlockInfo(TypedDict):
    """Info about an existing Host block in SSH config."""

    content: str
    start_line: int
    end_line: int
    managed: bool


def generate_host_block(
    host: str,
    user: str,
    identity_file: str,
    tailscale_ip: str,
    lan_ip: str = "",
    fqdn: str = "",
) -> str:
    """Generate an SSH config Host block with Tailscale failover ProxyCommand."""
    addrs = [tailscale_ip]
    if lan_ip:
        addrs.append(lan_ip)
    if fqdn:
        addrs.append(fqdn)
    addr_str = " ".join(addrs)

    proxy_cmd = (
        f"bash -c 'for addr in {addr_str}; "
        f'do nc -z -G 3 "$addr" 22 2>/dev/null && exec nc "$addr" 22; done; '
        f'echo "{host}: all addresses unreachable" >&2; exit 1\''
    )

    lines = [
        MANAGED_MARKER,
        f"Host {host}",
        f"    User {user}",
        f"    IdentityFile {identity_file}",
        f"    ProxyCommand {proxy_cmd}",
    ]
    return "\n".join(lines) + "\n"


def find_host_block(config_text: str, host: str) -> HostBlockInfo | None:
    """Find a Host block for the given host in SSH config text.

    Returns info about the block, or None if not found.
    """
    lines = config_text.split("\n")
    host_pattern = re.compile(rf"^Host\s+{re.escape(host)}\s*$")

    i = 0
    while i < len(lines):
        if host_pattern.match(lines[i].strip()):
            # Found the Host line — determine block boundaries
            start_line = i
            managed = False

            # Check if the line above is our managed marker
            if i > 0 and lines[i - 1].strip() == MANAGED_MARKER:
                start_line = i - 1
                managed = True

            # Find end of block (next Host line or end of file)
            end_line = i + 1
            while end_line < len(lines):
                stripped = lines[end_line].strip()
                if stripped.startswith("Host ") or stripped == MANAGED_MARKER:
                    break
                end_line += 1

            # Strip trailing blank lines from block
            while end_line > start_line and not lines[end_line - 1].strip():
                end_line -= 1

            block_content = "\n".join(lines[start_line:end_line])
            return HostBlockInfo(
                content=block_content,
                start_line=start_line,
                end_line=end_line,
                managed=managed,
            )
        i += 1

    return None


def write_host_block(
    config_path: Path,
    host: str,
    new_block: str,
) -> str:
    """Write a Host block to SSH config.

    Returns:
        "added" — appended new block
        "updated" — replaced existing managed block
        "conflict" — existing unmanaged block, file NOT modified
    """
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(new_block)
        return "added"

    config_text = config_path.read_text()
    existing = find_host_block(config_text, host)

    if existing is None:
        # Append new block
        separator = "\n" if config_text and not config_text.endswith("\n") else ""
        extra_newline = "\n" if config_text.strip() else ""
        config_path.write_text(config_text + separator + extra_newline + new_block)
        return "added"

    if not existing["managed"]:
        # Existing block we don't own — don't touch it
        return "conflict"

    # Replace our managed block
    lines = config_text.split("\n")
    new_lines = lines[: existing["start_line"]] + new_block.rstrip("\n").split("\n") + lines[existing["end_line"]:]
    config_path.write_text("\n".join(new_lines))
    return "updated"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_ssh_config.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/remote_mount/ssh_config.py tests/test_ssh_config.py
git commit -m "feat: SSH config management with Tailscale failover Host blocks"
```

---

### Task 7: Add Wizard

**Files:**
- Modify: `src/remote_mount/cli.py` (add `add` and `remove` commands)
- Modify: `tests/test_cli.py` (add CLI tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`:

```python
import yaml


def test_add_basic_mount(tmp_path: Path) -> None:
    """Add wizard creates a config entry with prompted values."""
    from remote_mount.config import load_config

    config_file = tmp_path / "config.yaml"
    runner = CliRunner()

    # Simulate user input: host, remote_path, mount_point, auto_mount, watchdog
    user_input = "myhost\n/data\n~/mnt/myhost\ny\nn\nn\n"
    with patch("remote_mount.cli.get_config_path", return_value=config_file):
        result = runner.invoke(cli, ["add"], input=user_input)

    assert result.exit_code == 0
    config = load_config(config_file)
    assert "myhost" in config.mounts
    assert config.mounts["myhost"].host == "myhost"
    assert config.mounts["myhost"].remote_path == "/data"


def test_remove_mount(tmp_path: Path) -> None:
    """Remove command deletes a mount from config."""
    from remote_mount.config import load_config, save_config, Config, MountConfig

    config_file = tmp_path / "config.yaml"
    config = Config()
    config.mounts["test"] = MountConfig(host="test", remote_path="/", mount_point="~/mnt/test")
    save_config(config, config_file)

    runner = CliRunner()
    with patch("remote_mount.cli.get_config_path", return_value=config_file):
        result = runner.invoke(cli, ["remove", "test"], input="y\n")

    assert result.exit_code == 0
    loaded = load_config(config_file)
    assert "test" not in loaded.mounts
```

Also add `from pathlib import Path` and `from unittest.mock import patch` to the imports at the top of `tests/test_cli.py` (if not already present).

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_cli.py::test_add_basic_mount tests/test_cli.py::test_remove_mount -v
```

Expected: FAIL — missing CLI commands.

- [ ] **Step 3: Implement `add` and `remove` commands in `src/remote_mount/cli.py`**

Add these commands to `cli.py`:

```python
@cli.command()
def add() -> None:
    """Interactive wizard to add a new mount."""
    from remote_mount.config import (
        get_config_path,
        load_config,
        save_config,
        MountConfig,
    )
    from remote_mount.ssh_config import generate_host_block, write_host_block

    config_path = get_config_path()
    config = load_config(config_path)

    host = click.prompt("SSH host (as in ~/.ssh/config or hostname)")
    remote_path = click.prompt("Remote path", default="/")
    default_mount = f"~/mnt/{host}"
    mount_point = click.prompt("Local mount point", default=default_mount)
    auto_mount = click.confirm("Auto-mount on 'remote-mount mount --all'?", default=True)
    watchdog = click.confirm("Enable watchdog auto-reconnect?", default=False)

    config.mounts[host] = MountConfig(
        host=host,
        remote_path=remote_path,
        mount_point=mount_point,
        auto_mount=auto_mount,
        watchdog=watchdog,
    )

    # Optional Tailscale setup
    setup_tailscale = click.confirm("Enable Tailscale failover for this host?", default=False)
    if setup_tailscale:
        from remote_mount.config import TailscaleHostConfig
        from pathlib import Path

        ts_ip = click.prompt("Tailscale IP")
        lan_ip = click.prompt("LAN IP (optional, press Enter to skip)", default="")
        fqdn = click.prompt("FQDN (e.g., host.tail1234.ts.net)")
        user = click.prompt("SSH user", default="")
        identity_file = click.prompt("SSH identity file", default="~/.ssh/id_ed25519")

        config.tailscale.enabled = True
        config.tailscale.hosts[host] = TailscaleHostConfig(
            tailscale_ip=ts_ip,
            lan_ip=lan_ip,
            fqdn=fqdn,
        )

        # Generate and write SSH config block
        block = generate_host_block(
            host=host,
            user=user,
            identity_file=identity_file,
            tailscale_ip=ts_ip,
            lan_ip=lan_ip,
            fqdn=fqdn,
        )
        ssh_config_path = Path.home() / ".ssh" / "config"
        result = write_host_block(ssh_config_path, host, block)
        if result == "added":
            click.echo(f"Added SSH config block for {host}")
        elif result == "updated":
            click.echo(f"Updated SSH config block for {host}")
        elif result == "conflict":
            click.echo(f"WARNING: Existing SSH config block for {host} not managed by remote-mount.")
            click.echo(f"Add this manually to ~/.ssh/config:\n\n{block}")

    save_config(config, config_path)
    click.echo(f"\nMount '{host}' added. Run 'remote-mount mount {host}' to mount.")


@cli.command()
@click.argument("name")
def remove(name: str) -> None:
    """Remove a mount from configuration."""
    from remote_mount.config import get_config_path, load_config, save_config

    config_path = get_config_path()
    config = load_config(config_path)

    if name not in config.mounts:
        click.echo(f"Mount '{name}' not found in config.")
        return

    if not click.confirm(f"Remove mount '{name}'?"):
        click.echo("Cancelled.")
        return

    del config.mounts[name]
    save_config(config, config_path)
    click.echo(f"Mount '{name}' removed.")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: All CLI tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/remote_mount/cli.py tests/test_cli.py
git commit -m "feat: add wizard and remove command for mount configuration"
```

---

### Task 8: Watchdog

**Files:**
- Modify: `src/remote_mount/mounts.py` (add `watchdog_loop` function)
- Modify: `src/remote_mount/cli.py` (add hidden `_watchdog` command)
- Create: `tests/test_watchdog.py`

- [ ] **Step 1: Write failing tests in `tests/test_watchdog.py`**

```python
"""Tests for the watchdog health-check loop."""

from pathlib import Path
from unittest.mock import patch, MagicMock, call

from remote_mount.config import Config, MountConfig, WatchdogConfig, RcloneConfig
from remote_mount.mounts import watchdog_tick, WatchdogState


class TestWatchdogTick:
    """Test a single tick of the watchdog loop (not the infinite loop)."""

    def test_healthy_mount_resets_backoff(self) -> None:
        mount = MountConfig(
            host="spark-1", remote_path="/", mount_point="/mnt/spark-1", watchdog=True
        )
        state = WatchdogState(backoff=60)
        with patch("remote_mount.mounts.is_mounted", return_value=True):
            result = watchdog_tick(mount, state, RcloneConfig(), "macos")
        assert result.backoff == 5  # reset to default base
        assert result.action == "healthy"

    def test_unhealthy_host_reachable_remounts(self) -> None:
        mount = MountConfig(
            host="spark-1", remote_path="/", mount_point="/mnt/spark-1", watchdog=True
        )
        state = WatchdogState(backoff=5)
        with patch("remote_mount.mounts.is_mounted", return_value=False):
            with patch("subprocess.run", return_value=MagicMock(returncode=0)):
                with patch("remote_mount.mounts.check_host_reachable", return_value=True):
                    with patch("remote_mount.mounts.do_mount", return_value=None):
                        with patch("remote_mount.mounts.do_unmount", return_value=None):
                            result = watchdog_tick(mount, state, RcloneConfig(), "macos")
        assert result.action == "remounted"

    def test_unhealthy_host_unreachable_backs_off(self) -> None:
        mount = MountConfig(
            host="spark-1", remote_path="/", mount_point="/mnt/spark-1", watchdog=True
        )
        state = WatchdogState(backoff=5)
        with patch("remote_mount.mounts.is_mounted", return_value=False):
            with patch("remote_mount.mounts.do_unmount", return_value=None):
                with patch("remote_mount.mounts.check_host_reachable", return_value=False):
                    result = watchdog_tick(mount, state, RcloneConfig(), "macos")
        assert result.action == "unreachable"
        assert result.backoff == 10  # doubled from 5

    def test_backoff_caps_at_max(self) -> None:
        mount = MountConfig(
            host="spark-1", remote_path="/", mount_point="/mnt/spark-1", watchdog=True
        )
        state = WatchdogState(backoff=200)
        with patch("remote_mount.mounts.is_mounted", return_value=False):
            with patch("remote_mount.mounts.do_unmount", return_value=None):
                with patch("remote_mount.mounts.check_host_reachable", return_value=False):
                    result = watchdog_tick(mount, state, RcloneConfig(), "macos")
        assert result.backoff == 300  # capped at default max
        # Verify it doesn't go higher
        state2 = WatchdogState(backoff=300)
        with patch("remote_mount.mounts.is_mounted", return_value=False):
            with patch("remote_mount.mounts.do_unmount", return_value=None):
                with patch("remote_mount.mounts.check_host_reachable", return_value=False):
                    result2 = watchdog_tick(mount, state2, RcloneConfig(), "macos")
        assert result2.backoff == 300  # stays at max
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_watchdog.py -v
```

Expected: FAIL — `ImportError: cannot import name 'watchdog_tick'`

- [ ] **Step 3: Add `watchdog_tick` and `WatchdogState` to `src/remote_mount/mounts.py`**

Add to the end of `src/remote_mount/mounts.py`:

```python
import logging
import time
from dataclasses import dataclass


@dataclass
class WatchdogState:
    """Mutable state for one mount's watchdog tracking."""

    backoff: int = 5
    action: str = ""


def watchdog_tick(
    mount: MountConfig,
    state: WatchdogState,
    rclone: RcloneConfig,
    platform: Platform,
    backoff_base: int = 5,
    backoff_max: int = 300,
) -> WatchdogState:
    """Run one tick of the watchdog loop for a single mount.

    Returns updated WatchdogState with the action taken.
    """
    mount_point = str(Path(mount.mount_point).expanduser())

    if is_mounted(mount_point):
        state.backoff = backoff_base
        state.action = "healthy"
        return state

    # Mount is unhealthy — clean up stale mount
    do_unmount(mount_point, platform)

    # Check if host is reachable
    if not check_host_reachable(mount.host):
        state.action = "unreachable"
        state.backoff = min(state.backoff * 2, backoff_max)
        return state

    # Host reachable — attempt remount
    error = do_mount(mount, rclone)
    if error:
        state.action = "mount_failed"
        state.backoff = min(state.backoff * 2, backoff_max)
    else:
        state.action = "remounted"
        state.backoff = backoff_base

    return state


def trim_log(log_path: Path, max_lines: int = 1000, keep_lines: int = 500) -> None:
    """Trim log file if it exceeds max_lines, keeping the last keep_lines."""
    if not log_path.exists():
        return
    lines = log_path.read_text().splitlines()
    if len(lines) > max_lines:
        log_path.write_text("\n".join(lines[-keep_lines:]) + "\n")


def watchdog_loop(config_path: Path | None = None) -> None:
    """Main watchdog loop — runs forever, checking all watchdog-enabled mounts."""
    from remote_mount.config import load_config, get_log_path, get_config_path
    from remote_mount.platform import detect_platform

    if config_path is None:
        config_path = get_config_path()

    log_path = get_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("remote-mount")

    platform = detect_platform()
    logger.info("Watchdog started on platform: %s", platform)

    # Trim log on startup
    trim_log(log_path)

    # Per-mount state
    states: dict[str, WatchdogState] = {}

    while True:
        config = load_config(config_path)
        watchdog_mounts = {
            name: m for name, m in config.mounts.items() if m.watchdog
        }

        if not watchdog_mounts:
            logger.info("No watchdog-enabled mounts, sleeping...")
            time.sleep(config.watchdog.check_interval)
            continue

        for name, mount_cfg in watchdog_mounts.items():
            if name not in states:
                states[name] = WatchdogState(backoff=config.watchdog.backoff_base)

            state = watchdog_tick(
                mount_cfg,
                states[name],
                config.rclone,
                platform,
                backoff_base=config.watchdog.backoff_base,
                backoff_max=config.watchdog.backoff_max,
            )
            states[name] = state

            if state.action != "healthy":
                logger.info("%s: %s (backoff=%ds)", name, state.action, state.backoff)

            if state.action == "unreachable":
                time.sleep(state.backoff)

        time.sleep(config.watchdog.check_interval)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_watchdog.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Add hidden `_watchdog` command to CLI**

Add to `src/remote_mount/cli.py`:

```python
@cli.command(hidden=True)
def _watchdog() -> None:
    """Hidden entry point for the watchdog service."""
    from remote_mount.mounts import watchdog_loop

    watchdog_loop()
```

- [ ] **Step 6: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/remote_mount/mounts.py src/remote_mount/cli.py tests/test_watchdog.py
git commit -m "feat: watchdog health-check loop with exponential backoff"
```

---

### Task 9: Service Management

**Files:**
- Create: `src/remote_mount/service.py`
- Create: `tests/test_service.py`
- Modify: `src/remote_mount/cli.py` (add `service` command group)

- [ ] **Step 1: Write failing tests in `tests/test_service.py`**

```python
"""Tests for service management — LaunchdManager and SystemdManager."""

import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from remote_mount.service import LaunchdManager, SystemdManager


class TestLaunchdManager:
    def test_install_creates_plist(self, tmp_path: Path) -> None:
        plist_dir = tmp_path / "Library" / "LaunchAgents"
        manager = LaunchdManager(plist_dir=plist_dir)
        with patch("shutil.which", return_value="/usr/local/bin/remote-mount"):
            path = manager.install("remote-mount _watchdog")
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "com.remote-mount.watchdog" in content
        assert "KeepAlive" in content
        assert "remote-mount" in content

    def test_install_plist_has_correct_structure(self, tmp_path: Path) -> None:
        plist_dir = tmp_path / "Library" / "LaunchAgents"
        manager = LaunchdManager(plist_dir=plist_dir)
        with patch("shutil.which", return_value="/usr/local/bin/remote-mount"):
            path = manager.install("remote-mount _watchdog")
        content = Path(path).read_text()
        assert '<?xml version="1.0"' in content
        assert "<plist" in content
        assert "ProgramArguments" in content
        assert "RunAtLoad" in content

    def test_start_calls_launchctl_bootstrap(self, tmp_path: Path) -> None:
        plist_dir = tmp_path / "Library" / "LaunchAgents"
        manager = LaunchdManager(plist_dir=plist_dir)
        # Create a fake plist so start can find it
        plist_dir.mkdir(parents=True)
        plist_path = plist_dir / "com.remote-mount.watchdog.plist"
        plist_path.write_text("<plist/>")
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            with patch("os.getuid", return_value=501):
                manager.start()
        cmd = mock_run.call_args[0][0]
        assert "launchctl" in cmd[0]
        assert "bootstrap" in cmd

    def test_stop_calls_launchctl_bootout(self, tmp_path: Path) -> None:
        plist_dir = tmp_path / "Library" / "LaunchAgents"
        manager = LaunchdManager(plist_dir=plist_dir)
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            with patch("os.getuid", return_value=501):
                manager.stop()
        cmd = mock_run.call_args[0][0]
        assert "launchctl" in cmd[0]
        assert "bootout" in cmd


class TestSystemdManager:
    def test_install_creates_unit_file(self, tmp_path: Path) -> None:
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        manager = SystemdManager(unit_dir=unit_dir)
        with patch("shutil.which", return_value="/usr/local/bin/remote-mount"):
            path = manager.install("remote-mount _watchdog")
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "[Unit]" in content
        assert "[Service]" in content
        assert "remote-mount" in content
        assert "Restart=always" in content

    def test_start_calls_systemctl(self, tmp_path: Path) -> None:
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        manager = SystemdManager(unit_dir=unit_dir)
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            manager.start()
        calls = [c[0][0] for c in mock_run.call_args_list]
        # Should daemon-reload then start
        assert any("daemon-reload" in str(c) for c in calls)
        assert any("start" in str(c) for c in calls)

    def test_stop_calls_systemctl(self, tmp_path: Path) -> None:
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        manager = SystemdManager(unit_dir=unit_dir)
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            manager.stop()
        cmd = mock_run.call_args[0][0]
        assert "systemctl" in cmd[0]
        assert "stop" in cmd
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_service.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'remote_mount.service'`

- [ ] **Step 3: Implement `src/remote_mount/service.py`**

```python
"""Watchdog service management for launchd (macOS) and systemd (Linux/WSL2).

Each manager implements the ServiceManager interface from platform.py:
install(), start(), stop(), uninstall(), status().
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from remote_mount.platform import ServiceManager

LABEL = "com.remote-mount.watchdog"
UNIT_NAME = "remote-mount-watchdog"


class LaunchdManager(ServiceManager):
    """macOS LaunchAgent manager for the watchdog service."""

    def __init__(self, plist_dir: Path | None = None) -> None:
        if plist_dir is None:
            plist_dir = Path.home() / "Library" / "LaunchAgents"
        self.plist_dir = plist_dir
        self.plist_path = self.plist_dir / f"{LABEL}.plist"

    def install(self, watchdog_cmd: str) -> str:
        """Generate and install a LaunchAgent plist."""
        remote_mount_path = shutil.which("remote-mount") or "remote-mount"

        plist_content = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{remote_mount_path}</string>
        <string>_watchdog</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""
        self.plist_dir.mkdir(parents=True, exist_ok=True)
        self.plist_path.write_text(plist_content)
        return str(self.plist_path)

    def start(self) -> None:
        """Start the watchdog via launchctl bootstrap."""
        uid = os.getuid()
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(self.plist_path)],
            capture_output=True,
        )

    def stop(self) -> None:
        """Stop the watchdog via launchctl bootout."""
        uid = os.getuid()
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}/{LABEL}"],
            capture_output=True,
        )

    def uninstall(self) -> None:
        """Stop the service and remove the plist."""
        self.stop()
        if self.plist_path.exists():
            self.plist_path.unlink()

    def status(self) -> str:
        """Check if the watchdog service is running."""
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return "running"
        return "stopped"


class SystemdManager(ServiceManager):
    """Linux/WSL2 systemd user service manager for the watchdog."""

    def __init__(self, unit_dir: Path | None = None) -> None:
        if unit_dir is None:
            unit_dir = Path.home() / ".config" / "systemd" / "user"
        self.unit_dir = unit_dir
        self.unit_path = self.unit_dir / f"{UNIT_NAME}.service"

    def install(self, watchdog_cmd: str) -> str:
        """Generate and install a systemd user unit file."""
        remote_mount_path = shutil.which("remote-mount") or "remote-mount"

        unit_content = f"""\
[Unit]
Description=remote-mount watchdog
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={remote_mount_path} _watchdog
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        self.unit_path.write_text(unit_content)
        return str(self.unit_path)

    def start(self) -> None:
        """Start the watchdog via systemctl --user."""
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
        )
        subprocess.run(
            ["systemctl", "--user", "start", UNIT_NAME],
            capture_output=True,
        )

    def stop(self) -> None:
        """Stop the watchdog via systemctl --user."""
        subprocess.run(
            ["systemctl", "--user", "stop", UNIT_NAME],
            capture_output=True,
        )

    def uninstall(self) -> None:
        """Stop the service and remove the unit file."""
        self.stop()
        if self.unit_path.exists():
            self.unit_path.unlink()
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
        )

    def status(self) -> str:
        """Check if the watchdog service is running."""
        result = subprocess.run(
            ["systemctl", "--user", "is-active", UNIT_NAME],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or "stopped"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_service.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 5: Wire `service` command group into CLI**

Add to `src/remote_mount/cli.py`:

```python
@cli.group()
def service() -> None:
    """Manage the watchdog background service."""


@service.command()
def install() -> None:
    """Generate and install the watchdog service."""
    from remote_mount.platform import detect_platform, get_service_manager

    platform = detect_platform()
    manager = get_service_manager(platform)
    path = manager.install("remote-mount _watchdog")
    click.echo(f"Service installed: {path}")
    click.echo("Run 'remote-mount service start' to start it.")


@service.command()
def start() -> None:
    """Start the watchdog service."""
    from remote_mount.platform import detect_platform, get_service_manager

    manager = get_service_manager(detect_platform())
    manager.start()
    click.echo("Watchdog service started.")


@service.command()
def stop() -> None:
    """Stop the watchdog service."""
    from remote_mount.platform import detect_platform, get_service_manager

    manager = get_service_manager(detect_platform())
    manager.stop()
    click.echo("Watchdog service stopped.")


@service.command()
def uninstall() -> None:
    """Stop and remove the watchdog service."""
    from remote_mount.platform import detect_platform, get_service_manager

    manager = get_service_manager(detect_platform())
    manager.uninstall()
    click.echo("Watchdog service uninstalled.")
```

- [ ] **Step 6: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/remote_mount/service.py src/remote_mount/cli.py tests/test_service.py
git commit -m "feat: service management with launchd and systemd support"
```

---

## Phase 3: Polish (Tasks 10–12)

### Task 10: Status & List Commands

**Files:**
- Modify: `src/remote_mount/cli.py` (add `status` and `list` commands)
- Modify: `tests/test_cli.py` (add tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`:

```python
def test_list_command_shows_mounts(tmp_path: Path) -> None:
    """List command shows configured mounts."""
    from remote_mount.config import save_config, Config, MountConfig

    config_file = tmp_path / "config.yaml"
    config = Config()
    config.mounts["spark-1"] = MountConfig(
        host="spark-1", remote_path="/", mount_point="~/mnt/spark-1", auto_mount=True, watchdog=True
    )
    config.mounts["spark-2"] = MountConfig(
        host="spark-2", remote_path="/home/user", mount_point="~/mnt/spark-2"
    )
    save_config(config, config_file)

    runner = CliRunner()
    with patch("remote_mount.cli.get_config_path", return_value=config_file):
        with patch("remote_mount.mounts.is_mounted", return_value=False):
            result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "spark-1" in result.output
    assert "spark-2" in result.output


def test_status_command(tmp_path: Path) -> None:
    """Status command shows mount health."""
    from remote_mount.config import save_config, Config, MountConfig

    config_file = tmp_path / "config.yaml"
    config = Config()
    config.mounts["test"] = MountConfig(
        host="test", remote_path="/", mount_point="~/mnt/test"
    )
    save_config(config, config_file)

    runner = CliRunner()
    with patch("remote_mount.cli.get_config_path", return_value=config_file):
        with patch("remote_mount.mounts.is_mounted", return_value=False):
            result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0
    assert "test" in result.output


def test_list_empty_config(tmp_path: Path) -> None:
    """List with no mounts configured shows helpful message."""
    config_file = tmp_path / "config.yaml"
    runner = CliRunner()
    with patch("remote_mount.cli.get_config_path", return_value=config_file):
        result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "no mounts" in result.output.lower() or "add" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_cli.py::test_list_command_shows_mounts tests/test_cli.py::test_status_command tests/test_cli.py::test_list_empty_config -v
```

Expected: FAIL — `Usage: cli [OPTIONS] COMMAND [ARGS]...` (no `list` or `status` commands).

- [ ] **Step 3: Implement `list` and `status` commands in `src/remote_mount/cli.py`**

Add to `src/remote_mount/cli.py`:

```python
@cli.command(name="list")
def list_mounts() -> None:
    """Show configured mounts and their current status."""
    from remote_mount.config import get_config_path, load_config
    from remote_mount.mounts import is_mounted

    config = load_config(get_config_path())
    if not config.mounts:
        click.echo("No mounts configured. Run 'remote-mount add' to get started.")
        return

    for name, mount_cfg in config.mounts.items():
        mount_point = str(mount_cfg.resolved_mount_point)
        mounted = is_mounted(mount_point)
        status_str = click.style("mounted", fg="green") if mounted else click.style("not mounted", fg="yellow")
        flags = []
        if mount_cfg.auto_mount:
            flags.append("auto")
        if mount_cfg.watchdog:
            flags.append("watchdog")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        click.echo(f"  {name}: {mount_cfg.host}:{mount_cfg.remote_path} -> {mount_point} ({status_str}){flag_str}")


@cli.command()
def status() -> None:
    """Show mount health and watchdog service state."""
    from remote_mount.config import get_config_path, load_config
    from remote_mount.mounts import is_mounted
    from remote_mount.platform import detect_platform

    config = load_config(get_config_path())
    platform = detect_platform()

    if not config.mounts:
        click.echo("No mounts configured.")
        return

    click.echo("Mounts:")
    for name, mount_cfg in config.mounts.items():
        mount_point = str(mount_cfg.resolved_mount_point)
        mounted = is_mounted(mount_point)
        icon = click.style("*", fg="green") if mounted else click.style("*", fg="red")
        state = "mounted" if mounted else "not mounted"
        click.echo(f"  {icon} {name}: {state} ({mount_point})")

    # Watchdog service status
    click.echo("\nWatchdog service:")
    try:
        from remote_mount.platform import get_service_manager
        manager = get_service_manager(platform)
        svc_status = manager.status()
        click.echo(f"  {svc_status}")
    except NotImplementedError:
        click.echo("  not available on this platform")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: All CLI tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/remote_mount/cli.py tests/test_cli.py
git commit -m "feat: list and status commands for mount overview"
```

---

### Task 11: Config Command

**Files:**
- Modify: `src/remote_mount/cli.py` (add `config` command group)
- Modify: `tests/test_cli.py` (add tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`:

```python
def test_config_path_command(tmp_path: Path) -> None:
    """'config path' prints the config file path."""
    config_file = tmp_path / "config.yaml"
    runner = CliRunner()
    with patch("remote_mount.cli.get_config_path", return_value=config_file):
        result = runner.invoke(cli, ["config", "path"])
    assert result.exit_code == 0
    assert str(config_file) in result.output


def test_config_edit_opens_editor(tmp_path: Path) -> None:
    """'config edit' calls click.edit with config contents."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("mounts: {}\n")
    runner = CliRunner()
    with patch("remote_mount.cli.get_config_path", return_value=config_file):
        with patch("click.edit", return_value=None) as mock_edit:
            result = runner.invoke(cli, ["config", "edit"])
    assert result.exit_code == 0
    mock_edit.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_cli.py::test_config_path_command tests/test_cli.py::test_config_edit_opens_editor -v
```

Expected: FAIL — no `config` command group.

- [ ] **Step 3: Implement `config` command group**

Add to `src/remote_mount/cli.py`:

```python
@cli.group(name="config", invoke_without_command=True)
@click.pass_context
def config_cmd(ctx: click.Context) -> None:
    """View or edit the configuration file."""
    if ctx.invoked_subcommand is None:
        # Default: open in editor
        ctx.invoke(config_edit)


@config_cmd.command(name="path")
def config_path() -> None:
    """Print the config file path."""
    from remote_mount.config import get_config_path

    click.echo(str(get_config_path()))


@config_cmd.command(name="edit")
def config_edit() -> None:
    """Open the config file in $EDITOR."""
    from remote_mount.config import get_config_path

    config_path = get_config_path()
    if not config_path.exists():
        click.echo(f"Config file doesn't exist yet: {config_path}")
        click.echo("Run 'remote-mount add' to create it.")
        return

    content = config_path.read_text()
    edited = click.edit(content, extension=".yaml")
    if edited is not None and edited != content:
        config_path.write_text(edited)
        click.echo("Config updated.")
    else:
        click.echo("No changes.")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: All CLI tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/remote_mount/cli.py tests/test_cli.py
git commit -m "feat: config command for viewing and editing configuration"
```

---

### Task 12: README & Packaging Verification

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# remote-mount

Persistent remote filesystem mounts using rclone's SFTP backend. Replaces SSHFS with cross-platform mount configuration, health monitoring, auto-reconnect, and optional Tailscale VPN failover.

## Install

```bash
uv tool install git+https://github.com/bkrabach/remote-mount
```

Or for development:

```bash
git clone https://github.com/bkrabach/remote-mount
cd remote-mount
uv venv && uv pip install -e ".[dev]"
```

## Quick Start

```bash
# Check prerequisites (rclone, FUSE, SSH)
remote-mount doctor

# Add a mount interactively
remote-mount add

# Mount it
remote-mount mount spark-1

# Or mount all configured mounts
remote-mount mount --all

# Check status
remote-mount status
```

## Watchdog (auto-reconnect)

```bash
# Install and start the background service
remote-mount service install
remote-mount service start

# Check service status
remote-mount service status

# Stop and remove
remote-mount service uninstall
```

The watchdog monitors mounts marked with `watchdog: true` in your config. When a mount drops, it cleans up the stale FUSE mount, checks if the host is reachable, and remounts automatically with exponential backoff.

## Commands

| Command | Description |
|---------|-------------|
| `remote-mount doctor` | Check & install prerequisites |
| `remote-mount add` | Interactive wizard to add a mount |
| `remote-mount remove <name>` | Remove a mount from config |
| `remote-mount list` | Show configured mounts and status |
| `remote-mount mount [name\|--all]` | Mount one or all |
| `remote-mount unmount [name\|--all]` | Unmount one or all |
| `remote-mount status` | Mount health + watchdog state |
| `remote-mount service install` | Install watchdog service |
| `remote-mount service start` | Start watchdog |
| `remote-mount service stop` | Stop watchdog |
| `remote-mount service uninstall` | Remove watchdog service |
| `remote-mount config` | Open config in $EDITOR |
| `remote-mount config path` | Print config file path |

## Configuration

Config lives at `~/.config/remote-mount/config.yaml`:

```yaml
mounts:
  spark-1:
    host: spark-1
    remote_path: /
    mount_point: ~/mnt/spark-1
    auto_mount: true
    watchdog: true

rclone:
  cache_mode: writes
  buffer_size: 64M
  extra_args: []

tailscale:
  enabled: false
  hosts:
    spark-1:
      tailscale_ip: 100.124.126.19
      lan_ip: 192.168.1.5
      fqdn: spark-1.tail8f3c4e.ts.net

watchdog:
  check_interval: 10
  backoff_base: 5
  backoff_max: 300
```

## Platform Support

| Platform | FUSE Layer | Service Manager |
|----------|-----------|-----------------|
| macOS | FUSE-T (via Homebrew) | launchd (LaunchAgent) |
| Linux | fuse3 (via apt) | systemd (user service) |
| WSL2 | fuse3 (via apt) | systemd (user service) |
| Windows | WinFsp (future) | Task Scheduler (future) |

## License

MIT
```

- [ ] **Step 2: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: All tests across all test files PASS.

- [ ] **Step 3: Verify CLI end-to-end**

```bash
uv run remote-mount --version
uv run remote-mount --help
uv run remote-mount doctor
uv run remote-mount list
uv run remote-mount config path
```

Expected: Each command runs without errors and produces expected output.

- [ ] **Step 4: Verify package installs cleanly**

```bash
uv tool install --force -e .
remote-mount --version
remote-mount --help
```

Expected: `remote-mount` is available as a standalone CLI tool and shows version 0.1.0.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: README with install, usage, and configuration reference"
```

---

## Summary

| Phase | Task | Description | Key files |
|-------|------|-------------|-----------|
| 1 | 1 | Project scaffold | `pyproject.toml`, `cli.py`, `__init__.py` |
| 1 | 2 | Platform detection | `platform.py` |
| 1 | 3 | Config management | `config.py` |
| 1 | 4 | Doctor command | `doctor.py` |
| 1 | 5 | Mount/unmount | `mounts.py` |
| 2 | 6 | SSH config | `ssh_config.py` |
| 2 | 7 | Add wizard | `cli.py` (add/remove) |
| 2 | 8 | Watchdog | `mounts.py` (watchdog_tick/loop) |
| 2 | 9 | Service management | `service.py` |
| 3 | 10 | Status & list | `cli.py` (list/status) |
| 3 | 11 | Config command | `cli.py` (config group) |
| 3 | 12 | README & packaging | `README.md` |

**Total: 12 tasks, ~55 steps, 12 commits.**

Each task follows TDD: write failing test, verify failure, implement, verify pass, commit. Every file path is exact. Every command can be copy-pasted.