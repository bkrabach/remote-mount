# remote-mount Design

## Goal

Create `remote-mount`, a Python CLI tool that manages persistent remote filesystem mounts using rclone's SFTP backend — replacing the unmaintained SSHFS with a cross-platform solution that handles prerequisite setup, mount configuration, health monitoring with auto-reconnect, and optional Tailscale VPN failover, all as a single installable package.

## Background

SSHFS was officially declared unmaintained in 2024. The existing shell-script approach to mounting remote filesystems is fragile: mounts drop silently, reconnection is manual, and there's no unified way to manage multiple mounts across macOS, Linux, and WSL2.

`remote-mount` replaces this with a proper CLI tool installable via `uv tool install git+https://github.com/bkrabach/remote-mount`. It uses rclone's SFTP backend, which is actively maintained, offers 4–10x better performance than SSHFS, has built-in retry logic for network interruptions, and works cross-platform (macOS via FUSE-T, Linux via native FUSE, WSL2 via Linux FUSE, and Windows via WinFsp in the future).

No existing tool combines mount configuration, health monitoring, auto-reconnect, and service management into a single package. `remote-mount` fills that gap.

## Approach

**Thin orchestrator.** `remote-mount` does not reimplement anything. It orchestrates existing, proven tools:

- **rclone** — handles the actual SFTP mount as a subprocess
- **Platform-native services** — launchd (macOS) and systemd (Linux/WSL2) handle process supervision
- **SSH** — authentication and config are delegated to the user's existing SSH setup

Dependencies are minimal: `click` (CLI framework), `pyyaml` (config handling), `paramiko` (SSH config parsing only — not the full SSH client). Everything else (rclone, FUSE layer, SSH keys) is a system-level dependency that the `doctor` command handles.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   CLI (cli.py)                   │
│  doctor | add | remove | mount | unmount | ...   │
└──────┬──────┬──────┬──────┬──────┬──────────────┘
       │      │      │      │      │
       ▼      ▼      ▼      ▼      ▼
  doctor.py  config.py  mounts.py  service.py  ssh_config.py
       │      │      │      │      │
       └──────┴──────┴──────┴──────┘
                     │
              platform.py
         (OS detection & abstraction)
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
   LaunchdManager  SystemdManager  (future: TaskSchedulerManager)
```

All modules call through `platform.py` for anything OS-specific. The CLI layer is a thin click wrapper that delegates to the appropriate module.

## Components

### Project Structure & Installation

```
remote-mount/
  pyproject.toml          # package metadata, [project.scripts] entry point
  src/remote_mount/
    __init__.py
    cli.py                # click CLI entry point
    config.py             # config loading/saving (YAML)
    doctor.py             # prerequisite detection & install
    mounts.py             # mount/unmount operations (calls rclone)
    service.py            # watchdog service management (launchd/systemd)
    ssh_config.py         # SSH config parsing/writing (Tailscale failover)
    platform.py           # platform detection & abstraction layer
```

Runtime dependencies:

| Package   | Purpose                                          |
|-----------|--------------------------------------------------|
| click     | CLI framework                                    |
| pyyaml    | Config file handling                             |
| paramiko  | SSH config parsing (SSHConfig class only)        |

No other runtime deps. System-level tools (rclone, FUSE, SSH) are checked and installed by the `doctor` command.

### Configuration

Config lives at `~/.config/remote-mount/config.yaml`. The `add` wizard creates and updates it, or the user can hand-edit.

```yaml
mounts:
  spark-1:
    host: spark-1              # SSH host (as in ~/.ssh/config or raw hostname)
    remote_path: /
    mount_point: ~/mnt/spark-1
    auto_mount: true           # mount on `remote-mount mount --all`
    watchdog: true             # include in watchdog service

  spark-2:
    host: spark-2
    remote_path: /home/bkrabach
    mount_point: ~/mnt/spark-2
    auto_mount: true
    watchdog: false

rclone:
  cache_mode: writes           # off | minimal | writes | full
  buffer_size: 64M
  extra_args: []               # pass-through for power users

tailscale:
  enabled: false               # opt-in globally
  hosts:                       # per-host Tailscale config (only used if enabled)
    spark-1:
      tailscale_ip: 100.124.126.19
      lan_ip: 192.168.1.5
      fqdn: spark-1.tail8f3c4e.ts.net
    spark-2:
      tailscale_ip: 100.93.134.115
      lan_ip: 192.168.1.6
      fqdn: spark-2.tail8f3c4e.ts.net

watchdog:
  check_interval: 10           # seconds between health checks
  backoff_base: 5              # initial retry wait
  backoff_max: 300             # cap at 5 minutes
