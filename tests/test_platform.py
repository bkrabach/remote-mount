"""Tests for platform detection module."""

from unittest.mock import mock_open, patch

from remote_mount.platform import (
    detect_platform,
    get_fuse_package,
    get_install_command,
    get_unmount_command,
)


class TestDetectPlatform:
    def test_macos(self):
        with patch("sys.platform", "darwin"):
            assert detect_platform() == "macos"

    def test_linux(self):
        with patch("sys.platform", "linux"):
            with patch("builtins.open", mock_open(read_data="Linux version 5.15.0")):
                assert detect_platform() == "linux"

    def test_wsl2(self):
        with patch("sys.platform", "linux"):
            with patch(
                "builtins.open",
                mock_open(read_data="Linux version 5.15.0-microsoft-standard-WSL2"),
            ):
                assert detect_platform() == "wsl2"

    def test_wsl2_microsoft_lowercase(self):
        with patch("sys.platform", "linux"):
            with patch(
                "builtins.open",
                mock_open(read_data="Linux version 5.10.102.1-microsoft-standard-WSL2"),
            ):
                assert detect_platform() == "wsl2"

    def test_linux_no_proc_version(self):
        with patch("sys.platform", "linux"):
            with patch("builtins.open", side_effect=OSError("No such file")):
                assert detect_platform() == "linux"

    def test_windows(self):
        with patch("sys.platform", "win32"):
            assert detect_platform() == "windows"


class TestFusePackage:
    def test_macos(self):
        assert get_fuse_package("macos") == "fuse-t"

    def test_linux(self):
        assert get_fuse_package("linux") == "fuse3"

    def test_wsl2(self):
        assert get_fuse_package("wsl2") == "fuse3"


class TestInstallCommand:
    def test_macos(self):
        assert get_install_command("macos") == "brew install --cask fuse-t"

    def test_linux(self):
        assert get_install_command("linux") == "sudo apt install fuse3 libfuse3-dev"

    def test_wsl2(self):
        assert get_install_command("wsl2") == "sudo apt install fuse3 libfuse3-dev"


class TestUnmountCommand:
    def test_macos(self):
        assert get_unmount_command("macos", "/mnt/remote") == ["umount", "/mnt/remote"]

    def test_linux(self):
        assert get_unmount_command("linux", "/mnt/remote") == [
            "fusermount",
            "-uz",
            "/mnt/remote",
        ]

    def test_wsl2(self):
        assert get_unmount_command("wsl2", "/mnt/remote") == [
            "fusermount",
            "-uz",
            "/mnt/remote",
        ]
