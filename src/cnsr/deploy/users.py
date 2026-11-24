"""The people an Xray node is shared with, on a node already deployed: adding one, taking one back, and
giving the owner a new UUID.

Only the clients of the config on the node change. The SNI rotation service, which rewrites the
same file, is stopped meanwhile, and the node's record is read again once it is: the service may
have put a new SNI in it through the control plane. The SNI itself is read from the config.

Each order of steps lets the same command finish what a dropped connection cut short: a user is
recorded before the node learns of them, and forgotten only once the node has. A new owner's UUID
keeps the old one as a user, so the owner's devices, and perhaps this very connection, go on working.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import date

from cnsr import runlog
from cnsr.deploy.apply_config import RESTART_MARKER, Refused, apply_config
from cnsr.deploy.context import DeployContext
from cnsr.deploy.steps_rotate import SERVICE, SWITCH_MARK, UNIT_PATH, resume_rotation, stop_rotation
from cnsr.errors import CnsrError
from cnsr.qx import node_line
from cnsr.server.xray import (
    CONFIG_PATH,
    IDENTITY_ENV_PATH,
    derive_public_key,
    identity_env,
    new_identity,
    read_identity,
    with_owner,
    with_users,
)
from cnsr.state import XrayInfo, XrayUser


def add_user(ctx: DeployContext, name: str) -> XrayUser:
    """Give ``name`` a client on the node; one recorded already keeps its UUID."""
    with _rotation_stopped(ctx):
        current, _ = _refresh(ctx)
        _sync_identity(ctx)
        node = ctx.node
        known = next((user for user in node.users if user.name == name), None)
        user = known or XrayUser(name, new_identity(ctx.deps.rng)[0])
        if known is None:
            node.users.append(user)
        _save(ctx)
        try:
            _apply(ctx, current, node.users)
        except Refused:
            if known is None:
                node.users.remove(user)
                _save(ctx)
            raise
    return user


def remove_user(ctx: DeployContext, name: str) -> None:
    """Take ``name``'s client off the node, then the record."""
    with _rotation_stopped(ctx):
        current, _ = _refresh(ctx)
        _sync_identity(ctx)
        left = [user for user in ctx.node.users if user.name != name]
        _apply(ctx, current, left)
        ctx.node.users = left
        _save(ctx)


def reset_owner(ctx: DeployContext) -> XrayUser:
    """Give the owner a new UUID and keep the old one as a user, which is returned.

    A reset cut short is finished, not started again: the record, which still has the old UUID
    then, and the node's config tell how far it got.
    """
    with _rotation_stopped(ctx):
        current, recorded = _refresh(ctx)
        node = ctx.node
        in_use = node.xray.uuid
        done = next((user for user in node.users if user.uuid == recorded != in_use), None)
        if done is not None:  # the node has the new UUID already
            _apply(ctx, current, node.users)
            old = done
        else:
            old = next((user for user in node.users if user.uuid == in_use), None)
            if old is None:
                old = XrayUser(_old_name(node.users), in_use)
                node.users.append(old)
            _save(ctx)
            info = replace(node.xray, uuid=new_identity(ctx.deps.rng)[0])
            config = with_users(with_owner(current, info.uuid), node.alias, node.users)
            try:
                apply_config(ctx, config, info)
            except Refused:
                node.users.remove(old)
                _save(ctx)
                raise
            node.xray = info
            node.line = node_line(node.domain, info, node.alias)
        _save(ctx)
        if _sync_identity(ctx) and ctx.exists(UNIT_PATH):  # the service reads it when it starts
            ctx.remote().run(["systemctl", "restart", SERVICE], sudo=True)
    return old


def _save(ctx: DeployContext) -> None:
    """Store the users, then the record with the identity the node has."""
    ctx.inventory.put_users(ctx.node.alias, ctx.node.users)
    ctx.inventory.put(ctx.node)


def _old_name(users: list[XrayUser]) -> str:
    """A name for the old UUID that no user has."""
    base, taken = f"old-{date.today():%Y%m%d}", {user.name for user in users}
    names = [base, *(f"{base}-{number}" for number in range(2, len(users) + 3))]
    return next(name for name in names if name not in taken)


def _sync_identity(ctx: DeployContext) -> bool:
    """Have the SNI rotation service check its handshakes as the owner; whether that changed anything."""
    node, x = ctx.node, ctx.node.xray
    wanted = identity_env(node.alias, x.uuid, x.public_key, x.short_id)
    if ctx.read(IDENTITY_ENV_PATH) == wanted:
        return False
    ctx.remote().put_text(IDENTITY_ENV_PATH, wanted, "600")
    return True


@contextmanager
def _rotation_stopped(ctx: DeployContext) -> Iterator[None]:
    try:
        stop_rotation(ctx)
        if ctx.exists(SWITCH_MARK):  # starting the service would put the config from before it back
            raise CnsrError(f"节点上有一次换 SNI 没有完成。先运行 cnsr up {ctx.node.alias} 恢复，再重试。")
        yield
    finally:
        resume_rotation(ctx, "换 SNI 服务已重新启动。")


def _refresh(ctx: DeployContext) -> tuple[str, str]:
    """The node's config, and the owner's UUID in the record; ``ctx.node`` becomes that record as it
    is now, with the identity and SNI of the config."""
    current = ctx.read(CONFIG_PATH)
    if current is None:
        raise CnsrError(f"节点上没有 Xray 配置。先运行 cnsr up {ctx.node.alias} 恢复，再重试。")
    found = read_identity(current)
    runlog.secret(found["private_key"])
    node = ctx.inventory.get(ctx.node.alias)
    if node is None:
        raise CnsrError(f"没有名为 {ctx.node.alias} 的服务器。")
    recorded = node.xray.uuid
    public_key = derive_public_key(found["private_key"])
    node.xray = XrayInfo(found["uuid"], public_key, found["short_id"], found["sni"], found["dest_ip"])
    node.line = node_line(node.domain, node.xray, node.alias)
    ctx.node = node
    return current, recorded


def _apply(ctx: DeployContext, current: str, users: list[XrayUser]) -> None:
    """Run Xray with ``users``; nothing happens when it does already."""
    config = with_users(current, ctx.node.alias, users)
    if json.loads(config) == json.loads(current) and not ctx.exists(RESTART_MARKER):
        return
    apply_config(ctx, config, ctx.node.xray)
