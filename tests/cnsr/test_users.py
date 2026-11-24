"""``cnsr user``: people a node is shared with, each a client of its own that can be taken back alone."""

from __future__ import annotations

import argparse
import json

import pytest
from deploy_fakes import run_up

from cnsr import runlog
from cnsr.commands import user
from cnsr.errors import CnsrError
from cnsr.qx import share_link, user_line
from cnsr.server.xray import CONFIG_PATH, read_identity

STOP = "systemctl stop cnsr-rotate.service"
LAUNCH = "systemd-run --quiet --collect --unit=cnsr-apply-config bash /opt/cnsr/bin/apply-config.sh "
APPLY_PATH, RESULT = "/opt/cnsr/bin/apply-config.sh", "/opt/cnsr/apply-result"
COMPOSE_RESTART = "docker compose -f /opt/cnsr/xray/compose.yml restart"
SWITCHING = "/opt/cnsr/switching"
XRAY_MARKER = "/opt/cnsr/xray/.restart-pending"


def run_user(fakes, action: str, name: str, alias: str = "jp-1") -> tuple[int, str]:
    fakes.terminal.clear()
    ns = argparse.Namespace(command="user", action=action, alias=alias, name=name)
    return user.run(ns, fakes.deps), fakes.terminal.text


def clients(fakes) -> dict[str, str]:
    """email -> UUID of every client in the node's config."""
    config = json.loads(fakes.server.files[CONFIG_PATH])
    return {client["email"]: client["id"] for client in config["inbounds"][0]["settings"]["clients"]}


def names(fakes) -> list[str]:
    return [u.name for u in fakes.node().users]


