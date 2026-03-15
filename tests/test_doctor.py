"""Tests for doctor prerequisite checks."""

from unittest.mock import MagicMock, patch

from remote_mount.doctor import CheckResult, check_fuse, check_rclone, check_ssh_key


class TestCheckRclone:
    def test_rclone_found(self):
        """check_rclone returns a passing CheckResult with version when rclone is available."""
        with patch("shutil.which", return_value="/usr/local/bin/rclone"):
            mock_result = MagicMock()
            mock_result.stdout = "rclone v1.65.0\n- os/arch: darwin/arm64\n"
            with patch("subprocess.run", return_value=mock_result):
                result = check_rclone()

        assert isinstance(result, CheckResult)
        assert result.passed is True
        assert result.name == "rclone"
        assert "1.65.0" in result.detail

    def test_rclone_missing(self):
        """check_rclone returns a failing CheckResult with install_cmd when rclone is absent."""
        with patch("shutil.which", return_value=None):
            result = check_rclone()

        assert isinstance(result, CheckResult)
        assert result.passed is False
        assert result.name == "rclone"
        assert result.install_cmd == "brew install rclone"


class TestCheckSshKey:
    def test_ssh_key_exists(self):
        """check_ssh_key returns a passing CheckResult when an SSH key is found."""
        with patch("pathlib.Path.exists", return_value=True):
            result = check_ssh_key()

        assert isinstance(result, CheckResult)
        assert result.passed is True
        assert result.name == "ssh_key"
        assert result.detail is not None

    def test_ssh_key_missing(self):
        """check_ssh_key returns a failing CheckResult with install_cmd when no key found."""
        with patch("pathlib.Path.exists", return_value=False):
            result = check_ssh_key()

        assert isinstance(result, CheckResult)
        assert result.passed is False
        assert result.name == "ssh_key"
        assert "ssh-keygen" in result.install_cmd


class TestCheckFuse:
    def test_fuse_t_found_macos(self):
        """check_fuse returns passing CheckResult when fuse-t cask is installed on macOS."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            result = check_fuse("macos")

        assert isinstance(result, CheckResult)
        assert result.passed is True
        assert result.name == "fuse"
        assert "fuse-t" in result.detail

    def test_fuse_missing_macos(self):
        """check_fuse returns failing CheckResult with brew install cmd when fuse-t absent on macOS."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            result = check_fuse("macos")

        assert isinstance(result, CheckResult)
        assert result.passed is False
        assert result.name == "fuse"
        assert "brew" in result.install_cmd

    def test_fuse3_found_linux(self):
        """check_fuse returns passing CheckResult when fusermount3 or fusermount found on Linux."""
        with patch("shutil.which", return_value="/usr/bin/fusermount3"):
            result = check_fuse("linux")

        assert isinstance(result, CheckResult)
        assert result.passed is True
        assert result.name == "fuse"

    def test_fuse_missing_linux(self):
        """check_fuse returns failing CheckResult with apt install cmd when fuse absent on Linux."""
        with patch("shutil.which", return_value=None):
            result = check_fuse("linux")

        assert isinstance(result, CheckResult)
        assert result.passed is False
        assert result.name == "fuse"
        assert "fuse3" in result.install_cmd
