"""How one node is added by hand: the owner's own lines, and one pair for each person it is shared with."""

from __future__ import annotations

from rich.text import Text

from cnsr import features
from cnsr.errors import CnsrError
from cnsr.qx import share_link, user_line
from cnsr.state import Node, XrayUser
from cnsr.ui import Ui


def shareable(node: Node) -> bool:
    return features.XRAY in features.installed(node) and node.line is not None


def users(node: Node) -> list[XrayUser]:
    """The people the node is shared with. A reset of the owner that never took leaves the owner's
    UUID recorded as a user's too: that one is nobody's to share."""
    return [user for user in node.users if user.uuid != node.xray.uuid]


def check(node: Node) -> None:
    """Raise when ``node`` has nothing to share, saying why."""
    if shareable(node):
        return
    if features.XRAY in features.installed(node):
        raise CnsrError(f"{node.alias} 没有可用的配置行；重跑 cnsr up {node.alias} 后再试。")
    raise CnsrError(f"{node.alias} 没有可以分享的 Xray 节点。")


def show_node(ui: Ui, node: Node) -> None:
    """The owner's lines and those of every user, with nothing of the subscription."""
    check(node)
    ui.styled(Text.assemble((node.alias, "bold"), "  的添加方式，不经过订阅"))
    ui.info("")
    _lines(ui, "你自己的（和订阅里的是同一份，不要分享）", node.line)
    for user in users(node):
        show_user(ui, node, user)
    if not users(node):
        ui.styled(Text(f"分享给别人：cnsr user add {node.alias} <名字>，每个人一份，可以单独收回。", style="dim"))
    _note(ui, node)


def show_added(ui: Ui, node: Node, user: XrayUser) -> None:
    """What to send a user just added."""
    show_user(ui, node, user)
    _note(ui, node)


def show_user(ui: Ui, node: Node, user: XrayUser) -> None:
    _lines(ui, f"用户 {user.name}", user_line(node, user))


def _lines(ui: Ui, title: str, line: str) -> None:
    ui.styled(Text(title, style="bold"))
    ui.styled(Text("圈X 加到配置的 [server_local]：", style="dim"))
    ui.styled(Text(line, style="cyan", no_wrap=True))
    if (link := share_link(line)) is not None:
        ui.styled(Text("v2rayN 等软件复制后从剪贴板导入：", style="dim"))
        ui.styled(Text(link, style="cyan", no_wrap=True))
    ui.info("")


def _note(ui: Ui, node: Node) -> None:
    ui.styled(Text(f"换 SNI 后要重新发：手动添加的节点不会自动更新，届时用 cnsr list {node.alias} 取新的。", style="dim"))
