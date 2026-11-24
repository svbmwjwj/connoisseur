"""Pipeline steps 5-6: scan the node's neighbourhood from this computer, then let the node choose."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import replace

from cnsr.deploy.context import DeployContext
from cnsr.deploy.steps_rotate import stop_rotation
from cnsr.errors import CnsrError
from cnsr.scan import pool
from cnsr.scan.egress import FAKE_IP_NETWORK, Egress, client_address, is_direct
from cnsr.scan.filters import shortlist
from cnsr.scan.ranges import scan_network, scan_targets
from cnsr.scan.select import Candidate, backups_json, choose, parse_backups, parse_validation, ranked
from cnsr.server.xray import BACKUPS_PATH, CONFIG_PATH, read_identity
from cnsr.ssh.remote import SshError

# Backups are checked again, from the node and from mainland China, right before each use, so
# every candidate that passed is kept. A rerun scans again only when fewer than REFILL_BELOW are left.
MAX_BACKUPS = 30
REFILL_BELOW = 10
UNKNOWN_EGRESS_OPTIONS = ["确认是直连，继续扫描", "停止"]
# Run on the node: prints "<domain> <address>" for every address each argument resolves to.
RESOLVE = 'for d in "$@"; do getent ahostsv4 "$d" | while read -r ip _; do echo "$d $ip"; done; done; true'
# The same for addresses: prints "<address> <name>" for each one with a name in reverse DNS.
REVERSE = 'for ip in "$@"; do getent hosts "$ip" | while read -r _ name _; do echo "$ip $name"; done; done; true'
TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"
_COUNTRY = re.compile(r"^loc=([A-Z]{2})$", re.MULTILINE)
PROXIED_OPTIONS = ["已关闭代理，重新检查", "停止"]


def step_scan(ctx: DeployContext) -> None:
    """Find SNI candidates around the node; skipped when Xray runs and enough backups are left.

    The scan must leave this computer directly, never through a proxy. A first deployment
    waits until it does (see ``require_direct``); a node that already runs Xray only misses
    the refill of its backups. A node whose deployment never finished counts as a first one:
    its SNI may be what stopped it, so ``step_sni`` checks it again against a fresh scan.
    """
    ui = ctx.deps.ui
    ctx.hits = None
    configured = ctx.deployed and ctx.exists(CONFIG_PATH)
    left = len(_backups_on_node(ctx)) if configured else 0
    if configured and left >= REFILL_BELOW:
        ui.detail(f"节点已有 Xray 配置，还有 {left} 个备选 SNI（不少于 {REFILL_BELOW} 个），跳过扫描。")
        return
    network = scan_network(ctx.node.ipv4)
    if configured:
        seen = _egress(ctx)
        if is_direct(seen) is not True:
            ui.warn(
                f"备选未补充：{_route_text(seen, network)}，扫描不能经过代理。"
                "节点照常使用当前的 SNI 和备选；关闭代理后重跑即可补充。"
            )
            return
    else:
        require_direct(ctx)
    targets = scan_targets(ctx.node.ipv4)
    ui.detail(f"在你的电脑上扫描 {network} 里的 {len(targets)} 个地址（不含节点所在的 /22，只连 443 端口，不带 SNI）。")
    found = ctx.deps.scan(targets, progress=ui.stage_count)
    short = shortlist(found)
    hits = [hit for hit in short if ctx.deps.sni_ok(hit.ip, hit.domain)]
    ui.detail(f"扫到 {len(found)} 个站点，过滤后剩 {len(short)} 个，带 SNI 握手成功 {len(hits)} 个。")
    if hits or not configured:
        ctx.hits = hits  # none at all on a first deployment: step_sni goes to the pool
    else:
        ui.warn("这次没有扫到可用的候选，备选 SNI 保持不变。")


def step_sni(ctx: DeployContext) -> None:
    """Have the node check the candidates itself, then keep the SNI and write the backups.

    The node first checks each candidate with curl, then tries the ones that pass with a real
    REALITY handshake (``reality-candidates.sh``, which needs the Docker of step 4). A node that already runs
    Xray keeps its current SNI; only its backups are replaced. A node whose deployment never
    finished keeps its SNI only while it still passes, and otherwise gets a new one. Too few
    candidates are topped up from the pool, behind every neighbour (``_from_pool``) but the
    foreign ones (``_place``), which come last. New
    backups end the control plane's "backups used up" mark for the node. An installed SNI
    rotation service is stopped first, as from here on the run changes the node's files.
    """
    ui = ctx.deps.ui
    stop_rotation(ctx)
    if ctx.hits is None:
        ui.detail("沿用节点上已有的 SNI 和备选。")
        _rerank_backups(ctx)
        return
    remote = ctx.remote()
    args = [value for hit in ctx.hits for value in (hit.domain, hit.ip)]
    if args:
        ui.detail(f"交给节点验证的候选：{'、'.join(f'{hit.domain}（{hit.ip}）' for hit in ctx.hits)}")
    tls = parse_validation(remote.run_script("validate-candidates.sh", args)) if args else []
    passed = _borrowable(ctx, tls) if tls else []
    ui.detail(f"节点验证了 {len(ctx.hits)} 个候选：TLS 检查通过 {len(tls)} 个，REALITY 握手通过 {len(passed)} 个。")
    config = ctx.read(CONFIG_PATH)
    if config is not None and not ctx.deployed:
        identity = read_identity(config)
        if not any(cand.domain == identity["sni"] and cand.ip == identity["dest_ip"] for cand in passed):
            ui.warn(f"节点还没有部署完成，它的 SNI {identity['sni']} 这次没有通过验证，改选新的 SNI。")
            config = None
    current = read_identity(config)["sni"] if config is not None else None
    usable = _place(ctx, [cand for cand in passed if cand.domain != current])
    wanted = REFILL_BELOW + (1 if config is None else 0)  # the SNI itself, and enough backups
    missing = wanted - sum(not cand.foreign for cand in usable)
    if missing > 0:
        usable += _from_pool(ctx, missing, {cand.domain for cand in usable} | {current})
    if config is None:
        chosen, backups = choose(usable, MAX_BACKUPS)
        ctx.sni = chosen
        ui.detail(f"选定 SNI：{chosen.domain}（{chosen.ip}，{chosen.latency_ms} 毫秒），备选 {len(backups)} 个。")
    else:
        backups = ranked(usable)[:MAX_BACKUPS]
        if not backups:
            ui.warn("没有新的候选通过节点验证，备选 SNI 保持不变。")
            return
        ui.detail(f"保留当前 SNI {current}，备选更新为 {len(backups)} 个。")
    remote.put_text(BACKUPS_PATH, backups_json(backups), "600")
    if ctx.inventory.clear_exhausted(ctx.node.alias):
        ui.detail("备选 SNI 已补充，控制端不再把这个节点记为备选用完。")


def require_direct(ctx: DeployContext) -> None:
    """Go on once this computer reaches the node's network directly; stop when you say so.

    Behind a proxy you are asked to turn it off and check again, so the instance already
    created is kept. When the addresses cannot be read you may confirm a direct connection
    yourself, but not while DNS shows a proxy.
    """
    network = scan_network(ctx.node.ipv4)
    while True:
        seen = _egress(ctx)
        direct = is_direct(seen)
        if direct is True:
            return
        if direct is None:
            question = f"{_route_text(seen, network)}。扫描必须直连进行，不能经过代理，请确认。"
            if ctx.deps.ui.choose(question, UNKNOWN_EGRESS_OPTIONS) != 0:
                raise CnsrError(f"已停止：扫描 {network} 必须直连。")
            return
        question = f"{_route_text(seen, network)}。扫描必须直连，请关闭代理（包括圈X 这类 TUN 模式的代理），然后重新检查。"
        if ctx.deps.ui.choose(question, PROXIED_OPTIONS) != 0:
            raise CnsrError(f"已停止：扫描 {network} 必须直连，请关闭代理后重跑。")


def _egress(ctx: DeployContext) -> Egress:
    """How this computer reaches the node's network: its address as a domestic echo and as the
    node sees it, and whether its DNS answers with a proxy's fake addresses.

    The node is reached by IP over a new connection, the same way the scan goes. ``SSH_CLIENT``
    is read without sudo, which would reset the environment.
    """
    domestic = ctx.deps.direct_address()
    fake_dns = ctx.deps.fake_ip_dns()
    try:
        node = client_address(ctx.remote().run(["printenv", "SSH_CLIENT"]))
    except SshError:
        raise
    except CnsrError:  # printenv fails when the variable is not set
        node = None
    ctx.deps.ui.detail(
        f"直连检查：国内回显服务看到的地址 {domestic or '未知'}，节点看到的来源地址 {node or '未知'}，"
        f"本机 DNS {'返回了' if fake_dns else '没有返回'}代理软件的虚拟地址（{FAKE_IP_NETWORK}）。"
    )
    return Egress(domestic, node, fake_dns)


def _route_text(seen: Egress, network: str) -> str:
    if seen.fake_dns:
        return f"这台电脑在用代理：本机 DNS 把域名解析成了代理软件的虚拟地址（{FAKE_IP_NETWORK}），发往 {network} 的扫描会经过代理"
    if seen.domestic is None:
        return f"无法确认发往节点所在网段 {network} 的流量是否直连（国内回显服务都没有应答）"
    if seen.node is None:
        return f"无法确认发往节点所在网段 {network} 的流量是否直连（节点没有报告你的来源地址）"
    return (
        f"发往节点所在网段 {network} 的流量走了代理：节点看到你从 {seen.node} 连过来，"
        f"而你直连时的出口是 {seen.domestic}"
    )


def _borrowable(ctx: DeployContext, cands: list[Candidate]) -> list[Candidate]:
    """The candidates a REALITY server on the node really completes a handshake with, in order."""
    remote = ctx.remote()
    ctx.deps.ui.detail("用 Xray 实际试一遍每个候选的 REALITY 握手。")
    output = remote.run_script("reality-candidates.sh", [value for cand in cands for value in (cand.domain, cand.ip)])
    ok = {(fields[0], fields[1]) for fields in map(str.split, output.splitlines()) if len(fields) == 2}
    return [cand for cand in cands if (cand.domain, cand.ip) in ok]


def _from_pool(ctx: DeployContext, count: int, taken: set[str | None]) -> list[Candidate]:
    """Up to ``count`` domains of the pool for the node's country, not in ``taken``, that pass every
    check the neighbours pass, in the pool's order."""
    ui, remote = ctx.deps.ui, ctx.remote()
    domains = [domain for domain in pool.domains(_country(ctx)) if domain not in taken]
    found = _resolve(ctx, domains)
    pairs = [(domain, found[domain]) for domain in domains if domain in found]
    pairs = [(domain, ip) for domain, ip in pairs if ctx.deps.sni_ok(ip, domain)]
    passed: list[Candidate] = []
    if pairs:
        output = remote.run_script("validate-candidates.sh", [value for pair in pairs for value in pair])
        tls = parse_validation(output)
        passed = _borrowable(ctx, tls) if tls else []
    chosen = [replace(cand, pool=True) for cand in passed[:count]]
    named = "、".join(cand.domain for cand in chosen)
    ui.detail(f"合格的邻居不够，从备用域名里补充 {len(chosen)} 个（还差 {count} 个）：{named or '没有通过检查的'}。")
    return chosen


