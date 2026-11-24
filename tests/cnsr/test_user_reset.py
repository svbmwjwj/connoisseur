"""``cnsr user reset``: a new UUID for the owner, the old one kept as a user until it is taken back."""

from __future__ import annotations

import argparse
import re

import pytest
from deploy_fakes import run_up
from test_users import RESULT, SWITCHING, XRAY_MARKER, clients, names, run_user

from cnsr.commands import user
from cnsr.qx import node_line
from cnsr.server.xray import CONFIG_PATH, IDENTITY_ENV_PATH, read_identity

ROTATE_RESTART = "systemctl restart cnsr-rotate.service"


@pytest.fixture
def up(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    return fake_deps


def reset(fakes, answer: str = "1", alias: str = "jp-1") -> tuple[int, str]:
    fakes.terminal.clear()
    fakes.terminal.inputs = [answer]
    ns = argparse.Namespace(command="user", action="reset", alias=alias, name=None)
    return user.run(ns, fakes.deps), fakes.terminal.text


def owner(fakes) -> str:
    return read_identity(fakes.server.files[CONFIG_PATH])["uuid"]


def test_the_owner_gets_a_new_uuid_and_the_old_one_still_works(up):
    old = owner(up)
    code, out = reset(up)
    assert code == 0, out
    assert owner(up) != old
    (kept,) = up.node().users
    assert kept.uuid == old and re.fullmatch(r"old-\d{8}", kept.name)
    assert list(clients(up)) == ["jp-1@cnsr", f"{kept.name}@jp-1"] and clients(up)[f"{kept.name}@jp-1"] == old
    assert f"cnsr user rm jp-1 {kept.name}" in out


def test_the_subscription_and_the_record_carry_the_new_uuid(up):
    reset(up)
    node = up.node()
    assert node.xray.uuid == owner(up)
    assert node.line == node_line(node.domain, node.xray, "jp-1") and node.xray.uuid in node.line


def test_keys_short_id_and_sni_stay(up):
    before = read_identity(up.server.files[CONFIG_PATH])
    reset(up)
    assert read_identity(up.server.files[CONFIG_PATH]) == {**before, "uuid": owner(up)}


def test_other_users_keep_theirs(up):
    run_user(up, "add", "alice")
    alice = up.node().users[0]
    reset(up)
    assert clients(up)["alice@jp-1"] == alice.uuid and names(up)[0] == "alice" and len(names(up)) == 2


def test_the_rotation_service_checks_with_the_new_uuid(up):
    start = len(up.server.log)
    reset(up)
    assert f"UUID={owner(up)}\n" in up.server.files[IDENTITY_ENV_PATH] and up.server.modes[IDENTITY_ENV_PATH] == "600"
    assert ROTATE_RESTART in up.server.what()[start:] and up.server.service == "active"


def test_taking_the_old_one_back_leaves_only_the_new(up):
    old = owner(up)
    reset(up)
    up.terminal.inputs = ["1"]
    code, _ = run_user(up, "rm", up.node().users[0].name)
    assert code == 0 and names(up) == [] and list(clients(up).values()) == [owner(up)] != [old]


def test_a_rerun_of_up_keeps_both(up):
    reset(up)
    before = clients(up)
    assert run_up(up, aws="jp-tokyo") == 0
    assert clients(up) == before


def test_resetting_twice_keeps_every_old_one_under_its_own_name(up):
    reset(up)
    reset(up)
    assert len(set(names(up))) == 2 and len(clients(up)) == 3


def test_it_is_confirmed_and_cancelled_by_default(up):
    old = owner(up)
    start = len(up.server.log)
    code, out = reset(up, answer="")
    assert code == 0 and "已取消" in out and owner(up) == old and up.server.log[start:] == []


def test_a_handshake_that_fails_leaves_everything_as_it_was(up):
    old, identity, line = owner(up), up.server.files[IDENTITY_ENV_PATH], up.node().line
    up.server.apply_outcome = "rolled-back handshake"
    code, out = reset(up)
    assert code == 1 and "已恢复" in out
    assert owner(up) == old and names(up) == [] and up.node().line == line and up.node().xray.uuid == old
    assert up.server.files[IDENTITY_ENV_PATH] == identity


def test_the_restart_may_cut_the_connection(up):
    up.server.restart_cuts = 4
    code, out = reset(up)
    assert code == 0, out
    assert up.node().xray.uuid == owner(up) and up.server.service == "active" and RESULT not in up.server.files


@pytest.mark.parametrize("applied", [True, False])
def test_a_reset_nothing_was_heard_of_is_finished_and_not_started_again(up, applied):
    old = owner(up)
    before = up.server.files[CONFIG_PATH]
    up.server.apply_outcome = None
    assert reset(up)[0] == 1
    if not applied:  # the node never got as far as the new config
        up.server.files[CONFIG_PATH] = before
        up.server.files.pop(XRAY_MARKER, None)
    up.server.apply_outcome = "ok"
    code, out = reset(up)
    assert code == 0, out
    (kept,) = up.node().users
    assert kept.uuid == old and owner(up) != old and len(clients(up)) == 2
    assert up.node().xray.uuid == owner(up) and f"UUID={owner(up)}\n" in up.server.files[IDENTITY_ENV_PATH]
    assert XRAY_MARKER not in up.server.files


def test_a_run_of_up_after_a_reset_that_never_took_gives_no_client_twice(up):
    """The record names the old UUID as a user already, while it is still the owner's."""
    before = up.server.files[CONFIG_PATH]
    up.server.apply_outcome = None
    reset(up)
    up.server.files[CONFIG_PATH] = before
    up.server.apply_outcome = "ok"
    assert run_up(up, aws="jp-tokyo") == 0
    assert len(clients(up)) == 1


def test_the_identity_file_is_brought_up_to_date_before_the_old_one_goes(up):
    """A reset cut short after the node's restart leaves the service checking with the old UUID."""
    identity = up.server.files[IDENTITY_ENV_PATH]
    reset(up)
    up.server.files[IDENTITY_ENV_PATH] = identity
    up.terminal.inputs = ["1"]
    assert run_user(up, "rm", up.node().users[0].name)[0] == 0
    assert f"UUID={owner(up)}\n" in up.server.files[IDENTITY_ENV_PATH]


def test_a_switch_the_node_never_finished_stops_it(up):
    up.server.files[SWITCHING] = "x\n"
    old = owner(up)
    code, out = reset(up)
    assert code == 1 and "cnsr up jp-1" in out and owner(up) == old and names(up) == []


def test_an_unknown_server_is_refused(up):
    code, out = reset(up, alias="jp-9")
    assert code == 1 and "没有名为 jp-9 的服务器" in out
