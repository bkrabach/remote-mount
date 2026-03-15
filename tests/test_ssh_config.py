"""Tests for remote_mount.ssh_config module."""

from remote_mount.ssh_config import (
    MANAGED_MARKER,
    find_host_block,
    generate_host_block,
    write_host_block,
)


class TestGenerateHostBlock:
    def test_basic_block_with_all_addresses(self):
        """Block includes tailscale_ip, lan_ip, and fqdn in ProxyCommand."""
        block = generate_host_block(
            host="myserver",
            user="alice",
            identity_file="~/.ssh/id_ed25519",
            tailscale_ip="100.64.1.1",
            lan_ip="192.168.1.10",
            fqdn="myserver.local",
        )
        assert "Host myserver" in block
        assert "User alice" in block
        assert "IdentityFile ~/.ssh/id_ed25519" in block
        # All three addresses present in ProxyCommand
        assert "100.64.1.1" in block
        assert "192.168.1.10" in block
        assert "myserver.local" in block
        # ProxyCommand uses bash -c with nc loop
        assert "ProxyCommand" in block
        assert "bash -c" in block
        assert "nc -z" in block

    def test_no_lan_ip_excludes_from_addresses(self):
        """Empty lan_ip is excluded from ProxyCommand address list."""
        block = generate_host_block(
            host="myserver",
            user="alice",
            identity_file="~/.ssh/id_ed25519",
            tailscale_ip="100.64.1.1",
            lan_ip="",
            fqdn="myserver.local",
        )
        assert "100.64.1.1" in block
        assert "myserver.local" in block
        # Empty lan_ip should not appear as an empty string address
        # The address list should only have 2 entries (no double-space from empty addr)
        # Check that no consecutive spaces indicating empty addr
        proxy_line = next(line for line in block.splitlines() if "ProxyCommand" in line)
        # Empty string should not be in addr list
        assert '""' not in proxy_line
        assert "for addr in  " not in proxy_line


class TestFindHostBlock:
    def test_finds_managed_block(self):
        """Returns HostBlockInfo with managed=True when MANAGED_MARKER precedes block."""
        config_text = f"""\
Host other
    User bob

{MANAGED_MARKER}
Host myserver
    User alice
    IdentityFile ~/.ssh/id_ed25519
    ProxyCommand bash -c 'echo test'

Host another
    User charlie
"""
        result = find_host_block(config_text, "myserver")
        assert result is not None
        assert result["managed"] is True
        assert "Host myserver" in result["content"]
        assert "User alice" in result["content"]

    def test_finds_unmanaged_block(self):
        """Returns HostBlockInfo with managed=False when no MANAGED_MARKER."""
        config_text = """\
Host myserver
    User alice
    IdentityFile ~/.ssh/id_ed25519

Host other
    User bob
"""
        result = find_host_block(config_text, "myserver")
        assert result is not None
        assert result["managed"] is False
        assert "Host myserver" in result["content"]

    def test_returns_none_when_not_found(self):
        """Returns None when host does not exist in config."""
        config_text = """\
Host other
    User bob

Host another
    User charlie
"""
        result = find_host_block(config_text, "myserver")
        assert result is None


class TestWriteHostBlock:
    def test_append_new_block_to_existing_file(self, tmp_path):
        """Appends block when file exists but host not present; returns 'added'."""
        config_path = tmp_path / "ssh_config"
        config_path.write_text(
            "Host other\n    User bob\n\n",
            encoding="utf-8",
        )
        new_block = f"{MANAGED_MARKER}\nHost myserver\n    User alice\n"
        result = write_host_block(config_path, "myserver", new_block)
        assert result == "added"
        content = config_path.read_text(encoding="utf-8")
        assert "Host myserver" in content
        assert "Host other" in content  # original preserved

    def test_update_managed_block(self, tmp_path):
        """Replaces managed block with new content; returns 'updated'."""
        config_path = tmp_path / "ssh_config"
        original = (
            f"Host other\n    User bob\n\n"
            f"{MANAGED_MARKER}\n"
            f"Host myserver\n    User alice\n    IdentityFile ~/.ssh/old_key\n\n"
        )
        config_path.write_text(original, encoding="utf-8")
        new_block = f"{MANAGED_MARKER}\nHost myserver\n    User alice\n    IdentityFile ~/.ssh/new_key\n"
        result = write_host_block(config_path, "myserver", new_block)
        assert result == "updated"
        content = config_path.read_text(encoding="utf-8")
        assert "new_key" in content
        assert "old_key" not in content
        assert "Host other" in content  # original preserved

    def test_conflict_on_unmanaged_block(self, tmp_path):
        """Does not modify file when unmanaged block exists; returns 'conflict'."""
        config_path = tmp_path / "ssh_config"
        original = (
            "Host myserver\n    User alice\n    IdentityFile ~/.ssh/manual_key\n\n"
        )
        config_path.write_text(original, encoding="utf-8")
        new_block = f"{MANAGED_MARKER}\nHost myserver\n    User alice\n    IdentityFile ~/.ssh/new_key\n"
        result = write_host_block(config_path, "myserver", new_block)
        assert result == "conflict"
        # File should be unchanged
        content = config_path.read_text(encoding="utf-8")
        assert content == original

    def test_creates_file_if_missing(self, tmp_path):
        """Creates config file and writes block when file does not exist; returns 'added'."""
        config_path = tmp_path / "ssh_config"
        assert not config_path.exists()
        new_block = f"{MANAGED_MARKER}\nHost myserver\n    User alice\n"
        result = write_host_block(config_path, "myserver", new_block)
        assert result == "added"
        assert config_path.exists()
        content = config_path.read_text(encoding="utf-8")
        assert "Host myserver" in content
        assert MANAGED_MARKER in content
