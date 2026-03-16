"""Tests for mount/unmount operations."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from remote_mount.config import MountConfig, RcloneConfig
from remote_mount.mounts import (
    build_rclone_command,
    do_mount,
    do_unmount,
    is_mounted,
)


class TestBuildRcloneCommand:
    def test_basic_linux(self):
        mount = MountConfig(host="myserver.example.com", mount_point="/mnt/remote")
        rclone = RcloneConfig()
        cmd = build_rclone_command(mount, rclone, platform="linux")
        assert cmd[0] == "rclone"
        assert cmd[1] == "mount"  # linux uses mount, not nfsmount
        assert ":sftp:/" in cmd
        assert "/mnt/remote" in cmd
        assert "--sftp-ssh" in cmd
        assert "ssh myserver.example.com" in cmd
        assert "--vfs-cache-mode" in cmd
        assert "--daemon" in cmd
        # Should NOT have --sftp-host (using --sftp-ssh instead)
        assert "--sftp-host" not in cmd

    def test_macos_uses_nfsmount(self):
        mount = MountConfig(host="myserver.example.com", mount_point="/mnt/remote")
        rclone = RcloneConfig()
        cmd = build_rclone_command(mount, rclone, platform="macos")
        assert cmd[1] == "nfsmount"  # macOS uses nfsmount

    def test_custom_remote_path(self):
        mount = MountConfig(
            host="myserver.example.com",
            remote_path="/data/share",
            mount_point="/mnt/share",
        )
        rclone = RcloneConfig()
        cmd = build_rclone_command(mount, rclone)
        assert ":sftp:/data/share" in cmd

    def test_extra_args(self):
        mount = MountConfig(host="myserver.example.com", mount_point="/mnt/remote")
        rclone = RcloneConfig(extra_args=["--log-level", "DEBUG"])
        cmd = build_rclone_command(mount, rclone)
        assert "--log-level" in cmd
        assert "DEBUG" in cmd

    def test_buffer_size(self):
        mount = MountConfig(host="myserver.example.com", mount_point="/mnt/remote")
        rclone = RcloneConfig(buffer_size="128M")
        cmd = build_rclone_command(mount, rclone)
        idx = cmd.index("--buffer-size")
        assert cmd[idx + 1] == "128M"

    def test_sftp_ssh_contains_host(self):
        mount = MountConfig(host="spark-1", mount_point="/mnt/remote")
        rclone = RcloneConfig()
        cmd = build_rclone_command(mount, rclone)
        idx = cmd.index("--sftp-ssh")
        assert cmd[idx + 1] == "ssh spark-1"


class TestDoMount:
    def test_creates_dir(self, tmp_path):
        mount_point = str(tmp_path / "newdir")
        mount = MountConfig(host="myserver.example.com", mount_point=mount_point)
        rclone = RcloneConfig()
        with patch("remote_mount.mounts.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            do_mount(mount, rclone)
        assert Path(mount_point).exists()

    def test_returns_error(self, tmp_path):
        mount_point = str(tmp_path / "newdir")
        mount = MountConfig(host="myserver.example.com", mount_point=mount_point)
        rclone = RcloneConfig()
        with patch("remote_mount.mounts.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="some error")
            result = do_mount(mount, rclone)
        assert result is not None
        assert isinstance(result, str)


class TestDoUnmount:
    def test_calls_correct_command(self):
        with patch("remote_mount.mounts.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            do_unmount("/mnt/remote", "macos")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["umount", "/mnt/remote"]

    def test_linux_fusermount(self):
        with patch("remote_mount.mounts.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            do_unmount("/mnt/remote", "linux")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["fusermount", "-uz", "/mnt/remote"]

    def test_returns_error_on_timeout(self):
        with patch("remote_mount.mounts.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="umount", timeout=10)
            result = do_unmount("/mnt/remote", "macos")
        assert result is not None
        assert isinstance(result, str)
        assert "timed out" in result.lower()


class TestTildeExpansion:
    def test_build_rclone_command_expands_tilde_in_mount_point(self):
        """build_rclone_command expands ~ to the real home directory, not literal ~."""
        from pathlib import Path

        mount = MountConfig(host="myserver.example.com", mount_point="~/mnt/test")
        rclone = RcloneConfig()
        cmd = build_rclone_command(mount, rclone)
        home = str(Path.home())
        # The command must not contain the raw tilde character
        assert "~" not in cmd, f"Literal ~ found in command: {cmd}"
        # The expanded home path must be present
        assert f"{home}/mnt/test" in cmd, (
            f"Expected expanded path {home}/mnt/test in command: {cmd}"
        )


class TestIsMounted:
    def test_mounted_and_responsive(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")
        assert is_mounted(str(tmp_path)) is True

    def test_not_mounted(self, tmp_path):
        non_existent = str(tmp_path / "nonexistent")
        assert is_mounted(non_existent) is False
