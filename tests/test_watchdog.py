"""Tests for watchdog tick logic."""

from unittest.mock import patch

from remote_mount.config import MountConfig, RcloneConfig
from remote_mount.mounts import WatchdogState, watchdog_tick


class TestWatchdogTick:
    """Tests for watchdog_tick single-tick logic."""

    def _make_mount(self) -> MountConfig:
        return MountConfig(
            host="myserver.example.com",
            remote_path="/data",
            mount_point="/mnt/remote",
            watchdog=True,
        )

    def _make_rclone(self) -> RcloneConfig:
        return RcloneConfig()

    def test_healthy_resets_backoff(self):
        """When mount is healthy, backoff resets to base and action is 'healthy'."""
        mount = self._make_mount()
        rclone = self._make_rclone()
        state = WatchdogState(backoff=60, action="mount_failed")

        with patch("remote_mount.mounts.is_mounted", return_value=True):
            watchdog_tick(
                mount, state, rclone, "macos", backoff_base=5, backoff_max=300
            )

        assert state.action == "healthy"
        assert state.backoff == 5

    def test_unhealthy_reachable_remounts(self):
        """When mount is unhealthy but host is reachable, it remounts and resets backoff."""
        mount = self._make_mount()
        rclone = self._make_rclone()
        state = WatchdogState(backoff=10, action="")

        with (
            patch("remote_mount.mounts.is_mounted", return_value=False),
            patch("remote_mount.mounts.do_unmount", return_value=None),
            patch("remote_mount.mounts.check_host_reachable", return_value=True),
            patch("remote_mount.mounts.do_mount", return_value=None),
        ):
            watchdog_tick(
                mount, state, rclone, "macos", backoff_base=5, backoff_max=300
            )

        assert state.action == "remounted"
        assert state.backoff == 5

    def test_unhealthy_unreachable_backs_off(self):
        """When mount is unhealthy and host is unreachable, backoff doubles (5->10)."""
        mount = self._make_mount()
        rclone = self._make_rclone()
        state = WatchdogState(backoff=5, action="")

        with (
            patch("remote_mount.mounts.is_mounted", return_value=False),
            patch("remote_mount.mounts.do_unmount", return_value=None),
            patch("remote_mount.mounts.check_host_reachable", return_value=False),
        ):
            watchdog_tick(
                mount, state, rclone, "macos", backoff_base=5, backoff_max=300
            )

        assert state.action == "unreachable"
        assert state.backoff == 10

    def test_backoff_caps_200_to_300(self):
        """Backoff doubles but is capped at backoff_max: 200 -> min(400, 300) = 300."""
        mount = self._make_mount()
        rclone = self._make_rclone()
        state = WatchdogState(backoff=200, action="")

        with (
            patch("remote_mount.mounts.is_mounted", return_value=False),
            patch("remote_mount.mounts.do_unmount", return_value=None),
            patch("remote_mount.mounts.check_host_reachable", return_value=False),
        ):
            watchdog_tick(
                mount, state, rclone, "macos", backoff_base=5, backoff_max=300
            )

        assert state.backoff == 300

    def test_backoff_stays_at_300(self):
        """Backoff already at max stays capped: 300 -> min(600, 300) = 300."""
        mount = self._make_mount()
        rclone = self._make_rclone()
        state = WatchdogState(backoff=300, action="")

        with (
            patch("remote_mount.mounts.is_mounted", return_value=False),
            patch("remote_mount.mounts.do_unmount", return_value=None),
            patch("remote_mount.mounts.check_host_reachable", return_value=False),
        ):
            watchdog_tick(
                mount, state, rclone, "macos", backoff_base=5, backoff_max=300
            )

        assert state.backoff == 300

    def test_mount_failed_doubles_backoff(self):
        """When host is reachable but mount fails, action='mount_failed' and backoff doubles."""
        mount = self._make_mount()
        rclone = self._make_rclone()
        state = WatchdogState(backoff=10, action="")

        with (
            patch("remote_mount.mounts.is_mounted", return_value=False),
            patch("remote_mount.mounts.do_unmount", return_value=None),
            patch("remote_mount.mounts.check_host_reachable", return_value=True),
            patch(
                "remote_mount.mounts.do_mount",
                return_value="rclone: connection refused",
            ),
        ):
            watchdog_tick(
                mount, state, rclone, "macos", backoff_base=5, backoff_max=300
            )

        assert state.action == "mount_failed"
        assert state.backoff == 20