def _country(ctx: DeployContext) -> str:
    """The node's country as Cloudflare sees it, or an empty string."""
    try:
        text = ctx.remote().run(["curl", "-s", "--max-time", "8", TRACE_URL])
    except SshError:
        raise
    except CnsrError:
        return ""
    match = _COUNTRY.search(text)
    return match[1] if match else ""


def _resolve(ctx: DeployContext, domains: list[str]) -> dict[str, str]:
    """The first public IPv4 address the node resolves each domain to; a domain without one is missing."""
    found = _addresses(ctx, domains)
    first = {domain: next((ip for ip in ips if _is_public(ip)), None) for domain, ips in found.items()}
    return {domain: ip for domain, ip in first.items() if ip is not None}


def _addresses(ctx: DeployContext, domains: list[str]) -> dict[str, list[str]]:
    """Every IPv4 address the node resolves each domain to; a domain it cannot resolve is missing."""
    found: dict[str, list[str]] = {}
    if not domains:
        return found
    for line in ctx.remote().run(["sh", "-c", RESOLVE, "sh", *domains]).splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] in domains:
            found.setdefault(fields[0], []).append(fields[1])
    return found


def _place(ctx: DeployContext, cands: list[Candidate]) -> list[Candidate]:
    """The candidates, each marked ``foreign`` when DNS does not place it at its address, nor at
    another one of the same provider (a load balancer's addresses come and go).

    A node that resolves none of them says nothing about any.
    """
    found = _addresses(ctx, [cand.domain for cand in cands if not cand.pool])
    if not found:
        return cands
    astray = [cand for cand in cands if not cand.pool and cand.ip not in found.get(cand.domain, [])]
    providers = _providers(ctx, {ip for cand in astray for ip in (cand.ip, *found.get(cand.domain, []))})
    foreign = {
        cand.domain
        for cand in astray
        if providers.get(cand.ip) is None
        or providers[cand.ip] not in {providers.get(ip) for ip in found.get(cand.domain, [])}
    }
    if foreign:
        ctx.deps.ui.detail(f"DNS 没有指向扫到的地址、可能是别人的节点，排到最后：{'、'.join(sorted(foreign))}。")
    return [cand if cand.pool else replace(cand, foreign=cand.domain in foreign) for cand in cands]


