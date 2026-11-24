"""Tests for the pool of well-known domains that tops up a node's SNI candidates."""

from __future__ import annotations

import subprocess
import time

import pytest
from deploy_fakes import run_up

from cnsr.deploy import steps_sni
from cnsr.errors import CnsrError
from cnsr.scan import pool
from cnsr.scan.filters import basic_ok
from cnsr.scan.probe import Hit
from cnsr.scan.select import parse_backups
from cnsr.server.xray import BACKUPS_PATH, CONFIG_PATH, read_identity

JP = pool.domains("JP")


def has_pool(fakes, count: int = len(JP)) -> None:
    """The node is in Japan, resolves the first ``count`` pool domains and reaches them."""
    fakes.server.country = "JP"
    fakes.server.resolves = {domain: f"9.9.9.{n + 1}" for n, domain in enumerate(JP[:count])}
    fakes.server.latency |= {domain: 5 for domain in JP[:count]}


def neighbours(fakes, count: int) -> None:
    fakes.server.latency = {f"site{i}.example.com": 20 + i for i in range(count)}


def backups(fakes):
    return parse_backups(fakes.server.files[BACKUPS_PATH])


def sni(fakes) -> str:
    return read_identity(fakes.server.files[CONFIG_PATH])["sni"]


def test_the_lists_hold_plain_domains_without_repeats():
    for country in ("JP", "US", ""):
        listed = pool.domains(country)
        assert listed and len(set(listed)) == len(listed)
        assert all(basic_ok(Hit("192.0.2.1", domain, "CA", False)) for domain in listed)


def test_an_unlisted_country_gets_the_general_list():
    assert pool.domains("ZZ") == pool.domains("") != JP


def test_enough_neighbours_leave_the_pool_alone(fake_deps):
    has_pool(fake_deps)
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert not any(b.pool for b in backups(fake_deps)) and len(backups(fake_deps)) == 11
    assert not any(JP[0] in what for what in fake_deps.server.what())


def test_few_neighbours_are_topped_up_to_ten_backups_after_them(fake_deps):
    neighbours(fake_deps, 4)
    has_pool(fake_deps)
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert sni(fake_deps) == "site0.example.com"  # never a pool domain while a neighbour passes
    kept = backups(fake_deps)
    assert [b.domain for b in kept] == [*(f"site{i}.example.com" for i in (1, 2, 3)), *JP[:7]]
    assert [b.pool for b in kept] == [False] * 3 + [True] * 7


def test_no_neighbour_at_all_takes_the_sni_from_the_pool(fake_deps):
    fake_deps.hits = []
    has_pool(fake_deps)
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert sni(fake_deps) == JP[0] and [b.domain for b in backups(fake_deps)] == list(JP[1:11])


def test_neighbours_that_all_fail_on_the_node_take_the_sni_from_the_pool(fake_deps):
    neighbours(fake_deps, 0)
    has_pool(fake_deps)
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert sni(fake_deps) == JP[0]


def test_pool_domains_pass_the_checks_of_the_neighbours(fake_deps):
    neighbours(fake_deps, 1)
    has_pool(fake_deps)
    del fake_deps.server.latency[JP[0]]  # no TLS from the node
    fake_deps.server.reality_fails = {JP[1]}
    blocked = JP[2]  # blocked by name from this computer
    fake_deps.deps.sni_ok = lambda ip, domain: domain != blocked
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    kept = [b.domain for b in backups(fake_deps)]
    assert kept == list(JP[3:13])


def test_no_candidate_of_either_kind_still_stops(fake_deps):
    fake_deps.hits = []
    assert run_up(fake_deps, aws="jp-tokyo") == 1
    assert "不会盲选" in fake_deps.terminal.text and CONFIG_PATH not in fake_deps.server.files


def test_a_node_that_cannot_tell_its_country_uses_the_general_list(fake_deps):
    fake_deps.hits = []
    general = pool.domains("")
    fake_deps.server.country = CnsrError("curl 失败")
    fake_deps.server.resolves = {domain: "9.9.9.9" for domain in general}
    fake_deps.server.latency |= {domain: 5 for domain in general}
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert sni(fake_deps) == general[0]


