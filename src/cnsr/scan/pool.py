"""Well-known domains that top up a node's SNI candidates when too few neighbours pass.

They are only a supplement: the address of such a site does not match the node's network, so the
disguise is weaker than a neighbour's. Within a list the sites served from a network of their own
come first and those on a CDN last: REALITY forwards strangers' connections to the target, and a
CDN edge would serve them every site it hosts. A list only suggests; every domain is checked from
the node like a neighbour before it is used.
"""

from __future__ import annotations

# The domains of JP passed every check from a node in Osaka on 2026-11-24.
_BY_COUNTRY = {
    "JP": (
        "www.yahoo.co.jp",
        "www.ritsumei.ac.jp",
        "www.nii.ac.jp",
        "gateway.icloud.com",
        "id.keyence.com",
        "www.keyence.co.jp",
        "www.nintendo.co.jp",
        "www.sony.com",
        "www.panasonic.com",
        "www.jreast.co.jp",
        "www.softbank.jp",
        "www.ntt.com",
        "www.kyoto-u.ac.jp",
        "www.lawson.co.jp",
        "nightreign.eldenring.jp",
    ),
}
# For a country without a list of its own, or one the node could not tell.
_GENERAL = ("gateway.icloud.com", "addons.mozilla.org", "www.microsoft.com", "swdist.apple.com")


def domains(country: str) -> tuple[str, ...]:
    """The domains for a two-letter country code, in the order they are preferred."""
    return _BY_COUNTRY.get(country, _GENERAL)
