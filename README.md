# remote-mount

Cross-platform CLI for managing persistent remote filesystem mounts with auto-reconnect.

## Features

- Mount remote filesystems over SSH using [SSHFS](https://github.com/libfuse/sshfs) (default) or [rclone](https://rclone.org/) (configurable)
- Interactive setup wizard with smart defaults
- System doctor that checks and installs prerequisites
- Background watchdog with exponential backoff reconnection
- Platform-native service management (launchd on macOS, systemd on Linux/WSL2)
- Optional Tailscale SSH failover (tries Tailscale IP > LAN IP > FQDN)
- Cross-platform: macOS, Linux, WSL2

## Requirements

- [SSHFS](https://github.com/libfuse/sshfs) (default engine) or [rclone](https://rclone.org/) (alternative)
- FUSE driver: [FUSE-T](https://www.fuse-t.org/) (macOS, recommended) or [macFUSE](https://osxfuse.github.io/) (macOS), fuse3 (Linux/WSL2)
- SSH key access to remote host(s)
- [uv](https://docs.astral.sh/uv/) (for install)

> `remote-mount doctor` will check for all of these and offer to install anything missing.

## Installation

```bash
uv tool install git+https://github.com/bkrabach/remote-mount
```

### Development install

```bash
git clone https://github.com/bkrabach/remote-mount.git
cd remote-mount
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Quick Start

```bash
# 1. Check and install prerequisites
remote-mount doctor

# 2. Add a mount (interactive wizard)
remote-mount add

# 3. Mount it
remote-mount mount spark-1    # or: remote-mount mount --all

# 4. Check status
remote-mount status
```

## Commands

| Command | Description |
|---|---|
| `doctor` | Check prerequisites and offer to install missing ones |
| `add` | Interactive wizard to configure a new mount |
| `remove <name>` | Remove a configured mount |
| `mount <name>` | Mount a specific remote filesystem |
| `mount --all` | Mount all configured remote filesystems |
| `unmount <name>` | Unmount a specific remote filesystem |
| `unmount --all` | Unmount all remote filesystems |
| `list` | Show all configured mounts with current status |
| `status` | Show mount health and watchdog service state |
| `config path` | Print the path to the config file |
| `config edit` | Open config file in `$EDITOR` |
| `service install` | Install the watchdog as a background service |
| `service start` | Start the watchdog background service |
| `service stop` | Stop the watchdog background service |
| `service uninstall` | Remove the watchdog background service |

## Configuration

Config lives at `~/.config/remote-mount/config.yaml` (or `$XDG_CONFIG_HOME/remote-mount/config.yaml`). Created automatically by `remote-mount add`, or hand-edit with `remote-mount config edit`.

```yaml
# Mount engine: "sshfs" (default, fast) or "rclone" (cross-platform fallback)
engine: sshfs

mounts:
  spark-1:
    host: spark-1              # SSH host (as in ~/.ssh/config or resolvable)
    remote_path: /             # Path on the remote host
    mount_point: ~/mnt/spark-1 # Local mount point (~ is expanded)
    auto_mount: true           # Include in `mount --all`
    watchdog: true             # Auto-reconnect via watchdog service

  spark-2:
    host: spark-2
    remote_path: /home/user
    mount_point: ~/mnt/spark-2
    auto_mount: true
    watchdog: false

# Only used when engine: rclone
rclone:
  cache_mode: writes           # off | minimal | writes | full
  buffer_size: 64M
  extra_args: []               # Extra rclone flags

# Optional Tailscale SSH failover
tailscale:
  enabled: false
  hosts:
    spark-1:
      tailscale_ip: 100.x.y.z
      lan_ip: 192.168.1.100
      fqdn: spark-1.tail12345.ts.net

watchdog:
  check_interval: 10           # Seconds between health checks
  backoff_base: 5              # Initial retry wait (seconds)
  backoff_max: 300             # Max retry wait (seconds, caps exponential growth)
```

## Watchdog Service

The watchdog monitors your mounts and automatically reconnects when they drop.

**How it works:**
1. Every `check_interval` seconds, tests each mount with `watchdog: true`
2. If healthy: resets backoff
3. If unhealthy but host reachable: immediately remounts
4. If host unreachable: exponential backoff (5s, 10s, 20s... up to `backoff_max`)

```bash
remote-mount service install   # Install as launchd/systemd service
remote-mount service start     # Start the watchdog
remote-mount service stop      # Stop it
remote-mount service uninstall # Remove it
```

> The `remote-mount` executable must be on PATH before running `service install`.

## Tailscale SSH Failover

When adding a mount, you can optionally configure Tailscale failover. This writes a `Host` block to `~/.ssh/config` with a `ProxyCommand` that tries addresses in order:

1. **Tailscale IP** (fastest, no DNS lookup)
2. **LAN IP** (local network)
3. **FQDN** (fallback, requires DNS)

The tool only modifies SSH config blocks marked with `# managed by remote-mount`. Existing entries you've written yourself are never touched.

## Mount Engines

| Engine | Default | When to use |
|--------|---------|-------------|
| `sshfs` | Yes | Fast, direct SSH mount. Works on macOS (with FUSE-T/macFUSE) and Linux. |
| `rclone` | No | Cross-platform fallback. Supports non-SSH backends (S3, GCS, etc.) in the future. Uses `nfsmount` on macOS, `mount` on Linux. |

Set `engine: rclone` in config to switch. The `doctor` command adapts its checks to whichever engine is configured.

## Platform Support

| Platform | FUSE Driver | Service Manager | Status |
|---|---|---|---|
| macOS | [FUSE-T](https://www.fuse-t.org/) (recommended) or macFUSE | launchd | Supported |
| Linux | fuse3 | systemd (user) | Supported |
| WSL2 | fuse3 | systemd (user) | Supported |
| Windows | [WinFsp](https://winfsp.dev/) | Task Scheduler | Planned |

## License

MIT License - see [LICENSE](LICENSE) for details.
