"""``cnsr up`` on a node in use: a restart of Xray may cut the very connection it is asked over."""

from __future__ import annotations

import pytest
from deploy_fakes import run_up

from cnsr.deploy import apply_config
from cnsr.errors import CnsrError
from cnsr.server.xray import COMPOSE_PATH, CONFIG_PATH

LAUNCH = "systemd-run"
RESTART = f"docker compose -f {COMPOSE_PATH} restart"


def launched(fakes, start: int = 0) -> list[str]:
    return [what for what in fakes.server.what()[start:] if what.startswith(LAUNCH)]


@pytest.fixture
def stale(fake_deps):
    """A node whose config is of an older template."""
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert launched(fake_deps) == []  # a first deployment restarts nothing
    fake_deps.server.files[CONFIG_PATH] = fake_deps.server.files[CONFIG_PATH].replace('"loglevel"', '"logLevel"')
    return fake_deps


def test_a_changed_config_is_taken_up_by_the_node_itself(stale):
    start = len(stale.server.log)
    assert run_up(stale, aws="jp-tokyo") == 0
    (launch,) = launched(stale, start)
    assert launch.endswith(" keep-stopped")
    assert '"loglevel"' in stale.server.files[CONFIG_PATH] and stale.server.service == "active"


def test_the_restart_may_cut_the_connection(stale):
    stale.server.restart_cuts = 4
    assert run_up(stale, aws="jp-tokyo") == 0
    assert '"loglevel"' in stale.server.files[CONFIG_PATH] and stale.server.service == "active"
    assert apply_config.RESULT_PATH not in stale.server.files


def test_the_rotation_service_stays_stopped_until_step_nine(stale, monkeypatch):
    seen = []
    original = stale.server._apply_config

    def spy(command):
        text = original(command)
        seen.append(stale.server.service)
        return text

    monkeypatch.setattr(stale.server, "_apply_config", spy)
    assert run_up(stale, aws="jp-tokyo") == 0
    assert seen == ["inactive"] and stale.server.service == "active"


def test_a_config_that_fails_is_rolled_back_and_the_run_fails(stale):
    before = stale.server.files[CONFIG_PATH]
    stale.server.apply_outcome = "rolled-back handshake"
    assert run_up(stale, aws="jp-tokyo") == 1
    assert stale.server.files[CONFIG_PATH] == before and "已恢复" in stale.terminal.text
    assert stale.server.service == "active"  # the failed run gave the rotation back


def test_a_changed_compose_file_is_taken_up_by_the_node_too(fake_deps):
    """`compose up` recreates the container, which cuts the connection all the same."""
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    fake_deps.server.files[COMPOSE_PATH] += "# older\n"
    fake_deps.server.restart_cuts = 4
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert "# older" not in fake_deps.server.files[COMPOSE_PATH] and len(launched(fake_deps)) == 1


def test_an_unchanged_node_restarts_nothing(fake_deps):
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert launched(fake_deps) == [] and RESTART not in fake_deps.server.what()


def test_a_run_that_heard_nothing_is_made_up_for_by_the_next(stale):
    stale.server.apply_outcome = None
    assert run_up(stale, aws="jp-tokyo") == 1
    stale.server.apply_outcome = "ok"
    start = len(stale.server.log)
    assert run_up(stale, aws="jp-tokyo") == 0
    assert len(launched(stale, start)) == 1 and "/opt/cnsr/xray/.restart-pending" not in stale.server.files


def test_a_new_compose_file_a_run_stopped_after_is_taken_up_by_the_next(fake_deps):
    """The file on the node is the new one by then, so only the marker tells."""
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    fake_deps.server.files[COMPOSE_PATH] += "# older\n"
    fake_deps.server.fail_once["put /opt/cnsr/xray/conf/config.new.json"] = CnsrError("写不进去")
    assert run_up(fake_deps, aws="jp-tokyo") == 1
    assert "# older" not in fake_deps.server.files[COMPOSE_PATH] and launched(fake_deps) == []
    assert run_up(fake_deps, aws="jp-tokyo") == 0
    assert len(launched(fake_deps)) == 1