def _providers(ctx: DeployContext, ips: set[str]) -> dict[str, str]:
    """Whose each address is: the last two labels of its name in reverse DNS, such as ``amazonaws.com``."""
    found: dict[str, str] = {}
    if not ips:
        return found
    for line in ctx.remote().run(["sh", "-c", REVERSE, "sh", *sorted(ips)]).splitlines():
        fields = line.split()
        labels = fields[1].rstrip(".").lower().split(".") if len(fields) == 2 else []
        if len(labels) > 2 and fields[0] in ips:
            found.setdefault(fields[0], ".".join(labels[-2:]))
    return found


def _rerank_backups(ctx: DeployContext) -> None:
    """Put the foreign ones of the backups already on the node last."""
    backups = _backups_on_node(ctx)
    better = ranked(_place(ctx, backups))
    if better != backups:
        ctx.remote().put_text(BACKUPS_PATH, backups_json(better), "600")


def _is_public(text: str) -> bool:
    try:
        return ipaddress.IPv4Address(text).is_global
    except ValueError:
        return False


def _backups_on_node(ctx: DeployContext) -> list[Candidate]:
    text = ctx.read(BACKUPS_PATH)
    if text is None:
        return []
    try:
        return parse_backups(text)
    except CnsrError as exc:
        ctx.deps.ui.warn(f"节点上的备选 SNI 列表无法读取，将重新扫描：{exc}")
        return []
