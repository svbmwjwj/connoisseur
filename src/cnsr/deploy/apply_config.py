"""Giving an Xray that may be in use another config.

The restart, the handshake check and the way back to the old config run on the node by themselves
(apply-config.sh, under systemd): this computer may reach the node through the node's own Xray,
whose restart then cuts the connection. cnsr connects again and reads what came of it.
"""

from __future__ import annotations

from cnsr.deploy.context import DeployContext
from cnsr.deploy.steps_rotate import BIN_DIR
from cnsr.errors import CnsrError
from cnsr.server.xray import NODE_DIR, VERIFY_ENV_PATH, XRAY_IMAGE, verify_env
from cnsr.ssh.remote import Remote, SshError, _read_asset
from cnsr.state import XrayInfo
from cnsr.waiting import Deadline

XRAY_DIR = f"{NODE_DIR}/xray"
CONF_DIR = f"{XRAY_DIR}/conf"
# Exists from just before a changed config moves into place until Xray has been restarted.
RESTART_MARKER = f"{XRAY_DIR}/.restart-pending"
CONTAINER_CONF_DIR = "/usr/local/etc/xray"  # where compose.yml mounts CONF_DIR
# Xray tells a config file's format by its extension, so the staged copy must end in .json.
STAGED_NAME = "config.new.json"
# The config test of a new image pulls it.
PULL_TIMEOUT = 300

# What apply-config.sh needs on the node, itself included.
SCRIPTS = ("apply-config.sh", "verify-reality.sh")
LAUNCH = ["systemd-run", "--quiet", "--collect", "--unit=cnsr-apply-config", "bash", f"{BIN_DIR}/apply-config.sh"]
KEEP_STOPPED = "keep-stopped"
RESULT_PATH = f"{NODE_DIR}/apply-result"
# The restart, a handshake check with its own waits, and perhaps the same restart back.
RESULT_SECONDS = 180
RESULT_INTERVAL_SECONDS = 3
_READ_RESULT = 'cat "$1" 2>/dev/null || true'
_WHY = {"staged": "没能换上新配置", "restart": "重启 Xray 失败", "handshake": "REALITY 握手验证没有通过"}


class Refused(CnsrError):
    """The node runs the config it had before: the change did not take."""


def apply_config(ctx: DeployContext, config: str, info: XrayInfo, *, keep_stopped: bool = False) -> None:
    """Run Xray with ``config`` (and the compose.yml there), or leave it with the old one and raise ``Refused``.

    apply-config.sh starts the SNI rotation service in the end, unless ``keep_stopped``. Nothing
    heard from the node is another error: the restart it may still owe is marked
    (``RESTART_MARKER``), so running the same command again makes up for it.
    """
    remote = ctx.remote()
    try:
        stage_config(remote, config)
    except SshError:
        raise
    except CnsrError as exc:
        raise Refused(str(exc)) from exc
    remote.run(["install", "-d", "-m", "755", BIN_DIR], sudo=True)
    for name in SCRIPTS:
        remote.put_text(f"{BIN_DIR}/{name}", _read_asset(name), "755")
    put_verify_env(remote, info)
    run_id = f"{ctx.deps.rng.getrandbits(64):016x}"
    try:
        remote.run([*LAUNCH, run_id, *([KEEP_STOPPED] if keep_stopped else [])], sudo=True)
    except SshError:
        pass  # the restart may have cut the connection: what came of it says so
    outcome, _, why = _outcome(ctx, run_id).partition(" ")
    if outcome == "failed":
        raise CnsrError(f"新的 Xray 配置没有成功，恢复旧配置后 Xray 也没能重启。请登录节点查看，或运行 cnsr up {ctx.node.alias}。")
    if outcome != "ok":
        raise Refused(f"{_WHY.get(why, '新配置没有成功')}，已恢复旧配置。")


def stage_config(remote: Remote, config: str) -> str:
    """Upload ``config`` beside the one in use and have ``xray run -test`` accept it; its path."""
    staged = f"{CONF_DIR}/{STAGED_NAME}"
    remote.put_text(staged, config, "644")
    mount = f"{CONF_DIR}:{CONTAINER_CONF_DIR}:ro"
    test = ["docker", "run", "--rm", "-v", mount, XRAY_IMAGE, "run", "-test", "-c", f"{CONTAINER_CONF_DIR}/{STAGED_NAME}"]
    try:
        remote.run(test, sudo=True, timeout=PULL_TIMEOUT)  # a new XRAY_IMAGE is pulled here
    except SshError:
        raise
    except CnsrError as exc:
        raise CnsrError(f"新的 Xray 配置没有通过 xray -test，节点上的配置保持不变：{exc}") from exc
    return staged


def put_verify_env(remote: Remote, info: XrayInfo) -> None:
    """Write what verify-reality.sh needs to complete a REALITY handshake as the owner."""
    # The values go in a root-only file, never on the command line, where sudo would log them.
    remote.put_text(VERIFY_ENV_PATH, verify_env(info.uuid, info.public_key, info.short_id, info.sni), "600")


def _outcome(ctx: DeployContext, run_id: str) -> str:
    """What apply-config.sh reported for ``run_id``, connecting again as often as it takes."""
    deps = ctx.deps
    deadline = Deadline(RESULT_SECONDS, deps.clock)
    while True:
        try:
            found, _, outcome = ctx.remote().run(["sh", "-c", _READ_RESULT, "sh", RESULT_PATH], sudo=True).strip().partition(" ")
            if found == run_id:
                ctx.remote().run(["rm", "-f", RESULT_PATH], sudo=True)
                return outcome
        except SshError as exc:
            deps.ui.detail(f"暂时连不上节点，稍后再试：{exc}")
        if deadline.passed():
            raise CnsrError("没有等到节点报告结果。等一会儿重跑同一条命令即可继续。")
        deps.sleep(deadline.step(RESULT_INTERVAL_SECONDS))
