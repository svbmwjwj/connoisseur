"""What ``cnsr up`` can put on a server: layers, each built on every layer before it.

The base hardening comes first, then Docker, then the Xray node; a layer needs all of those
before it. A server's record lists the features a finished run left on it (``Node.features``).
"""

from __future__ import annotations

from cnsr.server import xray
from cnsr.state import Node

HARDEN = "harden"
DOCKER = "docker"
XRAY = "xray"
BASE = HARDEN
EXTENSIONS = (DOCKER, XRAY)
ALL = (BASE, *EXTENSIONS)
LABELS = {HARDEN: "基础加固", DOCKER: "Docker（Docker Engine 和 compose 插件）", XRAY: "Xray 节点（REALITY，SNI 失效时自动更换）"}
# What each feature is called where another names it.
NAMES = {HARDEN: "基础加固", DOCKER: "Docker", XRAY: "Xray 节点"}
# What each feature shows as in ``cnsr list``.
SHORT_LABELS = {HARDEN: "仅加固", DOCKER: "Docker", XRAY: "Xray 节点"}
APP_PORTS = {XRAY: xray.PORTS}


def installed(node: Node | None) -> list[str]:
    """The features a finished run left on ``node``, in ``ALL`` order.

    A record from before features were recorded counts as every feature when it has a client
    line; one from before Docker was a feature of its own has Docker when it has Xray.
    """
    if node is None:
        return []
    if node.features:
        recorded = set(node.features) | ({DOCKER} if XRAY in node.features else set())
        return [feature for feature in ALL if feature in recorded]
    return list(ALL) if node.line is not None else []


def below(feature: str) -> tuple[str, ...]:
    """The features ``feature`` is built on."""
    return ALL[: ALL.index(feature)]


def problem(chosen: list[str]) -> str | None:
    """Why ``chosen`` cannot be deployed, or None when it can."""
    if not chosen:
        return f"至少选择一项；{LABELS[BASE]}是其他功能的基础。"
    for feature in reversed(ALL):
        if feature in chosen:
            missing = [need for need in below(feature) if need not in chosen]
            if missing:
                return f"选了{_after_cjk(NAMES[feature])}就必须同时选择{_after_cjk(NAMES[missing[0]])}。"
    return None


def app_ports(chosen: list[str]) -> tuple[tuple[int, str], ...]:
    """The ``(port, protocol)`` pairs the chosen features listen on, without repeats."""
    ports: list[tuple[int, str]] = []
    for feature in chosen:
        ports += [port for port in APP_PORTS.get(feature, ()) if port not in ports]
    return tuple(ports)


def summary(chosen: list[str]) -> str:
    """How ``cnsr list`` names what a server has: its top layer."""
    return SHORT_LABELS[[feature for feature in ALL if feature in chosen][-1]]


def _after_cjk(name: str) -> str:
    """``name`` as it follows Chinese text: a Latin first letter gets a space in front."""
    return f" {name}" if name[0].isascii() else name
