"""cnsr-rotate.sh: a backup from the pool is resolved again before it is checked and used."""

from __future__ import annotations

import sys

import pytest
from rotate_harness import OLD_SNI, node  # noqa: F401  (fixture)
from test_rotate_script import A, B, rotating

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash is not available on Windows")


def pooled(node, *backups):
    rotating(node)
    node.pool_backups(*backups)
    return node


def test_a_pool_backup_goes_to_the_address_it_resolves_to_now(node):
    pooled(node, A)
    node.resolves("a.example.com", "192.0.2.77", "192.0.2.78")
    node.valid("a.example.com")
    result = node.run("once")
    assert result.status == 0, result.stderr
    assert node.reality()["dest"] == "192.0.2.77:443" and node.reality()["serverNames"] == ["a.example.com"]
    assert any(call == "validate-candidates.sh a.example.com 192.0.2.77" for call in result.calls)
    assert node.sent("PUT", "line") == [{"sni": "a.example.com", "dest_ip": "192.0.2.77"}]


def test_a_neighbour_keeps_the_address_it_was_scanned_at(node):
    rotating(node, A)
    node.resolves("a.example.com", "192.0.2.77")
    node.valid("a.example.com")
    result = node.run("once")
    assert node.reality()["dest"] == "203.0.113.10:443"
    assert not any(call.startswith("getent") for call in result.calls)


def test_a_pool_backup_that_no_longer_resolves_is_dropped(node):
    pooled(node, A, B)
    node.resolves("b.example.com", "192.0.2.80")
    node.valid("a.example.com", "b.example.com")
    result = node.run("once")
    assert node.reality()["serverNames"] == ["b.example.com"] and node.backup_domains() == []
    assert "解析" in result.stderr


def test_an_answer_that_is_not_an_address_counts_as_unresolved(node):
    pooled(node, A)
    (node.base / "getent-a.example.com").write_text("not-an-address STREAM a\n")
    node.valid("a.example.com")
    node.run("once")
    assert node.reality()["serverNames"] == [OLD_SNI] and node.backup_domains() == []


def test_a_pool_backup_is_kept_when_the_node_itself_is_offline(node):
    pooled(node, A)
    node.offline()
    node.valid("a.example.com")
    node.run("once")
    assert node.reality()["serverNames"] == [OLD_SNI] and node.backup_domains() == ["a.example.com"]


def test_a_pool_backup_put_back_keeps_its_mark(node):
    import json

    pooled(node, A)
    node.resolves("a.example.com", "192.0.2.77")
    node.valid("a.example.com")
    node.fail("docker-test.rc", 1)
    node.run("once")
    [entry] = json.loads(node.read("backups.json"))
    assert entry["domain"] == "a.example.com" and entry["pool"] is True
