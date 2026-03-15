from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

from remote_mount.cli import cli
from remote_mount.config import Config, MountConfig, save_config
from remote_mount.doctor import CheckResult


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "remote filesystem mounts" in result.output


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_doctor_command_runs():
    """Doctor command runs without error and displays platform and check results."""
    mocked_results = [
        CheckResult(name="rclone", passed=True, detail="rclone v1.65.0"),
        CheckResult(name="ssh_key", passed=True, detail="id_ed25519"),
        CheckResult(name="ssh_agent", passed=True, detail="1 key(s) loaded"),
        CheckResult(name="fuse", passed=True, detail="fuse-t installed"),
    ]
    runner = CliRunner()
    with patch("remote_mount.cli.detect_platform", return_value="macos"):
        with patch("remote_mount.cli.run_checks", return_value=mocked_results):
            result = runner.invoke(cli, ["doctor"])

    assert result.exit_code == 0
    assert "macos" in result.output
    assert "rclone" in result.output
    assert "All checks passed." in result.output


def test_add_basic_mount():
    """Add command creates correct config entries from user input."""
    runner = CliRunner()
    # Input sequence:
    # myhost      -> host
    # /data       -> remote_path
    # ~/mnt/myhost -> mount_point
    # y           -> auto_mount (confirm, default True)
    # n           -> watchdog (confirm, default False)
    # n           -> Tailscale? (no)
    user_input = "myhost\n/data\n~/mnt/myhost\ny\nn\nn\n"

    with runner.isolated_filesystem():
        config_path = Path("config.yaml")
        with patch("remote_mount.cli.get_config_path", return_value=config_path):
            result = runner.invoke(cli, ["add"], input=user_input)

        assert result.exit_code == 0, f"Exit code {result.exit_code}: {result.output}"

        # Verify the config was saved
        assert config_path.exists(), "Config file was not created"
        with open(config_path) as f:
            data = yaml.safe_load(f)

        assert "mounts" in data
        assert "myhost" in data["mounts"]
        mount = data["mounts"]["myhost"]
        assert mount["host"] == "myhost"
        assert mount["remote_path"] == "/data"
        assert mount["mount_point"] == "~/mnt/myhost"
        assert mount["auto_mount"] is True
        assert mount["watchdog"] is False


def test_remove_mount():
    """Remove command deletes mount entry after confirmation."""
    runner = CliRunner()

    with runner.isolated_filesystem():
        config_path = Path("config.yaml")

        # Create initial config with a mount
        config = Config(
            mounts={
                "myhost": MountConfig(
                    host="myhost",
                    remote_path="/data",
                    mount_point="~/mnt/myhost",
                    auto_mount=True,
                    watchdog=False,
                )
            }
        )
        save_config(config, config_path)

        with patch("remote_mount.cli.get_config_path", return_value=config_path):
            result = runner.invoke(cli, ["remove", "myhost"], input="y\n")

        assert result.exit_code == 0, f"Exit code {result.exit_code}: {result.output}"

        # Verify mount was removed
        with open(config_path) as f:
            data = yaml.safe_load(f)

        assert "myhost" not in data.get("mounts", {})


def test_service_install_raises_when_remote_mount_not_in_path(tmp_path):
    """service install fails with ClickException when 'remote-mount' is not in PATH."""
    from remote_mount.service import LaunchdManager

    runner = CliRunner()
    manager = LaunchdManager(plist_dir=tmp_path)

    with patch("remote_mount.cli._get_service_manager", return_value=manager):
        with patch("shutil.which", return_value=None):
            result = runner.invoke(cli, ["service", "install"])

    assert result.exit_code != 0
    assert "remote-mount" in result.output
    assert "PATH" in result.output


def test_list_command_shows_mounts():
    """List command shows all configured mounts with status indicators."""
    runner = CliRunner()

    with runner.isolated_filesystem():
        config_path = Path("config.yaml")
        config = Config(
            mounts={
                "spark-1": MountConfig(
                    host="spark-1",
                    remote_path="/data",
                    mount_point="~/mnt/spark-1",
                    auto_mount=True,
                    watchdog=True,
                ),
                "spark-2": MountConfig(
                    host="spark-2",
                    remote_path="/home",
                    mount_point="~/mnt/spark-2",
                    auto_mount=False,
                    watchdog=False,
                ),
            }
        )
        save_config(config, config_path)

        with patch("remote_mount.cli.get_config_path", return_value=config_path):
            with patch("remote_mount.cli.is_mounted", return_value=False):
                result = runner.invoke(cli, ["list"])

    assert result.exit_code == 0, f"Exit code {result.exit_code}: {result.output}"
    assert "spark-1" in result.output
    assert "spark-2" in result.output
    assert "auto" in result.output
    assert "watchdog" in result.output


def test_status_command():
    """Status command shows mount health and watchdog service state."""
    runner = CliRunner()

    with runner.isolated_filesystem():
        config_path = Path("config.yaml")
        config = Config(
            mounts={
                "test-mount": MountConfig(
                    host="testhost",
                    remote_path="/data",
                    mount_point="~/mnt/test",
                    auto_mount=True,
                    watchdog=False,
                ),
            }
        )
        save_config(config, config_path)

        mock_manager = MagicMock()
        mock_manager.status.return_value = "inactive"

        with patch("remote_mount.cli.get_config_path", return_value=config_path):
            with patch("remote_mount.cli.is_mounted", return_value=False):
                with patch("remote_mount.cli.detect_platform", return_value="linux"):
                    with patch(
                        "remote_mount.cli.get_service_manager",
                        return_value=mock_manager,
                    ):
                        result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0, f"Exit code {result.exit_code}: {result.output}"
    assert "test-mount" in result.output
    assert "Watchdog service" in result.output


def test_list_empty_config():
    """List command shows helpful message when no mounts are configured."""
    runner = CliRunner()

    with runner.isolated_filesystem():
        config_path = Path("nonexistent_config.yaml")

        with patch("remote_mount.cli.get_config_path", return_value=config_path):
            result = runner.invoke(cli, ["list"])

    assert result.exit_code == 0, f"Exit code {result.exit_code}: {result.output}"
    # Should show helpful message referencing no mounts and how to add one
    output_lower = result.output.lower()
    assert "no mounts" in output_lower or "add" in output_lower
