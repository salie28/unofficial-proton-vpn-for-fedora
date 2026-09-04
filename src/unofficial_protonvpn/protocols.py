"""
Display names for VPN protocols.

The values Proton stores are hyphenated identifiers ("openvpn-udp",
"protun-smart"). Title-casing them produces things like "Protun-Smart", which
means nothing to anyone. These are the names Proton themselves use in their
Windows client, so the same connection is called the same thing on both.
"""

from typing import Optional

#: Stored value -> what the user should read.
PROTOCOL_NAMES = {
    "wireguard": "WireGuard",
    "openvpn-udp": "OpenVPN (UDP)",
    "openvpn-tcp": "OpenVPN (TCP)",
    "protun-udp": "Proton WireGuard (UDP)",
    "protun-tcp": "Proton WireGuard (TCP)",
    "protun-tls": "Stealth",
    "protun-smart": "Smart",
}

#: Longest name we will put on the narrow rail before shortening it.
RAIL_LIMIT = 16

#: Shorter forms, for the rail only.
RAIL_NAMES = {
    "protun-udp": "Proton WG (UDP)",
    "protun-tcp": "Proton WG (TCP)",
}


def protocol_name(value, short: bool = False) -> Optional[str]:
    """The display name for a stored protocol value.

    Unknown values fall back to a tidied form of themselves rather than being
    hidden: a protocol we do not recognise is still worth showing.
    """
    if not value:
        return None

    key = str(value).strip().lower()
    if short and key in RAIL_NAMES:
        return RAIL_NAMES[key]
    if key in PROTOCOL_NAMES:
        return PROTOCOL_NAMES[key]

    tidied = str(value).replace("-", " ").replace("_", " ").title()
    if short and len(tidied) > RAIL_LIMIT:
        return tidied[:RAIL_LIMIT - 1] + "…"
    return tidied