```

Key decisions:

- Mount entries are **named** so you can do `remote-mount mount spark-1` or `remote-mount mount --all`.
- `watchdog: true/false` is **per-mount** — not every mount needs auto-reconnect.
- Tailscale is a **top-level section** since it affects SSH config, not just individual mounts.
- The `extra_args` field is an **escape hatch** for rclone power users.
- No hardcoded specifics — everything is user-configured.

### CLI Commands

```
remote-mount doctor              # check & install prerequisites
remote-mount add                 # interactive wizard to add a mount
remote-mount remove <name>       # remove a mount from config
remote-mount list                # show configured mounts and their status
remote-mount mount [name|--all]  # mount one or all configured mounts
remote-mount unmount [name|--all]  # unmount one or all
remote-mount status              # show mount health + watchdog service state
remote-mount service install     # generate & install watchdog service
remote-mount service start       # start the watchdog
remote-mount service stop        # stop the watchdog
remote-mount service uninstall   # remove the watchdog service
remote-mount config              # open config file in $EDITOR
remote-mount config path         # print config file path
```

Key behaviors:

- **doctor** — detects platform, checks for rclone, FUSE layer, SSH keys. For each missing item, offers to install or prints the manual command if declined.
- **add** — wizard prompts for: host, remote path, mount point (with smart defaults like `~/mnt/<host>`), whether to enable watchdog, whether to set up Tailscale failover. If Tailscale is chosen, prompts for IPs/FQDN and offers to update `~/.ssh/config`.
- **mount** — calls `rclone mount` with SFTP backend as a daemon process. Uses SSH config for auth.
- **service install** — generates platform-native service file from a template, installs it, but doesn't start it.
- **status** — one-glance view: which mounts are up, which are down, is the watchdog running.

### Doctor Command

`remote-mount doctor` checks prerequisites and offers to fix what's missing. It runs a checklist per platform:

**Common (all platforms):**

- rclone installed and on PATH
- SSH key exists (`~/.ssh/id_*`)
- SSH agent running with key loaded

**macOS-specific:**

- FUSE layer: checks for FUSE-T first (preferred, no kernel extension), falls back to macFUSE
- Install via: `brew install --cask fuse-t` or `brew install --cask macfuse`

**Linux/WSL2-specific:**

- FUSE layer: `libfuse3` / `fuse3` package
- Install via: `apt install fuse3 libfuse3-dev` (Ubuntu/Debian)

**Optional checks (only if configured):**

- Tailscale installed and running (`tailscale status`)
- Tailscale hosts reachable

Output format:

```
[PASS] rclone .................. v1.68.2
[PASS] SSH key ................. ~/.ssh/id_ed25519
[FAIL] FUSE layer .............. not found
       Install automatically? [Y/n/manual]
         Y = runs `brew install --cask fuse-t`
         n = skip
         manual = prints the command for you to run
[PASS] Tailscale ............... connected (3 hosts)
```

Doctor is idempotent — safe to run repeatedly. It never changes anything without prompting first.

### Watchdog & Service Management

**Watchdog loop** (runs as a hidden Python entry point `remote-mount _watchdog`):

1. Load config, filter to `watchdog: true` mounts
2. For each mount, check health: `stat <mount_point>` with a short timeout
3. If healthy — reset backoff, sleep `check_interval`
4. If unhealthy — clean up stale mount, check if host is reachable (`ssh -o BatchMode=yes -o ConnectTimeout=5 <host> true`), attempt remount via rclone
5. If host unreachable — exponential backoff (configurable base/max from config)
6. Loop forever

**Service management** (`remote-mount service`):

| Subcommand  | macOS                                                                 | Linux/WSL2                                                                  |
|-------------|-----------------------------------------------------------------------|-----------------------------------------------------------------------------|
| `install`   | LaunchAgent plist at `~/Library/LaunchAgents/com.remote-mount.watchdog.plist` (`KeepAlive: true`) | systemd user unit at `~/.config/systemd/user/remote-mount-watchdog.service` (`Restart=always`) |
| `start`     | `launchctl bootstrap`                                                 | `systemctl --user start`                                                    |
| `stop`      | `launchctl bootout`                                                   | `systemctl --user stop`                                                     |
| `uninstall` | Stops service, removes plist                                          | Stops service, removes unit file                                            |
| `status`    | Shows running state + last few log lines                              | Shows running state + last few log lines                                    |

**Logging:** Watchdog writes to `~/.local/log/remote-mount.log`, auto-trimmed at 1000 lines.

The `_watchdog` command is a hidden subcommand (prefixed with underscore) — it's the entry point the service file calls, not something users run directly.

### SSH Config & Tailscale Failover

When Tailscale is enabled and a user adds a mount, the tool optionally manages `~/.ssh/config` entries with a failover ProxyCommand pattern.

The ProxyCommand tries addresses in order:

1. **Tailscale IP** — fastest, no DNS lookup needed
2. **LAN IP** — local network fallback
3. **FQDN** — last resort, requires DNS

Before writing to `~/.ssh/config`, the tool checks if a Host block already exists:

| Scenario                                  | Behavior                                                       |
|-------------------------------------------|----------------------------------------------------------------|
| No existing block                         | Appends a new one with `# managed by remote-mount` comment     |
| Existing block with `# managed by remote-mount` | Updates it in place                                     |
| Existing block without our comment        | Warns user and prints what it *would* write for manual merging |

