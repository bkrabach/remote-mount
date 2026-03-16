# Config Management Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Implement YAML configuration loading, saving, validation, path resolution, and dataclass models for mounts, rclone, tailscale, and watchdog settings.

**Architecture:** A single `config.py` module containing: two path-resolution functions (`get_config_path`, `get_log_path`), six dataclasses modeling the YAML config structure (`MountConfig`, `RcloneConfig`, `TailscaleHostConfig`, `TailscaleConfig`, `WatchdogConfig`, `Config`), and two public functions (`load_config`, `save_config`) backed by private parsing/serialization helpers. No external dependencies beyond `pyyaml` (already in `pyproject.toml`).

**Tech Stack:** Python 3.10+, pyyaml, dataclasses, pytest

**Design document:** `docs/plans/2026-03-15-remote-mount-design.md` (see "Configuration" section)

**Depends on:** Task 1 (Project Scaffold) — `pyproject.toml`, `src/remote_mount/__init__.py`, `tests/__init__.py` must exist.

> **Spec note:** The spec summary says "7 tests" but the class-by-class breakdown (2 + 1 + 3 + 2) adds up to 8. This plan implements 8 tests matching the detailed breakdown. Human reviewer should be aware of this discrepancy — it's a typo in the spec summary, not an implementation issue.

---

### Task 1: Path Resolution Functions and Tests

**Files:**
- Create: `src/remote_mount/config.py`
- Create: `tests/test_config.py`

**Step 1: Write failing tests for path resolution in `tests/test_config.py`**

