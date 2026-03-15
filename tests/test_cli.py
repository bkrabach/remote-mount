from unittest.mock import patch

from click.testing import CliRunner

from remote_mount.cli import cli
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
