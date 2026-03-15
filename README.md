# remote-mount

Persistent remote filesystem mounts using rclone SFTP, with automatic reconnection and a background watchdog service.

## Features

- Mount remote filesystems over SFTP using [rclone](https://rclone.org/)
- Auto-mount on startup via system service (launchd/systemd)
- Background watchdog with exponential backoff reconnection
- Tailscale SSH failover support
- Cross-platform: macOS, Linux, WSL2

## Requirements

- [rclone](https://rclone.org/install/) (v1.60+)
- FUSE driver: **FUSE-T** (macOS), **fuse3** (Linux/WSL2), or **WinFsp** (Windows)
- SSH key access to remote host(s)
- [uv](https://docs.astral.sh/uv/) (for install)

## Installation

### Install as a standalone CLI tool (recommended)

```bash
uv tool install git+https://github.com/yourusername/remote-mount.git
```

### Development install

```bash
git clone https://github.com/yourusername/remote-mount.git
cd remote-mount
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Quick Start

### 1. Check prerequisites

```bash
remote-mount doctor
```

`doctor` checks that rclone, a FUSE driver, your SSH key, and SSH agent are all ready. It reports platform-specific details and offers to install anything missing.

### 2. Add a mount

```bash
remote-mount add
```

Interactive prompts configure the host, remote path, local mount point, auto-mount, and optional watchdog/Tailscale settings.

### 3. Mount

```bash
# Mount a specific host
remote-mount mount spark-1

# Mount all configured mounts
remote-mount mount --all
```

### 4. Check status

```bash
remote-mount status
```

Shows each mount's live state (mounted / not mounted) and the watchdog service status.

### 5. List configured mounts

```bash
remote-mount list
```

---

## Watchdog Service

The watchdog is a background service that continuously monitors your mounts and automatically remounts them if they become unavailable.

### How it works

1. Every `check_interval` seconds (default: 10 s) the watchdog tests each mount by listing its root directory.
2. If a mount is **healthy** the backoff counter resets to `backoff_base`.
3. If a mount is **unhealthy but the host is reachable** over SSH, it immediately attempts a remount.
4. If the host is **unreachable** (network down, Tailscale disconnected, etc.) the watchdog backs off exponentially:
   - Backoff doubles on each failed attempt: 5 s → 10 s → 20 s → … → `backoff_max` (default: 300 s)
   - Once capped at `backoff_max` it keeps retrying at that interval until the host returns

### Service commands

```bash
# Install the watchdog as a system service (launchd on macOS, systemd on Linux)
remote-mount service install

# Start the service
remote-mount service start

# Check service status
remote-mount service status   # (via remote-mount status)

# Stop the service
remote-mount service stop

# Remove the service
remote-mount service uninstall
```

> **Note:** The `remote-mount` executable must be on `PATH` before running `service install`.

---

## Commands

| Command | Description |
|---|---|
| `doctor` | Check prerequisites (rclone, FUSE, SSH key, SSH agent) |
| `add` | Interactively configure a new remote mount |
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

---

## Configuration

The config file lives at `~/.config/remote-mount/config.yaml` (or `$XDG_CONFIG_HOME/remote-mount/config.yaml`).

Print the path:
```bash
remote-mount config path
```

Edit directly:
```bash
remote-mount config edit
```

### Full config.yaml example

```yaml
# ~/.config/remote-mount/config.yaml

mounts:
  spark-1:
    host: spark-1           # SSH hostname (must be in ~/.ssh/config or resolvable)
    remote_path: /data      # Path on the remote host to mount
    mount_point: ~/mnt/spark-1  # Local mount point (~ is expanded)
    auto_mount: true        # Mount automatically when service starts
    watchdog: true          # Monitor and remount if this mount goes stale

  spark-2:
    host: spark-2
    remote_path: /home/user
    mount_point: ~/mnt/spark-2
    auto_mount: false
    watchdog: false

rclone:
  cache_mode: writes        # VFS cache mode: off, minimal, writes, full
  buffer_size: 64M          # Read buffer size
  extra_args: []            # Extra rclone flags appended to every mount command
  # extra_args:
  #   - --sftp-key-file=/home/user/.ssh/id_ed25519
  #   - --log-level=DEBUG

tailscale:
  enabled: false            # Set to true to configure Tailscale SSH failover
  hosts:
    spark-1:
      tailscale_ip: 100.x.y.z      # Tailscale mesh IP
      lan_ip: 192.168.1.100        # LAN IP (optional)
      fqdn: spark-1.tail12345.ts.net  # Tailscale FQDN (optional)

watchdog:
  check_interval: 10        # Seconds between health checks
  backoff_base: 5           # Initial backoff in seconds after first failure
  backoff_max: 300          # Maximum backoff in seconds (caps exponential growth)
```

### SSH configuration

When you run `remote-mount add` and opt into Tailscale failover, remote-mount automatically writes an SSH `Host` block to `~/.ssh/config` with `Match exec` directives that prefer Tailscale when available and fall back to the LAN IP or FQDN.

---

## Platform Support

| Platform | FUSE Driver | Service Manager | Status |
|---|---|---|---|
| **macOS** | [FUSE-T](https://www.fuse-t.org/) | launchd | ✅ Supported |
| **Linux** | fuse3 | systemd (user) | ✅ Supported |
| **WSL2** | fuse3 | systemd (user) | ✅ Supported |
| **Windows** | [WinFsp](https://winfsp.dev/) | — | 🔜 Planned |

### macOS

Install FUSE-T via Homebrew:
```bash
brew install --cask fuse-t
```

### Linux / WSL2

Install fuse3:
```bash
# Ubuntu/Debian
sudo apt install fuse3

# Fedora/RHEL
sudo dnf install fuse3
```

For WSL2, also ensure systemd is enabled in `/etc/wsl.conf`:
```ini
[boot]
systemd=true
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.
