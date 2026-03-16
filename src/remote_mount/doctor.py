"""Doctor command — prerequisite detection for remote-mount."""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import click

from remote_mount.platform import Platform


@dataclass
class CheckResult:
    """Result of a single prerequisite check."""

    name: str
    passed: bool
    detail: str = ""
    install_cmd: str = ""


def check_mount_engine(engine: str, platform: Platform = "linux") -> CheckResult:
    """Check whether the configured mount engine binary is installed.

    If engine is 'sshfs': checks for the sshfs binary.
    If engine is 'rclone': checks for the rclone binary and returns its version.
    """
    if engine == "rclone":
        if shutil.which("rclone") is None:
            return CheckResult(
                name="rclone",
                passed=False,
                detail="rclone not found",
                install_cmd="brew install rclone",
            )
        result = subprocess.run(
            ["rclone", "version"],
            capture_output=True,
            text=True,
        )
        first_line = (
            result.stdout.splitlines()[0]
            if result.stdout
            else "rclone (unknown version)"
        )
        return CheckResult(name="rclone", passed=True, detail=first_line)

    # engine == "sshfs" (default)
    if shutil.which("sshfs") is None:
        install_cmd = (
            "brew install sshfs" if platform == "macos" else "apt install sshfs"
        )
        return CheckResult(
            name="sshfs",
            passed=False,
            detail="sshfs not found",
            install_cmd=install_cmd,
        )
    return CheckResult(name="sshfs", passed=True, detail="sshfs found")


def check_ssh_key() -> CheckResult:
    """Check whether at least one SSH key exists in ~/.ssh/."""
    ssh_dir = Path.home() / ".ssh"
    key_names = ["id_ed25519", "id_rsa", "id_ecdsa", "id_dsa"]
    for key_name in key_names:
        key_path = ssh_dir / key_name
        if key_path.exists():
            return CheckResult(name="ssh_key", passed=True, detail=key_name)
    return CheckResult(
        name="ssh_key",
        passed=False,
        detail="no SSH key found in ~/.ssh/",
        install_cmd="ssh-keygen -t ed25519",
    )


def check_ssh_agent() -> CheckResult:
    """Check whether the SSH agent has loaded keys."""
    result = subprocess.run(
        ["ssh-add", "-l"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        key_count = len(result.stdout.strip().splitlines())
        return CheckResult(
            name="ssh_agent",
            passed=True,
            detail=f"{key_count} key(s) loaded",
        )
    return CheckResult(
        name="ssh_agent",
        passed=False,
        detail="no keys loaded in SSH agent",
        install_cmd="ssh-add ~/.ssh/id_ed25519",
    )


def check_fuse(platform: Platform) -> CheckResult:
    """Check whether the FUSE layer is available for the given platform."""
    if platform == "macos":
        result = subprocess.run(
            ["brew", "list", "--cask", "fuse-t"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return CheckResult(name="fuse", passed=True, detail="fuse-t installed")
        return CheckResult(
            name="fuse",
            passed=False,
            detail="fuse-t not found",
            install_cmd="brew install --cask fuse-t",
        )
    # Linux / WSL2
    for cmd in ("fusermount3", "fusermount"):
        path = shutil.which(cmd)
        if path:
            return CheckResult(
                name="fuse", passed=True, detail=f"{cmd} found at {path}"
            )
    return CheckResult(
        name="fuse",
        passed=False,
        detail="fusermount / fusermount3 not found",
        install_cmd="sudo apt install fuse3 libfuse3-dev",
    )


def run_checks(platform: Platform, engine: str = "sshfs") -> list[CheckResult]:
    """Run all prerequisite checks and return the results."""
    return [
        check_mount_engine(engine, platform),
        check_ssh_key(),
        check_ssh_agent(),
        check_fuse(platform),
    ]


def print_results(results: list[CheckResult]) -> None:
    """Display check results with colored [PASS]/[FAIL] labels."""
    for r in results:
        label = (
            click.style("[PASS]", fg="green")
            if r.passed
            else click.style("[FAIL]", fg="red")
        )
        detail = f"  {r.detail}" if r.detail else ""
        click.echo(f"{label} {r.name}{detail}")


def prompt_install(result: CheckResult) -> str:
    """Offer the user a Y/n/manual choice to install a missing prerequisite.

    Returns: 'auto', 'manual', or 'skip'.
    """
    click.echo(f"\nInstall {result.name}?  Command: {result.install_cmd}")
    choice = click.prompt("  [Y]es / [n]o / [m]anual", default="Y").strip().lower()

    if choice in ("y", "yes", ""):
        return "auto"
    if choice in ("m", "manual"):
        return "manual"
    return "skip"
