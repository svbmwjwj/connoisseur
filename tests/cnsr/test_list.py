"""Tests for ``cnsr list``: the nodes, the Quantumult X sections and the v2rayN address, changing nothing."""

from __future__ import annotations

import argparse
import io
import json
import re

from rich.cells import cell_len
from rich.console import Console

from deploy_fakes import run_up

from cnsr import runlog
from cnsr.commands import listing
from cnsr.progress import LiveStages
from cnsr.qx import check_url, share_link, snippet_url, user_line, v2rayn_url
from cnsr.state import ControlMeta, XrayUser
from cnsr.ui import Ui


def run_list(fakes, alias: str | None = None, menu: bool = False) -> tuple[int, str]:
    fakes.terminal.clear()
    code = listing.run(argparse.Namespace(command="list", alias=alias, menu=menu), fakes.deps)
    return code, fakes.terminal.text


def test_list_shows_the_nodes_and_both_subscriptions(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    meta = ControlMeta.from_json(fake_deps.kv()["meta:control"])
    node = fake_deps.node()
    before = len(fake_deps.cloudflare.calls())

    code, out = run_list(fake_deps)

    assert code == 0
    assert "jp-1" in out and node.domain in out and node.ipv4 in out and node.xray.sni in out
    assert snippet_url(meta) in out and "[server_remote]" not in out
    assert v2rayn_url(meta) in out
    assert {method for method, _ in fake_deps.cloudflare.calls()[before:]} == {"GET"}


def test_list_marks_a_node_that_is_not_in_the_subscription(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    node = fake_deps.node()
    node.line = None
    fake_deps.store(node)
    _, out = run_list(fake_deps)
    assert "不在订阅里" in out


def test_list_without_a_control_plane_creates_nothing(fake_deps):
    code, out = run_list(fake_deps)
    assert code == 1
    assert "还没有服务器" in out
    assert {method for method, _ in fake_deps.cloudflare.calls()} == {"GET"}


def test_list_without_cloudflare_settings_says_there_are_no_nodes(fake_deps):
    fake_deps.deps.conf_path.unlink()
    code, out = run_list(fake_deps)
    assert code == 1
    assert "还没有服务器" in out
    assert fake_deps.calls["make_cf"] == []


def test_list_names_what_each_server_has(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    hardened = fake_deps.node()
    hardened.alias, hardened.features, hardened.xray, hardened.line = "jp-2", ["harden"], None, None
    fake_deps.store(hardened)
    fake_deps.kv()["index:nodes"] = json.dumps(["jp-1", "jp-2"])
    _, out = run_list(fake_deps)
    assert "服务器  2 台" in out
    assert re.search(r"jp-1 +● Xray 节点 ", out) and re.search(r"jp-2 +○ 仅加固 ", out)


def test_list_without_an_xray_node_shows_no_subscription(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo", features=["harden"]) == 0
    meta = ControlMeta.from_json(fake_deps.kv()["meta:control"])
    _, out = run_list(fake_deps)
    assert re.search(r"jp-1 +○ 仅加固 ", out)
    assert v2rayn_url(meta) not in out and "圈X" not in out


def test_list_aligns_the_columns(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    hardened = fake_deps.node()
    hardened.alias, hardened.features, hardened.xray, hardened.line = "jp-22", ["harden"], None, None
    fake_deps.store(hardened)
    fake_deps.kv()["index:nodes"] = json.dumps(["jp-1", "jp-22"])
    _, out = run_list(fake_deps)
    lines = out.splitlines()
    first = next(number for number, line in enumerate(lines) if line.startswith("服务器  2 台"))
    rows = [lines[first + 1], *lines[first + 3 :][:2]]  # the header, then the servers below its rule
    assert len(rows) == 3 and rows[0].split()[:2] == ["别名", "功能"]
    starts = {cell_len(row[: row.index(word)]) for row, word in zip(rows, ["来源", "AWS", "AWS"])}
    assert len(starts) == 1


def test_list_in_a_terminal_colours_the_table_and_never_breaks_an_address(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    meta = ControlMeta.from_json(fake_deps.kv()["meta:control"])
    screen = io.StringIO()
    console = Console(file=screen, force_terminal=True, width=60, color_system="standard")
    fake_deps.deps.ui = Ui(out=screen, interactive=False, display=LiveStages(console, auto_refresh=False))
    assert listing.run(argparse.Namespace(command="list", alias=None, menu=False), fake_deps.deps) == 0
    out = screen.getvalue()
    assert "\x1b[32m● Xray 节点" in out  # green
    plain = re.sub(r"\x1b\[[0-9;]*m", "", out)
    for url in (snippet_url(meta), v2rayn_url(meta)):
        assert any(line.endswith(url) for line in plain.splitlines())


def test_list_shows_the_quantumult_x_check_tasks_ready_to_paste(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    meta = ControlMeta.from_json(fake_deps.kv()["meta:control"])
    _, out = run_list(fake_deps)
    assert "圈X 检测" in out and "[task_local]" in out
    assert f"* * * * * {check_url(meta)}, tag=cnsr 节点检测, enabled=true" in out
    ui_url = check_url(meta).replace("check.js", "check-ui.js")
    assert f"event-interaction {ui_url}, tag=cnsr 检测, enabled=true" in out
    assert "长按节点手动检测" in out


def test_list_shows_aws_traffic_in_and_out_with_a_note_on_the_shared_allowance(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    fake_deps.lightsail.used = {"jp-1": (300 * 1024**3, 1024**4)}
    _, out = run_list(fake_deps)
    row = next(line for line in out.splitlines() if line.strip().startswith("jp-1 "))
    assert "0.3 / 1 TB" in row
    assert "AWS 流量为本月入站加出站" in out and "合用额度" in out


def test_aws_traffic_that_cannot_be_read_is_a_dash(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    fake_deps.lightsail.instances.clear()  # gone: no traffic to read
    _, out = run_list(fake_deps)
    row = next(line for line in out.splitlines() if line.strip().startswith("jp-1 "))
    assert " - " in row or row.rstrip().endswith("-")


# ---- one node, to add by hand -------------------------------------------------------------


def test_list_with_an_alias_shows_how_to_add_that_node_alone(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    meta = ControlMeta.from_json(fake_deps.kv()["meta:control"])
    node = fake_deps.node()
    before = len(fake_deps.cloudflare.calls())

    code, out = run_list(fake_deps, "jp-1")

    assert code == 0
    assert node.line in out and "[server_local]" in out
    assert share_link(node.line) in out
    assert meta.client_token not in out and meta.host not in out  # nothing of the subscription
    assert "换 SNI 后要重新发" in out
    assert {method for method, _ in fake_deps.cloudflare.calls()[before:]} == {"GET"}


def test_list_with_an_unknown_alias_says_so(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    code, out = run_list(fake_deps, "jp-9")
    assert code == 1 and "没有名为 jp-9 的服务器" in out


def test_list_with_an_alias_that_has_no_xray_node_says_why(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo", features=["harden"]) == 0
    code, out = run_list(fake_deps, "jp-1")
    assert code == 1 and "jp-1 没有可以分享的 Xray 节点" in out and "vless" not in out


def test_list_with_an_alias_whose_line_is_missing_says_how_to_get_it(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    node = fake_deps.node()
    node.line = None
    fake_deps.store(node)
    code, out = run_list(fake_deps, "jp-1")
    assert code == 1 and "cnsr up jp-1" in out and "vless" not in out


def test_list_with_an_alias_shows_each_user_apart_from_the_owner(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    node = fake_deps.node()
    node.users = [XrayUser("alice", "22222222-2222-4222-8222-222222222222")]
    fake_deps.store(node)
    code, out = run_list(fake_deps, "jp-1")
    assert code == 0 and "你自己的" in out and "不要分享" in out and "用户 alice" in out
    line = user_line(node, node.users[0])
    assert out.index(node.line) < out.index("用户 alice") < out.index(line) and share_link(line) in out


def test_the_menu_shows_how_to_add_one_node(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    line = fake_deps.node().line
    fake_deps.terminal.inputs = ["2", "1"]
    code, out = run_list(fake_deps, menu=True)
    assert code == 0 and line in out


def test_the_menu_can_be_left_without_picking_a_node(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    line = fake_deps.node().line
    fake_deps.terminal.inputs = ["1"]
    code, out = run_list(fake_deps, menu=True)
    assert code == 0 and line not in out


def test_the_menu_adds_a_user(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    fake_deps.terminal.inputs = ["2", "2", "Alice", "alice"]  # a bad name is asked again
    code, out = run_list(fake_deps, menu=True)
    assert code == 0, out
    (alice,) = fake_deps.node().users
    assert alice.name == "alice" and user_line(fake_deps.node(), alice) in out


def test_the_menu_takes_a_user_back(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    fake_deps.terminal.inputs = ["2", "2", "alice"]
    run_list(fake_deps, menu=True)
    fake_deps.terminal.inputs = ["2", "3", "1", "1"]  # the node, take back, alice, confirm
    code, out = run_list(fake_deps, menu=True)
    assert code == 0 and fake_deps.node().users == [], out


def test_the_menu_resets_the_owner(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    before = fake_deps.node().xray.uuid
    fake_deps.terminal.inputs = ["2", "3", "1"]  # the node, reset (nobody to take back), confirm
    code, out = run_list(fake_deps, menu=True)
    assert code == 0 and fake_deps.node().xray.uuid != before, out


def test_the_menu_does_not_offer_to_take_back_nobody(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    fake_deps.terminal.inputs = ["2", "1"]
    _, out = run_list(fake_deps, menu=True)
    assert "收回用户" not in out


def test_the_menu_asks_nothing_without_a_node_to_share(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo", features=["harden"]) == 0
    fake_deps.terminal.inputs = []
    code, out = run_list(fake_deps, menu=True)
    assert code == 0 and "管理" not in out


def test_the_command_itself_asks_nothing(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    fake_deps.terminal.inputs = []
    assert run_list(fake_deps)[0] == 0
    assert fake_deps.terminal.prompts == []


def test_a_shared_node_is_masked_in_the_log(fake_deps, tmp_path):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    uuid = fake_deps.node().xray.uuid
    with runlog.started(tmp_path, "list", "jp-1", ["list", "jp-1"]) as run:
        _, out = run_list(fake_deps, "jp-1")
    assert uuid in fake_deps.terminal.screen and uuid not in run.path.read_text(encoding="utf-8")
