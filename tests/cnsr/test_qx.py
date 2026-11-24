"""Tests for the Quantumult X lines printed after a deployment."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cnsr.qx import node_line, share_link, user_line
from cnsr.state import Node, XrayInfo, XrayUser


def test_node_line_exact():
    x = XrayInfo("11111111-1111-4111-8111-111111111111", "PUB", "0123456789abcdef", "www.example.com", "198.51.100.7")
    assert node_line("edge-cache-v123.example.com", x, "jp-1") == (
        "vless=edge-cache-v123.example.com:443, method=none, password=11111111-1111-4111-8111-111111111111, "
        "obfs=over-tls, obfs-host=www.example.com, reality-base64-pubkey=PUB, reality-hex-shortid=0123456789abcdef, "
        "vless-flow=xtls-rprx-vision, udp-relay=true, tag=jp-1")


def test_node_line_never_enables_fast_open():
    x = XrayInfo("u", "k", "s", "www.example.com", "198.51.100.7")
    assert "fast-open" not in node_line("n.example.com", x, "jp-1")



SHARED = json.loads((Path(__file__).parents[1] / "shared" / "share-links.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", SHARED, ids=lambda case: case["line"][:22])
def test_a_line_becomes_the_same_share_link_the_worker_makes(case):
    assert share_link(case["line"]) == case["link"]


def test_a_users_line_is_the_nodes_with_the_users_uuid_and_a_tag_of_its_own():
    x = XrayInfo("owner", "PUB", "0123456789abcdef", "www.example.com", "198.51.100.7")
    node = Node("jp-1", "vps", "192.0.2.1", domain="n.example.com", xray=x, line=node_line("n.example.com", x, "jp-1"))
    line = user_line(node, XrayUser("alice", "alice-uuid"))
    assert line == node.line.replace("password=owner", "password=alice-uuid").replace("tag=jp-1", "tag=jp-1-alice")