@pytest.fixture
def up(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    return fake_deps


# ---- adding ------------------------------------------------------------------------------------


def test_adding_a_user_puts_a_client_of_its_own_behind_the_owner(up):
    owner = up.node().xray.uuid
    code, out = run_user(up, "add", "alice")
    assert code == 0, out
    (alice,) = up.node().users
    assert clients(up) == {"jp-1@cnsr": owner, "alice@jp-1": alice.uuid} and alice.uuid != owner
    assert list(clients(up))[0] == "jp-1@cnsr"
    node = up.node()
    assert user_line(node, alice) in out and share_link(user_line(node, alice)) in out
    assert owner not in up.terminal.screen  # the owner's own link is not what gets shared


def test_the_owner_the_key_and_the_sni_stay(up):
    before = read_identity(up.server.files[CONFIG_PATH])
    run_user(up, "add", "alice")
    run_user(up, "add", "bob")
    assert read_identity(up.server.files[CONFIG_PATH]) == before
    assert names(up) == ["alice", "bob"]


def test_xray_is_tested_restarted_and_checked_with_rotation_stopped(up):
    start = len(up.server.log)
    run_user(up, "add", "alice")
    what = up.server.what()[start:]
    order = [STOP, f"put {APPLY_PATH}", LAUNCH, COMPOSE_RESTART]
    found = [next(i for i, step in enumerate(what) if step.startswith(wanted)) for wanted in order]
    assert found == sorted(found) and any("-test" in step for step in what[: found[2]])
    assert up.server.service == "active" and XRAY_MARKER not in up.server.files


def test_the_subscription_keeps_only_the_owner(up):
    line = up.node().line
    run_user(up, "add", "alice")
    assert up.node().line == line


def test_adding_the_same_name_again_changes_nothing_and_shows_the_links(up):
    run_user(up, "add", "alice")
    (alice,) = up.node().users
    start = len(up.server.log)
    code, out = run_user(up, "add", "alice")
    assert code == 0 and user_line(up.node(), alice) in out
    assert up.node().users == [alice] and COMPOSE_RESTART not in up.server.what()[start:]


@pytest.mark.parametrize("name", ["Alice", "a b", "", "-x"])
def test_a_bad_name_is_refused_before_anything_happens(up, name):
    start = len(up.server.log)
    code, out = run_user(up, "add", name)
    assert code == 1 and "用户名字" in out and up.server.log[start:] == []


def test_a_rerun_of_up_keeps_the_users(up):
    run_user(up, "add", "alice")
    before = clients(up)
    start = len(up.server.log)
    assert run_up(up, aws="jp-tokyo") == 0
    assert clients(up) == before and names(up) == ["alice"]
    assert COMPOSE_RESTART not in up.server.what()[start:]  # the same text: no needless restart


def test_a_rotation_since_the_record_was_read_is_kept(up):
    """The node switched its SNI and the record is still the old one."""
    config = json.loads(up.server.files[CONFIG_PATH])
    reality = config["inbounds"][0]["streamSettings"]["realitySettings"]
    reality.update(dest="203.0.113.99:443", serverNames=["new.example.com"])
    up.server.files[CONFIG_PATH] = json.dumps(config, indent=2) + "\n"
    code, out = run_user(up, "add", "alice")
    assert code == 0 and "obfs-host=new.example.com" in out
    node = up.node()
    assert (node.xray.sni, node.xray.dest_ip) == ("new.example.com", "203.0.113.99")
    assert "obfs-host=new.example.com" in node.line


def test_a_switch_the_node_never_finished_stops_the_change(up):
    """Its recovery would put the config from before the change back."""
    up.server.files[SWITCHING] = "x\n"
    before = clients(up)
    code, out = run_user(up, "add", "alice")
    assert code == 1 and "cnsr up jp-1" in out
    assert clients(up) == before and names(up) == [] and up.server.service == "active"


# ---- failures ----------------------------------------------------------------------------------


def test_a_config_xray_refuses_changes_nothing(up, monkeypatch):
    before = up.server.files[CONFIG_PATH]
    refuse_test(up, monkeypatch)
    code, out = run_user(up, "add", "alice")
    assert code == 1 and "xray -test" in out
    assert up.server.files[CONFIG_PATH] == before and names(up) == [] and up.server.service == "active"


def test_a_handshake_that_fails_puts_the_old_config_back(up):
    before = up.server.files[CONFIG_PATH]
    up.server.apply_outcome = "rolled-back handshake"
    code, out = run_user(up, "add", "alice")
    assert code == 1 and "已恢复" in out
    assert up.server.files[CONFIG_PATH] == before and names(up) == []
    assert up.server.service == "active" and XRAY_MARKER not in up.server.files


def test_the_restart_may_cut_the_connection_it_is_asked_over(up):
    """This computer may reach the node through the node's own Xray."""
    up.server.restart_cuts = 4  # the launch itself, and the next tries to connect
    code, out = run_user(up, "add", "alice")
    assert code == 0, out
    (alice,) = up.node().users
    assert alice.uuid in clients(up).values() and user_line(up.node(), alice) in out
    assert up.server.service == "active" and XRAY_MARKER not in up.server.files and RESULT not in up.server.files


def test_taking_back_survives_the_cut_too(up):
    run_user(up, "add", "alice")
    up.server.restart_cuts = 4
    up.terminal.inputs = ["1"]
    code, out = run_user(up, "rm", "alice")
    assert code == 0, out
    assert names(up) == [] and "alice@jp-1" not in clients(up)


def test_a_node_that_never_reports_is_finished_by_the_same_command(up):
    up.server.apply_outcome = None
    code, out = run_user(up, "add", "alice")
    assert code == 1 and "重跑同一条命令" in out
    assert names(up) == ["alice"]  # recorded first, so nothing on the node is forgotten
    assert XRAY_MARKER in up.server.files
    (alice,) = up.node().users
    up.server.apply_outcome = "ok"
    code, out = run_user(up, "add", "alice")
    assert code == 0 and up.node().users == [alice] and alice.uuid in clients(up).values()
    assert XRAY_MARKER not in up.server.files


def test_an_old_result_is_not_taken_for_this_runs(up):
    up.server.files[RESULT] = "0123456789abcdef ok\n"
    up.server.apply_outcome = None
    assert run_user(up, "add", "alice")[0] == 1


def test_a_rollback_that_failed_says_to_look_at_the_node(up):
    up.server.apply_outcome = "failed"
    code, out = run_user(up, "add", "alice")
    assert code == 1 and "cnsr up jp-1" in out


def test_an_interrupt_before_the_launch_starts_rotation_again(up):
    up.server.fail_once[f"put {APPLY_PATH}"] = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        run_user(up, "add", "alice")
    assert up.server.service == "active"


# ---- taking back -------------------------------------------------------------------------------


def test_taking_a_user_back_removes_only_that_client(up):
    run_user(up, "add", "alice")
    run_user(up, "add", "bob")
    bob = up.node().users[1]
    up.terminal.inputs = ["1"]
    code, out = run_user(up, "rm", "alice")
    assert code == 0, out
    assert names(up) == ["bob"] and "alice@jp-1" not in clients(up) and clients(up)["bob@jp-1"] == bob.uuid
    assert clients(up)["jp-1@cnsr"] == up.node().xray.uuid


def test_taking_back_is_confirmed_and_cancelled_by_default(up):
    run_user(up, "add", "alice")
    up.terminal.inputs = [""]
    start = len(up.server.log)
    code, out = run_user(up, "rm", "alice")
    assert code == 0 and "已取消" in out and names(up) == ["alice"] and up.server.log[start:] == []


def test_taking_back_someone_unknown_says_so(up):
    code, out = run_user(up, "rm", "alice")
    assert code == 1 and "没有名为 alice 的用户" in out


def test_the_record_stays_until_the_node_has_let_the_user_go(up):
    run_user(up, "add", "alice")
    up.server.apply_outcome = None
    up.terminal.inputs = ["1"]
    assert run_user(up, "rm", "alice")[0] == 1
    assert names(up) == ["alice"]
    up.server.apply_outcome = "ok"
    up.terminal.inputs = ["1"]
    assert run_user(up, "rm", "alice")[0] == 0
    assert names(up) == [] and "alice@jp-1" not in clients(up) and XRAY_MARKER not in up.server.files


def test_a_failed_handshake_leaves_the_user_where_they_were(up):
    run_user(up, "add", "alice")
    before = clients(up)
    up.server.apply_outcome = "rolled-back handshake"
    up.terminal.inputs = ["1"]
    assert run_user(up, "rm", "alice")[0] == 1
    assert clients(up) == before and names(up) == ["alice"]


# ---- refusals ----------------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["add", "rm"])
def test_an_unknown_server_is_refused(up, action):
    code, out = run_user(up, action, "alice", alias="jp-9")
    assert code == 1 and "没有名为 jp-9 的服务器" in out


def test_a_server_without_an_xray_node_is_refused(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo", features=["harden"]) == 0
    code, out = run_user(fake_deps, "add", "alice")
    assert code == 1 and "没有可以分享的 Xray 节点" in out


def test_a_users_uuid_is_masked_in_the_log(up, tmp_path):
    with runlog.started(tmp_path, "user", "jp-1", ["user", "add", "jp-1", "alice"]) as run:
        run_user(up, "add", "alice")
    (alice,) = up.node().users
    assert alice.uuid in up.terminal.screen and alice.uuid not in run.path.read_text(encoding="utf-8")


def refuse_test(fakes, monkeypatch) -> None:
    original = fakes.server.command

    def command(words):
        if words[:3] == ["docker", "run", "--rm"] and "-test" in words:
            raise CnsrError("Failed to start")
        return original(words)

    monkeypatch.setattr(fakes.server, "command", command)