The `# managed by remote-mount` marker is the safety boundary — the tool only touches blocks it owns.

**Generated template:**

```
# managed by remote-mount
Host spark-1
    User bkrabach
    IdentityFile ~/.ssh/id_ed25519
    ProxyCommand bash -c 'for addr in 100.124.126.19 192.168.1.5 spark-1.tail8f3c4e.ts.net; do nc -z -G 3 "$addr" 22 2>/dev/null && exec nc "$addr" 22; done; echo "spark-1: all addresses unreachable" >&2; exit 1'
```

### Platform Abstraction & Windows Path

`platform.py` is the seam for cross-platform support. It exposes a simple interface that the rest of the codebase calls:

```python
detect_platform() -> "macos" | "linux" | "wsl2" | "windows"

get_fuse_package()      # e.g., "fuse-t" on macOS, "fuse3" on Linux
get_install_command()   # e.g., "brew install --cask fuse-t"
get_service_manager()   # returns a ServiceManager (launchd or systemd)
```

**ServiceManager abstraction** — a class with `install()`, `start()`, `stop()`, `uninstall()`, `status()` methods:

| Implementation        | Platform    | Mechanism                          |
|-----------------------|-------------|------------------------------------|
| `LaunchdManager`      | macOS       | Templates a plist, uses `launchctl bootstrap/bootout` |
| `SystemdManager`      | Linux/WSL2  | Templates a unit file, uses `systemctl --user`        |
| `TaskSchedulerManager`| Windows     | Future — same interface, no other code changes needed  |

**WSL2 detection:** Checks `/proc/version` for "Microsoft" or "WSL". Reports `wsl2` but uses the Linux/systemd codepath since WSL2 with systemd support behaves like standard Linux.

## Data Flow

### Mount Operation

```
User: remote-mount mount spark-1
  │
  ▼
cli.py → config.py (load mount "spark-1")
  │
  ▼
mounts.py → builds rclone command:
  rclone mount :sftp:/ ~/mnt/spark-1 \
    --sftp-host spark-1 \
    --vfs-cache-mode writes \
    --daemon
  │
  ▼
rclone connects via SSH (using ~/.ssh/config for auth)
  │
  ▼
FUSE mount appears at ~/mnt/spark-1
```

### Watchdog Recovery

```
_watchdog loop (every check_interval seconds):
  │
  ▼
stat ~/mnt/spark-1  →  timeout/error?
  │                         │
  OK → sleep               YES
                             │
                             ▼
                        fusermount -uz ~/mnt/spark-1  (cleanup)
                             │
                             ▼
                        ssh -o BatchMode=yes spark-1 true
                             │               │
                          reachable       unreachable
                             │               │
                             ▼               ▼
                        rclone mount    exponential backoff
                        (remount)       (retry later)
```

## Error Handling

- **Mount fails** — rclone's stderr is captured and displayed to the user. Common causes (FUSE not installed, SSH auth failure) get specific guidance messages.
- **Host unreachable during watchdog** — exponential backoff from `backoff_base` (5s) to `backoff_max` (300s). Resets on successful reconnection.
- **Stale FUSE mount** — watchdog runs `fusermount -uz` (lazy unmount) to clean up before attempting remount.
- **SSH config conflicts** — tool refuses to modify Host blocks it doesn't own (no `# managed by remote-mount` marker). Prints what it would write and lets the user merge manually.
- **Doctor failures** — each check is independent. A failure in one doesn't stop the others. The user sees the full picture and can fix items in any order.
- **Config file missing** — `add` creates it from scratch. Other commands print a helpful message pointing to `remote-mount add`.

## Testing Strategy

- **Unit tests** for `config.py` (YAML round-trip), `ssh_config.py` (Host block parsing/generation), `platform.py` (detection logic with mocked `/proc/version`).
- **Integration tests** for `doctor.py` (mocked `shutil.which` and subprocess calls), `service.py` (template generation verified against known-good plist/unit files).
- **CLI tests** using click's `CliRunner` for command parsing and output formatting.
- **Manual testing** on macOS, Ubuntu, and WSL2 for end-to-end mount/unmount/watchdog flows (these require actual FUSE and rclone).

## Open Questions

1. **rclone config management** — Should `remote-mount` generate `~/.config/rclone/rclone.conf` entries, or use rclone's SFTP backend directly via CLI flags? **Recommendation:** CLI flags, to avoid managing two config files.
2. **Non-SSH remote mounts** — Should the tool support S3, GCS, and other rclone backends in the future? The architecture allows it, but YAGNI — SSH/SFTP only for now, with room to grow.
