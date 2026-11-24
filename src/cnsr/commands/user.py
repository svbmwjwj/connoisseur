"""``cnsr user``: share an Xray node with someone (``add``), take that back (``rm``), or give the owner a
new UUID (``reset``)."""

from __future__ import annotations

from argparse import Namespace

from cnsr import features, localconf
from cnsr.cloudflare.control import find_control_plane
from cnsr.commands import sharing
from cnsr.commands.add_keys import choose_login, pub_file
from cnsr.commands.token_hint import saved_token_hint
from cnsr.deploy import users
from cnsr.deploy.context import AddRequest, DeployContext, Deps, default_deps
from cnsr.errors import CnsrError
from cnsr.naming import validate_user
from cnsr.state import Inventory

CONFIRM_OPTIONS = ["收回", "取消"]
RESET_OPTIONS = ["更换", "取消"]


def run(ns: Namespace, deps: Deps | None = None) -> int:
    """Add or take back ``ns.name`` on ``ns.alias``, or reset its owner; 0 on success, 1 after an error,
    printed here."""
    deps = deps or default_deps()
    try:
        with saved_token_hint(deps.conf_path):
            if ns.action == "reset":
                reset(deps, ns.alias)
            else:
                (add if ns.action == "add" else remove)(deps, ns.alias, ns.name)
    except CnsrError as exc:
        deps.ui.error(str(exc))
        return 1
    return 0


def add(deps: Deps, alias: str, name: str) -> None:
    """Give ``name`` a client of their own on the node and print what to send them."""
    if (error := validate_user(name)) is not None:
        raise CnsrError(error)
    ctx = _context(deps, alias)
    _login(ctx)
    deps.ui.info(f"在 {alias} 上添加用户 {name}（会重启 Xray，所有人断开几秒）。")
    user = users.add_user(ctx, name)
    deps.ui.info("")
    sharing.show_added(deps.ui, ctx.node, user)


def remove(deps: Deps, alias: str, name: str) -> None:
    """Take ``name``'s client off the node, after a confirmation."""
    ctx = _context(deps, alias)
    if all(user.name != name for user in ctx.node.users):
        raise CnsrError(f"{alias} 上没有名为 {name} 的用户。")
    if deps.ui.choose(f"收回 {alias} 上用户 {name} 的使用权？（会重启 Xray，所有人断开几秒）", CONFIRM_OPTIONS, default=1) != 0:
        deps.ui.info("已取消，没有改动。")
        return
    _login(ctx)
    users.remove_user(ctx, name)
    deps.ui.info(f"已收回：用户 {name} 不能再用 {alias}，其他人不受影响。")


def reset(deps: Deps, alias: str) -> None:
    """Give the owner a new UUID, after a confirmation; the old one works until it is taken back."""
    ui = deps.ui
    ctx = _context(deps, alias)
    if ui.choose(f"更换 {alias} 的主用户（订阅里的那个）？旧的先保留（会重启 Xray，所有人断开几秒）", RESET_OPTIONS, default=1) != 0:
        ui.info("已取消，没有改动。")
        return
    _login(ctx)
    old = users.reset_owner(ctx)
    ui.info(f"已更换：订阅约一分钟后是新的主用户，旧的保留为用户 {old.name}，仍然可用。")
    ui.info(f"先在你的所有设备上更新订阅，再运行 cnsr user rm {alias} {old.name} 收回旧的；拿着旧链接的人到那时才断开。")
    ui.info("没更新订阅的设备到那时也会断开，圈X 可能因此误报 SNI 失效、触发换 SNI。")


def _context(deps: Deps, alias: str) -> DeployContext:
    """What the change works with; nothing is created in Cloudflare and the node is not contacted."""
    missing = f"没有名为 {alias} 的服务器"
    values = localconf.load(deps.conf_path)
    token, zone = values.get("CLOUDFLARE_API_TOKEN"), values.get("CLOUDFLARE_ZONE")
    if not (token and zone):
        raise CnsrError(f"{missing}（本机还没有 Cloudflare 设置）。")
    cf = deps.make_cf(token)
    found = find_control_plane(cf, zone)
    if found is None:
        raise CnsrError(f"{missing}（这个 Cloudflare 账号里还没有控制端）。")
    kv, meta, zone_id = found
    inventory = Inventory(kv)
    node = inventory.get(alias)
    if node is None:
        raise CnsrError(f"{missing}。")
    sharing.check(node)
    ip = node.ipv4 if node.source == "vps" else None
    req = AddRequest(alias, node.source, node.region, ip, node.ssh.user, node.ssh.port)
    return DeployContext(
        req, deps, node, inventory, cf, zone_id, zone, meta, None, None, (),
        features=features.installed(node), in_use=True, deployed=True,
    )  # fmt: skip


def _login(ctx: DeployContext) -> None:
    """Pick the node's key as ``cnsr up`` does, so that ssh is pointed at it."""
    ctx.agent, ctx.key, name = choose_login(ctx.deps, ctx.node.alias, ctx.node.ssh.key_name)
    pub_file(ctx.deps, ctx.key, name)
