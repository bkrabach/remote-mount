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
    engine: str = "sshfs"


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
        engine=data.get("engine", "sshfs"),
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
        "engine": config.engine,
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
