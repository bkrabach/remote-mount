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