def test_an_answer_that_is_not_an_address_is_not_a_candidate(fake_deps):
    fake_deps.hits = []
    has_pool(fake_deps)
    fake_deps.server.resolves[JP[0]] = "not-an-ip"
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert sni(fake_deps) == JP[1]


def test_a_refill_tops_up_without_the_sni_in_use(fake_deps):
    neighbours(fake_deps, 4)
    assert run_up(fake_deps, aws="jp-tokyo") == 0  # three backups, no pool yet
    assert len(backups(fake_deps)) == 3
    has_pool(fake_deps)
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    kept = backups(fake_deps)
    assert len(kept) == 10 and sni(fake_deps) not in [b.domain for b in kept]
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert len(fake_deps.calls["scan"]) == 2  # ten backups now: no scan, so no direct connection needed


def test_the_pool_domain_in_use_is_not_its_own_backup(fake_deps):
    fake_deps.hits = []
    has_pool(fake_deps, 3)
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    fake_deps.hits = None
    neighbours(fake_deps, 2)
    has_pool(fake_deps, 3)
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert sni(fake_deps) == JP[0] and JP[0] not in [b.domain for b in backups(fake_deps)]


@pytest.mark.parametrize("count", [0, 2])
def test_a_pool_that_gives_too_little_is_no_error_while_a_neighbour_passes(fake_deps, count):
    neighbours(fake_deps, 2)
    has_pool(fake_deps, count)
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert len(backups(fake_deps)) == 1 + count


# ---- neighbours DNS does not place where they were found ---------------------------------------


def test_a_neighbour_dns_places_elsewhere_comes_after_the_pool(fake_deps):
    """Its address shows a certificate it borrows: most likely somebody's node."""
    neighbours(fake_deps, 3)
    has_pool(fake_deps)
    fake_deps.server.resolves["site0.example.com"] = "9.9.9.200"  # the fastest
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert sni(fake_deps) == "site1.example.com"
    kept = backups(fake_deps)
    assert [b.domain for b in kept] == ["site2.example.com", *JP[:9], "site0.example.com"]
    assert [b.domain for b in kept if b.foreign] == ["site0.example.com"]


def test_any_of_several_addresses_places_a_neighbour(fake_deps):
    neighbours(fake_deps, 1)
    fake_deps.server.resolves["site0.example.com"] = ["9.9.9.200", "203.0.113.10"]
    has_pool(fake_deps, 2)
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert sni(fake_deps) == "site0.example.com"


def test_a_neighbour_that_does_not_resolve_is_not_placed_either(fake_deps):
    neighbours(fake_deps, 2)
    has_pool(fake_deps)
    fake_deps.server.resolves["site0.example.com"] = []
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert sni(fake_deps) == "site1.example.com" and backups(fake_deps)[-1].domain == "site0.example.com"


def test_a_pool_domain_is_preferred_to_a_neighbour_dns_places_elsewhere(fake_deps):
    neighbours(fake_deps, 1)
    has_pool(fake_deps)
    fake_deps.server.resolves["site0.example.com"] = "9.9.9.200"
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert sni(fake_deps) == JP[0]


def test_it_is_still_used_when_there_is_nothing_else(fake_deps):
    neighbours(fake_deps, 1)
    fake_deps.server.resolves["site0.example.com"] = "9.9.9.200"
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert sni(fake_deps) == "site0.example.com"


