"""Which scan hits are worth keeping as REALITY SNI candidates."""

from __future__ import annotations

import ipaddress
import itertools
import re

from cnsr.scan.probe import Hit, is_ip_address

DYNAMIC_DNS_SUFFIXES = (
    "duckdns.org",
    "eu.org",
    "qzz.io",
    "ddns.net",
    "no-ip.org",
    "hopto.org",
    "dynu.net",
    "freeddns.org",
    "nip.io",
    "sslip.io",
)
NAME_KEYWORDS = ("panel", "xui", "alist", "frp", "v2ray", "stg", "staging", "dev", "test", "demo")
LOW_REP_TLDS = (
    "info",
    "click",
    "top",
    "xyz",
    "club",
    "work",
    "site",
    "vip",
    "live",
    "loan",
    "cc",
    "online",
    "icu",
    "buzz",
    "shop",
    "rest",
)
BIG_SITES = (
    "apple.com",
    "icloud.com",
    "microsoft.com",
    "live.com",
    "office.com",
    "bing.com",
    "yahoo.com",
    "google.com",
    "gstatic.com",
    "youtube.com",
    "amazon.com",
    "cloudflare.com",
    "github.com",
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "netflix.com",
    "nvidia.com",
    "samsung.com",
)

_KEYWORDS = frozenset(NAME_KEYWORDS)
_CLOUDFLARE_ORIGIN = "cloudflare origin"


def basic_ok(h: Hit) -> bool:
    """Reject self-signed certificates, Cloudflare origin certificates, localhost and IP literals."""
    domain = h.domain.lower()
    if h.self_signed or _CLOUDFLARE_ORIGIN in h.issuer.lower() or domain == "localhost":
        return False
    return not is_ip_address(domain)


def reputation_ok(domain: str) -> bool:
    """Reject names that look like panels or test sites, cheap TLDs, dynamic DNS and big sites."""
    domain = domain.lower()
    labels = domain.split(".")
    if labels[-1] in LOW_REP_TLDS:
        return False
    if not _KEYWORDS.isdisjoint(re.split(r"[.-]", domain)):
        return False
    return not any(_has_suffix(domain, suffix) for suffix in DYNAMIC_DNS_SUFFIXES + BIG_SITES)


def shortlist(hits: list[Hit], limit: int = 30) -> list[Hit]:
    """Up to ``limit`` acceptable hits, one per domain, taken in turns from each /22 in input order.

    A vendor may route the /22s of one /20 differently, so that a node cannot reach a whole /22
    of its neighbours; taking turns keeps such a /22 from filling the list.
    """
    by_network: dict[ipaddress.IPv4Network, list[Hit]] = {}
    seen: set[str] = set()
    for h in hits:
        domain = h.domain.lower()
        if domain in seen or not basic_ok(h) or not reputation_ok(domain):
            continue
        seen.add(domain)
        by_network.setdefault(ipaddress.IPv4Network(f"{h.ip}/22", strict=False), []).append(h)
    rounds = itertools.zip_longest(*by_network.values())
    return [h for turn in rounds for h in turn if h is not None][:limit]


def _has_suffix(domain: str, suffix: str) -> bool:
    return domain == suffix or domain.endswith("." + suffix)