```python
"""Tests for remote_mount.config module."""

from pathlib import Path

from remote_mount.config import (
    get_config_path,
    get_log_path,
)


class TestConfigPath:
    def test_default_path(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        path = get_config_path()
        assert path == Path.home() / ".config" / "remote-mount" / "config.yaml"

    def test_xdg_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        path = get_config_path()
        assert path == tmp_path / "remote-mount" / "config.yaml"


class TestLogPath:
    def test_default_log_path(self):
        path = get_log_path()
        assert path == Path.home() / ".local" / "log" / "remote-mount.log"
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError` or `ImportError` (functions don't exist yet).

**Step 3: Implement path resolution in `src/remote_mount/config.py`**

```python
"""Configuration management for remote-mount."""

from __future__ import annotations

import os
from pathlib import Path


def get_config_path() -> Path:
    """Return path to config file, respecting XDG_CONFIG_HOME."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".config"
    return base / "remote-mount" / "config.yaml"


def get_log_path() -> Path:
    """Return path to log file."""
    return Path.home() / ".local" / "log" / "remote-mount.log"
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_config.py -v
```

Expected: 3 tests PASS (test_default_path, test_xdg_override, test_default_log_path).

**Step 5: Commit**

```bash
git add src/remote_mount/config.py tests/test_config.py
git commit -m "feat(config): add path resolution with XDG support"
```

---

### Task 2: Dataclass Models

**Files:**
- Modify: `src/remote_mount/config.py`

**Step 1: Add all six dataclasses to `src/remote_mount/config.py`**

Add these imports at the top of the file (after the existing imports):

```python
from dataclasses import dataclass, field
from typing import Any
```

Then add after the `get_log_path()` function:

```python
@dataclass
class MountConfig:
    host: str
    remote_path: str = "/"
    mount_point: str = ""
    auto_mount: bool = True
    watchdog: bool = False

    @property
    def resolved_mount_point(self) -> str:
        """Return mount_point with ~ expanded."""
        return (
            str(Path(self.mount_point).expanduser())
            if self.mount_point
            else self.mount_point
        )


@dataclass
class RcloneConfig:
    cache_mode: str = "writes"
    buffer_size: str = "64M"
    extra_args: list[str] = field(default_factory=list)


@dataclass
class TailscaleHostConfig:
    tailscale_ip: str = ""
    lan_ip: str = ""
    fqdn: str = ""


@dataclass
class TailscaleConfig:
    enabled: bool = False
    hosts: dict[str, TailscaleHostConfig] = field(default_factory=dict)


@dataclass
class WatchdogConfig:
    check_interval: int = 10
    backoff_base: int = 5
    backoff_max: int = 300


@dataclass
class Config:
    mounts: dict[str, MountConfig] = field(default_factory=dict)
    rclone: RcloneConfig = field(default_factory=RcloneConfig)
    tailscale: TailscaleConfig = field(default_factory=TailscaleConfig)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)
```

**Step 2: Verify existing tests still pass**

```bash
uv run pytest tests/test_config.py -v
```

Expected: 3 tests PASS (no regressions).

**Step 3: Commit**

```bash
git add src/remote_mount/config.py
git commit -m "feat(config): add dataclass models for all config sections"
```

---

### Task 3: load_config with Tests

**Files:**
- Modify: `src/remote_mount/config.py`
- Modify: `tests/test_config.py`

**Step 1: Write failing tests for load_config in `tests/test_config.py`**

Add these imports at the top of the test file (replace the existing import block):

```python
from pathlib import Path

import yaml

from remote_mount.config import (
    Config,
    MountConfig,
    RcloneConfig,
    TailscaleConfig,
    TailscaleHostConfig,
    WatchdogConfig,
    get_config_path,
    get_log_path,
    load_config,
)
```

Then add this test class after `TestLogPath`:

```python
class TestLoadConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        config_path = tmp_path / "nonexistent.yaml"
        config = load_config(config_path)
        assert isinstance(config, Config)
        assert config.mounts == {}
        assert isinstance(config.rclone, RcloneConfig)
        assert config.rclone.cache_mode == "writes"
        assert config.rclone.buffer_size == "64M"
        assert config.rclone.extra_args == []
        assert isinstance(config.tailscale, TailscaleConfig)
        assert config.tailscale.enabled is False
        assert config.tailscale.hosts == {}
        assert isinstance(config.watchdog, WatchdogConfig)
        assert config.watchdog.check_interval == 10
        assert config.watchdog.backoff_base == 5
        assert config.watchdog.backoff_max == 300

    def test_existing_config_parsed(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        data = {
            "mounts": {
                "myserver": {
                    "host": "myserver",
                    "remote_path": "/data",
                    "mount_point": "/mnt/myserver",
                    "auto_mount": False,
                    "watchdog": True,
                }
            },
            "rclone": {
                "cache_mode": "full",
                "buffer_size": "128M",
                "extra_args": ["--vfs-cache-max-size", "10G"],
            },
            "tailscale": {
                "enabled": True,
                "hosts": {
                    "myserver": {
                        "tailscale_ip": "100.64.0.1",
                        "lan_ip": "192.168.1.10",
                        "fqdn": "myserver.tailnet.ts.net",
                    }
                },
            },
            "watchdog": {
                "check_interval": 30,
                "backoff_base": 10,
                "backoff_max": 600,
            },
        }
        config_path.write_text(yaml.dump(data))

        config = load_config(config_path)

        assert "myserver" in config.mounts
        mount = config.mounts["myserver"]
        assert mount.host == "myserver"
        assert mount.remote_path == "/data"
        assert mount.mount_point == "/mnt/myserver"
        assert mount.auto_mount is False
        assert mount.watchdog is True

        assert config.rclone.cache_mode == "full"
        assert config.rclone.buffer_size == "128M"
        assert config.rclone.extra_args == ["--vfs-cache-max-size", "10G"]

        assert config.tailscale.enabled is True
        assert "myserver" in config.tailscale.hosts
        host = config.tailscale.hosts["myserver"]
        assert host.tailscale_ip == "100.64.0.1"
        assert host.lan_ip == "192.168.1.10"
        assert host.fqdn == "myserver.tailnet.ts.net"

        assert config.watchdog.check_interval == 30
        assert config.watchdog.backoff_base == 10
        assert config.watchdog.backoff_max == 600

    def test_tilde_expansion_in_mount_point(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        data = {
            "mounts": {
                "server": {
                    "host": "server",
                    "mount_point": "~/mounts/server",
                }
            }
        }
        config_path.write_text(yaml.dump(data))

        config = load_config(config_path)
        mount = config.mounts["server"]
        assert mount.mount_point == "~/mounts/server"
        assert mount.resolved_mount_point == str(
            Path.home() / "mounts" / "server"
        )
```

**Step 2: Run tests to verify the new ones fail**

```bash
uv run pytest tests/test_config.py -v
```

Expected: 3 old tests PASS, 3 new tests FAIL (`ImportError: cannot import name 'load_config'`).

**Step 3: Implement load_config and private parsers in `src/remote_mount/config.py`**

Add `import yaml` at the top of the file (after the existing imports).

Then add after the `Config` dataclass:

```python
def _parse_rclone(data: dict[str, Any]) -> RcloneConfig:
    return RcloneConfig(
        cache_mode=data.get("cache_mode", "writes"),
        buffer_size=data.get("buffer_size", "64M"),
        extra_args=data.get("extra_args", []),
    )


def _parse_tailscale(data: dict[str, Any]) -> TailscaleConfig:
    hosts = {}
    for name, hdata in data.get("hosts", {}).items():
        hosts[name] = TailscaleHostConfig(
            tailscale_ip=hdata.get("tailscale_ip", ""),
            lan_ip=hdata.get("lan_ip", ""),
            fqdn=hdata.get("fqdn", ""),
        )
    return TailscaleConfig(
        enabled=data.get("enabled", False),
        hosts=hosts,
    )


def _parse_watchdog(data: dict[str, Any]) -> WatchdogConfig:
    return WatchdogConfig(
        check_interval=data.get("check_interval", 10),
        backoff_base=data.get("backoff_base", 5),
        backoff_max=data.get("backoff_max", 300),
    )


def _parse_mounts(data: dict[str, Any]) -> dict[str, MountConfig]:
    mounts = {}
    for name, mdata in data.items():
        mounts[name] = MountConfig(
            host=mdata.get("host", name),
            remote_path=mdata.get("remote_path", "/"),
            mount_point=mdata.get("mount_point", ""),
            auto_mount=mdata.get("auto_mount", True),
            watchdog=mdata.get("watchdog", False),
        )
    return mounts


def load_config(config_path: Path) -> Config:
    """Load config from YAML file; return defaults if file missing."""
    if not config_path.exists():
        return Config()

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    mounts = _parse_mounts(data.get("mounts", {}))
    rclone = _parse_rclone(data.get("rclone", {}))
    tailscale = _parse_tailscale(data.get("tailscale", {}))
    watchdog = _parse_watchdog(data.get("watchdog", {}))

    return Config(
        mounts=mounts,
        rclone=rclone,
        tailscale=tailscale,
        watchdog=watchdog,
    )
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_config.py -v
```

Expected: 6 tests PASS.

**Step 5: Commit**

```bash
git add src/remote_mount/config.py tests/test_config.py
git commit -m "feat(config): add load_config with YAML parsing and defaults"
```

---

### Task 4: save_config with Tests

**Files:**
- Modify: `src/remote_mount/config.py`
- Modify: `tests/test_config.py`

**Step 1: Write failing tests for save_config in `tests/test_config.py`**

Add `save_config` to the import block at the top of the test file:

```python
from remote_mount.config import (
    Config,
    MountConfig,
    RcloneConfig,
    TailscaleConfig,
    TailscaleHostConfig,
    WatchdogConfig,
    get_config_path,
    get_log_path,
    load_config,
    save_config,
)
```

Then add this test class at the bottom of the file:

```python
class TestSaveConfig:
    def test_round_trip(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        original = Config(
            mounts={
                "server": MountConfig(
                    host="server",
                    remote_path="/data",
                    mount_point="~/mounts/server",
                    auto_mount=False,
                    watchdog=True,
                )
            },
            rclone=RcloneConfig(
                cache_mode="full",
                buffer_size="128M",
                extra_args=["--arg"],
            ),
            tailscale=TailscaleConfig(
                enabled=True,
                hosts={
                    "server": TailscaleHostConfig(
                        tailscale_ip="100.64.0.1",
                        lan_ip="192.168.1.1",
                        fqdn="server.ts.net",
                    )
                },
            ),
            watchdog=WatchdogConfig(
                check_interval=20,
                backoff_base=8,
                backoff_max=400,
            ),
        )

        save_config(original, config_path)
        loaded = load_config(config_path)

        assert "server" in loaded.mounts
        m = loaded.mounts["server"]
        assert m.host == "server"
        assert m.remote_path == "/data"
        assert m.mount_point == "~/mounts/server"
        assert m.auto_mount is False
        assert m.watchdog is True

        assert loaded.rclone.cache_mode == "full"
        assert loaded.rclone.buffer_size == "128M"
        assert loaded.rclone.extra_args == ["--arg"]

        assert loaded.tailscale.enabled is True
        assert "server" in loaded.tailscale.hosts
        h = loaded.tailscale.hosts["server"]
        assert h.tailscale_ip == "100.64.0.1"
        assert h.lan_ip == "192.168.1.1"
        assert h.fqdn == "server.ts.net"

        assert loaded.watchdog.check_interval == 20
        assert loaded.watchdog.backoff_base == 8
        assert loaded.watchdog.backoff_max == 400

    def test_creates_parent_directories(self, tmp_path):
        config_path = tmp_path / "nested" / "deep" / "config.yaml"
        config = Config()

        save_config(config, config_path)

        assert config_path.exists()
```

**Step 2: Run tests to verify the new ones fail**

```bash
uv run pytest tests/test_config.py -v
```

Expected: 6 old tests PASS, 2 new tests FAIL (`ImportError: cannot import name 'save_config'`).

**Step 3: Implement save_config and serialization helpers in `src/remote_mount/config.py`**

Add after the `load_config` function:

```python
def _mount_to_dict(mount: MountConfig) -> dict[str, Any]:
    return {
        "host": mount.host,
        "remote_path": mount.remote_path,
        "mount_point": mount.mount_point,
        "auto_mount": mount.auto_mount,
        "watchdog": mount.watchdog,
    }


def _tailscale_host_to_dict(host: TailscaleHostConfig) -> dict[str, Any]:
    return {
        "tailscale_ip": host.tailscale_ip,
        "lan_ip": host.lan_ip,
        "fqdn": host.fqdn,
    }


def save_config(config: Config, config_path: Path) -> None:
    """Serialize config to YAML, creating parent directories as needed."""
    config_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {
        "mounts": {name: _mount_to_dict(m) for name, m in config.mounts.items()},
        "rclone": {
            "cache_mode": config.rclone.cache_mode,
            "buffer_size": config.rclone.buffer_size,
            "extra_args": config.rclone.extra_args,
        },
        "tailscale": {
            "enabled": config.tailscale.enabled,
            "hosts": {
                name: _tailscale_host_to_dict(h)
                for name, h in config.tailscale.hosts.items()
            },
        },
        "watchdog": {
            "check_interval": config.watchdog.check_interval,
            "backoff_base": config.watchdog.backoff_base,
            "backoff_max": config.watchdog.backoff_max,
        },
    }

    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
```

**Step 4: Run all tests to verify everything passes**

```bash
uv run pytest tests/test_config.py -v
```

Expected: All 8 tests PASS:
- `TestConfigPath::test_default_path` PASSED
- `TestConfigPath::test_xdg_override` PASSED
- `TestLogPath::test_default_log_path` PASSED
- `TestLoadConfig::test_missing_file_returns_defaults` PASSED
- `TestLoadConfig::test_existing_config_parsed` PASSED
- `TestLoadConfig::test_tilde_expansion_in_mount_point` PASSED
- `TestSaveConfig::test_round_trip` PASSED
- `TestSaveConfig::test_creates_parent_directories` PASSED

**Step 5: Run the full test suite to verify no regressions**

```bash
uv run pytest tests/ -v
```

Expected: All project tests PASS (including test_cli.py and test_platform.py from earlier tasks).

**Step 6: Commit**

```bash
git add src/remote_mount/config.py tests/test_config.py
git commit -m "feat(config): add save_config with YAML serialization and directory creation"
```

---

## Final File Reference

### `src/remote_mount/config.py` — complete file after all tasks

```python
"""Configuration management for remote-mount."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def get_config_path() -> Path:
    """Return path to config file, respecting XDG_CONFIG_HOME."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".config"
    return base / "remote-mount" / "config.yaml"


def get_log_path() -> Path:
    """Return path to log file."""
    return Path.home() / ".local" / "log" / "remote-mount.log"


@dataclass
class MountConfig:
    host: str
    remote_path: str = "/"
    mount_point: str = ""
    auto_mount: bool = True
    watchdog: bool = False

    @property
    def resolved_mount_point(self) -> str:
        """Return mount_point with ~ expanded."""
        return (
            str(Path(self.mount_point).expanduser())
            if self.mount_point
            else self.mount_point
        )


@dataclass
class RcloneConfig:
    cache_mode: str = "writes"
    buffer_size: str = "64M"
    extra_args: list[str] = field(default_factory=list)


@dataclass
class TailscaleHostConfig:
    tailscale_ip: str = ""
    lan_ip: str = ""
    fqdn: str = ""


@dataclass
class TailscaleConfig:
    enabled: bool = False
    hosts: dict[str, TailscaleHostConfig] = field(default_factory=dict)


@dataclass
class WatchdogConfig:
    check_interval: int = 10
    backoff_base: int = 5
    backoff_max: int = 300


@dataclass
class Config:
    mounts: dict[str, MountConfig] = field(default_factory=dict)
    rclone: RcloneConfig = field(default_factory=RcloneConfig)
    tailscale: TailscaleConfig = field(default_factory=TailscaleConfig)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)


def _parse_rclone(data: dict[str, Any]) -> RcloneConfig:
    return RcloneConfig(
        cache_mode=data.get("cache_mode", "writes"),
        buffer_size=data.get("buffer_size", "64M"),
        extra_args=data.get("extra_args", []),
    )


def _parse_tailscale(data: dict[str, Any]) -> TailscaleConfig:
    hosts = {}
    for name, hdata in data.get("hosts", {}).items():
        hosts[name] = TailscaleHostConfig(
            tailscale_ip=hdata.get("tailscale_ip", ""),
            lan_ip=hdata.get("lan_ip", ""),
            fqdn=hdata.get("fqdn", ""),
        )
    return TailscaleConfig(
        enabled=data.get("enabled", False),
        hosts=hosts,
    )


def _parse_watchdog(data: dict[str, Any]) -> WatchdogConfig:
    return WatchdogConfig(
        check_interval=data.get("check_interval", 10),
        backoff_base=data.get("backoff_base", 5),
        backoff_max=data.get("backoff_max", 300),
    )


def _parse_mounts(data: dict[str, Any]) -> dict[str, MountConfig]:
    mounts = {}
    for name, mdata in data.items():
        mounts[name] = MountConfig(
            host=mdata.get("host", name),
            remote_path=mdata.get("remote_path", "/"),
            mount_point=mdata.get("mount_point", ""),
            auto_mount=mdata.get("auto_mount", True),
            watchdog=mdata.get("watchdog", False),
        )
    return mounts


def load_config(config_path: Path) -> Config:
    """Load config from YAML file; return defaults if file missing."""
    if not config_path.exists():
        return Config()

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    mounts = _parse_mounts(data.get("mounts", {}))
    rclone = _parse_rclone(data.get("rclone", {}))
    tailscale = _parse_tailscale(data.get("tailscale", {}))
    watchdog = _parse_watchdog(data.get("watchdog", {}))

    return Config(
        mounts=mounts,
        rclone=rclone,
        tailscale=tailscale,
        watchdog=watchdog,
    )


def _mount_to_dict(mount: MountConfig) -> dict[str, Any]:
    return {
        "host": mount.host,
        "remote_path": mount.remote_path,
        "mount_point": mount.mount_point,
        "auto_mount": mount.auto_mount,
        "watchdog": mount.watchdog,
    }


def _tailscale_host_to_dict(host: TailscaleHostConfig) -> dict[str, Any]:
    return {
        "tailscale_ip": host.tailscale_ip,
        "lan_ip": host.lan_ip,
        "fqdn": host.fqdn,
    }


def save_config(config: Config, config_path: Path) -> None:
    """Serialize config to YAML, creating parent directories as needed."""
    config_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {
        "mounts": {name: _mount_to_dict(m) for name, m in config.mounts.items()},
        "rclone": {
            "cache_mode": config.rclone.cache_mode,
            "buffer_size": config.rclone.buffer_size,
            "extra_args": config.rclone.extra_args,
        },
        "tailscale": {
            "enabled": config.tailscale.enabled,
            "hosts": {
                name: _tailscale_host_to_dict(h)
                for name, h in config.tailscale.hosts.items()
            },
        },
        "watchdog": {
            "check_interval": config.watchdog.check_interval,
            "backoff_base": config.watchdog.backoff_base,
            "backoff_max": config.watchdog.backoff_max,
        },
    }

    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
```

### `tests/test_config.py` — complete file after all tasks

```python
"""Tests for remote_mount.config module."""

from pathlib import Path

import yaml

from remote_mount.config import (
    Config,
    MountConfig,
    RcloneConfig,
    TailscaleConfig,
    TailscaleHostConfig,
    WatchdogConfig,
    get_config_path,
    get_log_path,
    load_config,
    save_config,
)


class TestConfigPath:
    def test_default_path(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        path = get_config_path()
        assert path == Path.home() / ".config" / "remote-mount" / "config.yaml"

    def test_xdg_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        path = get_config_path()
        assert path == tmp_path / "remote-mount" / "config.yaml"


class TestLogPath:
    def test_default_log_path(self):
        path = get_log_path()
        assert path == Path.home() / ".local" / "log" / "remote-mount.log"


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        config_path = tmp_path / "nonexistent.yaml"
        config = load_config(config_path)
        assert isinstance(config, Config)
        assert config.mounts == {}
        assert isinstance(config.rclone, RcloneConfig)
        assert config.rclone.cache_mode == "writes"
        assert config.rclone.buffer_size == "64M"
        assert config.rclone.extra_args == []
        assert isinstance(config.tailscale, TailscaleConfig)
        assert config.tailscale.enabled is False
        assert config.tailscale.hosts == {}
        assert isinstance(config.watchdog, WatchdogConfig)
        assert config.watchdog.check_interval == 10
        assert config.watchdog.backoff_base == 5
        assert config.watchdog.backoff_max == 300

    def test_existing_config_parsed(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        data = {
            "mounts": {
                "myserver": {
                    "host": "myserver",
                    "remote_path": "/data",
                    "mount_point": "/mnt/myserver",
                    "auto_mount": False,
                    "watchdog": True,
                }
            },
            "rclone": {
                "cache_mode": "full",
                "buffer_size": "128M",
                "extra_args": ["--vfs-cache-max-size", "10G"],
            },
            "tailscale": {
                "enabled": True,
                "hosts": {
                    "myserver": {
                        "tailscale_ip": "100.64.0.1",
                        "lan_ip": "192.168.1.10",
                        "fqdn": "myserver.tailnet.ts.net",
                    }
                },
            },
            "watchdog": {
                "check_interval": 30,
                "backoff_base": 10,
                "backoff_max": 600,
            },
        }
        config_path.write_text(yaml.dump(data))

        config = load_config(config_path)

        assert "myserver" in config.mounts
        mount = config.mounts["myserver"]
        assert mount.host == "myserver"
        assert mount.remote_path == "/data"
        assert mount.mount_point == "/mnt/myserver"
        assert mount.auto_mount is False
        assert mount.watchdog is True

        assert config.rclone.cache_mode == "full"
        assert config.rclone.buffer_size == "128M"
        assert config.rclone.extra_args == ["--vfs-cache-max-size", "10G"]

        assert config.tailscale.enabled is True
        assert "myserver" in config.tailscale.hosts
        host = config.tailscale.hosts["myserver"]
        assert host.tailscale_ip == "100.64.0.1"
        assert host.lan_ip == "192.168.1.10"
        assert host.fqdn == "myserver.tailnet.ts.net"

        assert config.watchdog.check_interval == 30
        assert config.watchdog.backoff_base == 10
        assert config.watchdog.backoff_max == 600

    def test_tilde_expansion_in_mount_point(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        data = {
            "mounts": {
                "server": {
                    "host": "server",
                    "mount_point": "~/mounts/server",
                }
            }
        }
        config_path.write_text(yaml.dump(data))

        config = load_config(config_path)
        mount = config.mounts["server"]
        assert mount.mount_point == "~/mounts/server"
        assert mount.resolved_mount_point == str(
            Path.home() / "mounts" / "server"
        )


class TestSaveConfig:
    def test_round_trip(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        original = Config(
            mounts={
                "server": MountConfig(
                    host="server",
                    remote_path="/data",
                    mount_point="~/mounts/server",
                    auto_mount=False,
                    watchdog=True,
                )
            },
            rclone=RcloneConfig(
                cache_mode="full",
                buffer_size="128M",
                extra_args=["--arg"],
            ),
            tailscale=TailscaleConfig(
                enabled=True,
                hosts={
                    "server": TailscaleHostConfig(
                        tailscale_ip="100.64.0.1",
                        lan_ip="192.168.1.1",
                        fqdn="server.ts.net",
                    )
                },
            ),
            watchdog=WatchdogConfig(
                check_interval=20,
                backoff_base=8,
                backoff_max=400,
            ),
        )

        save_config(original, config_path)
        loaded = load_config(config_path)

        assert "server" in loaded.mounts
        m = loaded.mounts["server"]
        assert m.host == "server"
        assert m.remote_path == "/data"
        assert m.mount_point == "~/mounts/server"
        assert m.auto_mount is False
        assert m.watchdog is True

        assert loaded.rclone.cache_mode == "full"
        assert loaded.rclone.buffer_size == "128M"
        assert loaded.rclone.extra_args == ["--arg"]

        assert loaded.tailscale.enabled is True
        assert "server" in loaded.tailscale.hosts
        h = loaded.tailscale.hosts["server"]
        assert h.tailscale_ip == "100.64.0.1"
        assert h.lan_ip == "192.168.1.1"
        assert h.fqdn == "server.ts.net"

        assert loaded.watchdog.check_interval == 20
        assert loaded.watchdog.backoff_base == 8
        assert loaded.watchdog.backoff_max == 400

    def test_creates_parent_directories(self, tmp_path):
        config_path = tmp_path / "nested" / "deep" / "config.yaml"
        config = Config()

        save_config(config, config_path)

        assert config_path.exists()
```