def test_a_rerun_that_skips_the_scan_still_puts_them_last(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0  # eleven backups
    first = backups(fake_deps)[0].domain
    fake_deps.server.resolves[first] = "9.9.9.200"
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert len(fake_deps.calls["scan"]) == 1
    kept = backups(fake_deps)
    assert kept[-1].domain == first and kept[-1].foreign and len(kept) == 11


def test_a_rerun_that_changes_no_order_leaves_the_file_alone(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    start = len(fake_deps.server.log)
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert f"put {BACKUPS_PATH}" not in fake_deps.server.what()[start:]


def test_a_lookup_that_fails_on_a_rerun_changes_nothing(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    before = fake_deps.server.files[BACKUPS_PATH]
    fake_deps.server.scanned.clear()  # the node resolves nothing: that says nothing about any domain
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert fake_deps.server.files[BACKUPS_PATH] == before


def test_an_address_of_the_same_provider_places_a_neighbour(fake_deps):
    """A load balancer's addresses come and go: DNS answers with others of the same cloud."""
    neighbours(fake_deps, 2)
    has_pool(fake_deps)
    server = fake_deps.server
    server.resolves["site0.example.com"] = ["9.9.9.200", "9.9.9.201"]
    server.reverse = {"203.0.113.10": "ec2-203-0-113-10.ap-x.compute.amazonaws.com",
                      "9.9.9.201": "ec2-9-9-9-201.ap-x.compute.amazonaws.com"}  # fmt: skip
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert sni(fake_deps) == "site0.example.com" and not any(b.foreign for b in backups(fake_deps))


@pytest.mark.parametrize(
    "reverse",
    [
        {"203.0.113.10": "host.vendor.example.net", "9.9.9.200": "ec2-9-9-9-200.compute.amazonaws.com"},
        {"9.9.9.200": "ec2-9-9-9-200.compute.amazonaws.com"},
        {"203.0.113.10": "localhost", "9.9.9.200": "localhost"},  # says nothing about who owns it
        {},
    ],
)
def test_another_provider_or_none_does_not(fake_deps, reverse):
    neighbours(fake_deps, 2)
    has_pool(fake_deps)
    fake_deps.server.resolves["site0.example.com"] = "9.9.9.200"
    fake_deps.server.reverse = reverse
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert sni(fake_deps) == "site1.example.com"


def test_neighbours_dns_places_right_need_no_reverse_lookup(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert not any("getent hosts" in what for what in fake_deps.server.what())


@pytest.mark.parametrize(
    "ours,theirs,same",
    [
        ("p1.tokyo.ocn.ne.jp", "www1.sakura.ne.jp", False),
        ("p1.tokyo.ocn.ne.jp", "p2.osaka.ocn.ne.jp", True),
        ("a.host.co.uk", "b.other.co.uk", False),
        ("a.b.host.com.cn", "c.host.com.cn", True),
        ("x.compute.amazonaws.com", "y.s3.amazonaws.com", True),
        ("ocn.ne.jp", "ocn.ne.jp", False),  # nothing in front of the provider: not a host's name
    ],
)
def test_a_providers_name_is_what_stands_before_the_public_suffix(fake_deps, ours, theirs, same):
    neighbours(fake_deps, 2)
    has_pool(fake_deps)
    server = fake_deps.server
    server.resolves["site0.example.com"] = "9.9.9.200"
    server.reverse = {"203.0.113.10": ours, "9.9.9.200": theirs}
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert sni(fake_deps) == ("site0.example.com" if same else "site1.example.com")


def test_lookups_run_side_by_side_with_a_limit_each():
    for script in (steps_sni.RESOLVE, steps_sni.REVERSE):
        assert "timeout 5 getent" in script and script.rstrip().endswith("wait") and "&" in script


@pytest.mark.parametrize("script,args", [("RESOLVE", ["a", "b"]), ("REVERSE", ["1.1.1.1", "2.2.2.2"])])
def test_the_lookups_run_under_a_plain_sh(tmp_path, script, args):
    """`timeout` and `getent` stand-ins: one that hangs is cut off, the others still answer."""
    tool = tmp_path / "getent"
    tool.write_text('#!/bin/sh\ncase "$2" in a|1.1.1.1) exec sleep 30;; esac\necho "$2 STREAM $2"\n')
    limit = tmp_path / "timeout"
    limit.write_text('#!/bin/sh\nshift\n"$@" & p=$!\n( sleep 1; kill $p 2>/dev/null ) >/dev/null 2>&1 &\nwait $p\n')
    for path in (tool, limit):
        path.chmod(0o755)
    started = time.monotonic()
    out = subprocess.run(["sh", "-c", getattr(steps_sni, script), "sh", *args], capture_output=True, text=True,
                         env={"PATH": f"{tmp_path}:/usr/bin:/bin"}, timeout=25).stdout  # fmt: skip
    assert time.monotonic() - started < 15 and args[1] in out


def test_a_lookup_that_fails_outright_does_not_fail_the_run(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    before = fake_deps.server.files[BACKUPS_PATH]
    fake_deps.server.lookups_fail = True
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert fake_deps.server.files[BACKUPS_PATH] == before
