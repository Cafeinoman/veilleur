# SPDX-License-Identifier: EUPL-1.2
"""SSRF guard (cahier ES-08): which resolved addresses a collector may reach.

Only global unicast addresses are allowed. Refused: loopback, private, link-local, CGNAT (100.64/10), multicast,
reserved, unspecified and documentation addresses, in IPv4 and IPv6; an IPv6 address that embeds an IPv4 one
(IPv4-mapped, NAT64, 6to4) is judged by the embedded address; Teredo and the 6to4 relay are refused.
"""

from __future__ import annotations

import ipaddress

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_REFUSED_V4 = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )
)
_NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))
_TEREDO = ipaddress.ip_network("2001::/32")


def _v4_allowed(address: ipaddress.IPv4Address) -> bool:
    return address.is_global and not any(address in network for network in _REFUSED_V4)


def is_allowed(address: IPAddress) -> bool:
    """True when a collector may connect to `address`."""
    if isinstance(address, ipaddress.IPv4Address):
        return _v4_allowed(address)
    if address.ipv4_mapped is not None:
        return _v4_allowed(address.ipv4_mapped)
    if any(address in network for network in _NAT64):
        return _v4_allowed(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
    if address.sixtofour is not None:
        return _v4_allowed(address.sixtofour)
    if address in _TEREDO or address.scope_id:
        return False
    return (
        address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_site_local
        and not address.is_unspecified
    )


def parse_allowed(text: str) -> IPAddress | None:
    """The address in `text` if it is allowed, otherwise None (also for text that is not an address)."""
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    return address if is_allowed(address) else None
