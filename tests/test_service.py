"""Tests for service management (LaunchdManager and SystemdManager)."""

import os
from unittest.mock import call, patch
from xml.etree import ElementTree

from remote_mount.service import LABEL, UNIT_NAME, LaunchdManager, SystemdManager


class TestLaunchdManager:
    """Tests for macOS launchd service management."""

    def test_install_creates_plist_file(self, tmp_path):
        """install() creates a plist file in plist_dir."""
        manager = LaunchdManager(plist_dir=tmp_path)
        manager.install("/usr/local/bin/remote-mount")

        expected = tmp_path / f"{LABEL}.plist"
        assert expected.exists(), f"Plist file not found at {expected}"

    def test_install_plist_correct_xml_structure(self, tmp_path):
        """install() generates plist with Label, ProgramArguments, RunAtLoad, KeepAlive."""
        manager = LaunchdManager(plist_dir=tmp_path)
        manager.install("/usr/local/bin/remote-mount")

        plist_path = tmp_path / f"{LABEL}.plist"
        content = plist_path.read_text()

        # Parse XML
        root = ElementTree.fromstring(content)
        assert root.tag == "plist", "Root element should be <plist>"

        # Find the <dict> inside <plist>
        d = root.find("dict")
        assert d is not None, "Expected <dict> inside <plist>"

        # Build a key->value map from the alternating key/value elements
        keys = [el.text for el in d if el.tag == "key"]
        assert "Label" in keys
        assert "ProgramArguments" in keys
        assert "RunAtLoad" in keys
        assert "KeepAlive" in keys

        # Walk through dict children in pairs to validate values
        children = list(d)
        kv = {}
        for i in range(0, len(children) - 1, 2):
            key_el = children[i]
            val_el = children[i + 1]
            kv[key_el.text] = val_el

        # Label must be the service label constant
        assert kv["Label"].text == LABEL

        # ProgramArguments: first element is the watchdog_cmd, second is "_watchdog"
        args = [el.text for el in kv["ProgramArguments"]]
        assert args[0] == "/usr/local/bin/remote-mount"
        assert args[-1] == "_watchdog"

        # RunAtLoad and KeepAlive must be <true/>
        assert kv["RunAtLoad"].tag == "true"
        assert kv["KeepAlive"].tag == "true"

    def test_start_calls_bootstrap(self, tmp_path):
        """start() calls 'launchctl bootstrap gui/<uid> <plist_path>'."""
        manager = LaunchdManager(plist_dir=tmp_path)
        uid = os.getuid()
        plist_path = tmp_path / f"{LABEL}.plist"

        with patch("subprocess.run") as mock_run:
            manager.start()

        mock_run.assert_called_once_with(
            ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
            check=True,
        )

    def test_stop_calls_bootout(self, tmp_path):
        """stop() calls 'launchctl bootout gui/<uid>/com.remote-mount.watchdog'."""
        manager = LaunchdManager(plist_dir=tmp_path)
        uid = os.getuid()

        with patch("subprocess.run") as mock_run:
            manager.stop()

        mock_run.assert_called_once_with(
            ["launchctl", "bootout", f"gui/{uid}/{LABEL}"],
            check=True,
        )


class TestSystemdManager:
    """Tests for Linux systemd service management."""

    def test_install_creates_unit_file_with_correct_sections(self, tmp_path):
        """install() creates a unit file with [Unit], [Service], and [Install] sections."""
        manager = SystemdManager(unit_dir=tmp_path)
        manager.install("/usr/local/bin/remote-mount")

        unit_path = tmp_path / f"{UNIT_NAME}.service"
        assert unit_path.exists(), f"Unit file not found at {unit_path}"

        content = unit_path.read_text()

        # [Unit] section
        assert "[Unit]" in content
        assert "After=network-online.target" in content

        # [Service] section
        assert "[Service]" in content
        assert "Type=simple" in content
        assert "_watchdog" in content  # ExecStart includes _watchdog subcommand
        assert "Restart=always" in content
        assert "RestartSec=5" in content

        # [Install] section
        assert "[Install]" in content
        assert "WantedBy=default.target" in content

    def test_start_calls_systemctl(self, tmp_path):
        """start() calls daemon-reload then 'systemctl --user start <unit>'."""
        manager = SystemdManager(unit_dir=tmp_path)

        with patch("subprocess.run") as mock_run:
            manager.start()

        assert mock_run.call_count == 2
        calls = mock_run.call_args_list
        # First call: daemon-reload
        assert calls[0] == call(
            ["systemctl", "--user", "daemon-reload"],
            check=True,
        )
        # Second call: start
        assert calls[1] == call(
            ["systemctl", "--user", "start", UNIT_NAME],
            check=True,
        )

    def test_stop_calls_systemctl(self, tmp_path):
        """stop() calls 'systemctl --user stop <unit>'."""
        manager = SystemdManager(unit_dir=tmp_path)

        with patch("subprocess.run") as mock_run:
            manager.stop()

        mock_run.assert_called_once_with(
            ["systemctl", "--user", "stop", UNIT_NAME],
            check=True,
        )
