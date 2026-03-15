"""SSH config management for remote-mount."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

MANAGED_MARKER = "# managed by remote-mount"


class HostBlockInfo(TypedDict):
    content: str
    start_line: int
    end_line: int
    managed: bool


def generate_host_block(
    host: str,
    user: str,
    identity_file: str,
    tailscale_ip: str,
    lan_ip: str,
    fqdn: str,
) -> str:
    """Build an SSH Host block with Tailscale failover ProxyCommand.

    Addresses are tried in order: tailscale_ip, lan_ip, fqdn.
    Empty values are excluded from the address list.
    """
    addresses = [a for a in [tailscale_ip, lan_ip, fqdn] if a]
    addr_list = " ".join(addresses)
    proxy_cmd = (
        f"bash -c 'for addr in {addr_list};"
        r" do nc -z -G 3 \"$addr\" 22 && exec nc \"$addr\" 22; done'"
    )
    lines = [
        f"Host {host}",
        f"    User {user}",
        f"    IdentityFile {identity_file}",
        f"    ProxyCommand {proxy_cmd}",
    ]
    return "\n".join(lines) + "\n"


def find_host_block(config_text: str, host: str) -> HostBlockInfo | None:
    """Find an SSH Host block by hostname.

    Returns HostBlockInfo with:
      - content: the Host block lines (excluding any preceding MANAGED_MARKER)
      - start_line: first line of the region to replace (includes MANAGED_MARKER if managed)
      - end_line: last line of the region to replace (inclusive, includes trailing blanks)
      - managed: True if the preceding line is MANAGED_MARKER

    Returns None if the host block is not found.
    """
    lines = config_text.splitlines()
    host_pattern = re.compile(r"^Host\s+" + re.escape(host) + r"\s*$")

    for i, line in enumerate(lines):
        if not host_pattern.match(line):
            continue

        # Find the end of the block: the index of the next bare Host line (exclusive)
        next_host_idx = len(lines)
        for j in range(i + 1, len(lines)):
            if re.match(r"^Host\s+", lines[j]):
                next_host_idx = j
                break

        # end_line is the last line index before the next Host block (inclusive)
        end_line = next_host_idx - 1

        # Check for MANAGED_MARKER on the preceding line
        managed = i > 0 and lines[i - 1].strip() == MANAGED_MARKER
        start_line = (i - 1) if managed else i

        # content is just the Host block (without the marker line)
        content = "\n".join(lines[i : end_line + 1])

        return HostBlockInfo(
            content=content,
            start_line=start_line,
            end_line=end_line,
            managed=managed,
        )

    return None


def write_host_block(config_path: Path, host: str, new_block: str) -> str:
    """Write a host block to the SSH config file.

    Returns:
        'added'    — block was written to a new or existing file without a prior entry
        'updated'  — existing managed block was replaced with the new block
        'conflict' — an unmanaged block already exists; file was not modified
    """
    # Case 1: file does not exist — create it
    if not config_path.exists():
        config_path.write_text(new_block.rstrip("\n") + "\n", encoding="utf-8")
        return "added"

    text = config_path.read_text(encoding="utf-8")
    info = find_host_block(text, host)

    # Case 2: no existing block — append
    if info is None:
        separator = "\n" if text and not text.endswith("\n\n") else ""
        config_path.write_text(
            text + separator + new_block.rstrip("\n") + "\n",
            encoding="utf-8",
        )
        return "added"

    # Case 3: unmanaged block — do not touch
    if not info["managed"]:
        return "conflict"

    # Case 4: managed block — replace it
    lines = text.splitlines(keepends=True)
    start = info["start_line"]
    end = info["end_line"]

    before = "".join(lines[:start])
    after = "".join(lines[end + 1 :])
    config_path.write_text(
        before + new_block.rstrip("\n") + "\n" + after,
        encoding="utf-8",
    )
    return "updated"
