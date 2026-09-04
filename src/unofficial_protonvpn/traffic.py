"""
Traffic counters for the VPN interface.

PLAN.md §5: `/sys/class/net/proton0/statistics/{rx,tx}_bytes` - no root needed.
§6: rates are the delta since the last tick, the total is cumulative.

The kernel resets these counters every time the interface is recreated, which
happens on every new connection. That makes the raw counter exactly the
"total this session", and it also means a *decrease* is the signal that a new
tunnel came up - handled in `sample()`.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

#: The WireGuard interface Proton creates. Verified on the dev machine.
NETWORK_DEVICES = Path("/sys/class/net")

DEFAULT_INTERFACE = "proton0"

#: Interface name prefixes a Proton tunnel can appear under. WireGuard gives
#: `proton0`; OpenVPN gives a `tun` device; the Proton protocols may use their
#: own. Assuming `proton0` silently broke every non-WireGuard protocol - the
#: figures simply stayed blank.
TUNNEL_PREFIXES = ("proton", "tun", "wg")

#: Never mistake the kill switch's dummy devices for the tunnel.
NOT_TUNNELS = ("pvpnksintrf", "ipv6leakintrf", "pvpn-killswitch")



def find_tunnel_interface() -> Optional[str]:
    """The interface carrying the tunnel right now, or None.

    Prefers `proton0` when present, then any `tun*`/`wg*` device that is up.
    """
    if (NETWORK_DEVICES / DEFAULT_INTERFACE).exists():
        return DEFAULT_INTERFACE

    try:
        candidates = sorted(entry.name for entry in NETWORK_DEVICES.iterdir())
    except OSError:
        return None

    for name in candidates:
        if any(name.startswith(skip) for skip in NOT_TUNNELS):
            continue
        if not any(name.startswith(prefix) for prefix in TUNNEL_PREFIXES):
            continue
        try:
            state = (NETWORK_DEVICES / name / "operstate").read_text().strip()
        except OSError:
            continue
        # tun devices report "unknown" rather than "up" while carrying traffic.
        if state in ("up", "unknown"):
            return name
    return None

_STATS = "/sys/class/net/{iface}/statistics/{counter}_bytes"


def read_counters(interface: str = DEFAULT_INTERFACE) -> Optional[Tuple[int, int]]:
    """Return (rx_bytes, tx_bytes), or None if the interface isn't there.

    None is the normal disconnected case, not an error.
    """
    # Built from NETWORK_DEVICES rather than a formatted constant, so the
    # device tree can be pointed elsewhere in tests - otherwise a test reads
    # the machine's real interfaces and passes for the wrong reason.
    statistics = NETWORK_DEVICES / interface / "statistics"
    try:
        rx = int((statistics / "rx_bytes").read_text())
        tx = int((statistics / "tx_bytes").read_text())
    except (OSError, ValueError):
        return None
    return rx, tx


@dataclass(frozen=True)
class TrafficSample:
    """One tick of traffic data."""

    down_rate: float = 0.0   # bytes/second since the previous sample
    up_rate: float = 0.0
    total: int = 0           # bytes moved on this interface, both directions
    connected: bool = False


class TrafficMeter:
    """Turns successive counter readings into rates and a session total."""

    def __init__(self, interface: Optional[str] = None):
        self.interface = interface
        self._previous: Optional[Tuple[int, int]] = None
        self._previous_time: Optional[float] = None

    def reset(self) -> None:
        """Forget the baseline, so the next sample reports no rate."""
        self._previous = None
        self._previous_time = None

    def sample(self, now: Optional[float] = None) -> TrafficSample:
        """Read the counters and report rates since the previous call."""
        now = time.monotonic() if now is None else now

        # Re-discover the interface each time it goes missing: the tunnel's
        # device depends on the protocol (proton0 for WireGuard, a tun device
        # for OpenVPN) and changes when the protocol does.
        if self.interface is None:
            self.interface = find_tunnel_interface()

        counters = read_counters(self.interface) if self.interface else None
        if counters is None:
            self.interface = find_tunnel_interface()
            counters = read_counters(self.interface) if self.interface else None

        if counters is None:
            self.reset()
            return TrafficSample(connected=False)

        rx, tx = counters
        previous, previous_time = self._previous, self._previous_time
        self._previous, self._previous_time = counters, now

        # First sample after connecting, or the interface was recreated and the
        # counters restarted: report the total, but no rate we cannot compute.
        if previous is None or previous_time is None:
            return TrafficSample(total=rx + tx, connected=True)
        if rx < previous[0] or tx < previous[1]:
            return TrafficSample(total=rx + tx, connected=True)

        elapsed = now - previous_time
        if elapsed <= 0:
            return TrafficSample(total=rx + tx, connected=True)

        return TrafficSample(
            down_rate=(rx - previous[0]) / elapsed,
            up_rate=(tx - previous[1]) / elapsed,
            total=rx + tx,
            connected=True,
        )


def format_bytes(count: float) -> str:
    """Human-readable size, e.g. '3.4 GB'. Decimal units, as Proton's UI uses."""
    value = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1000 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}" if value < 100 else f"{value:.0f} {unit}"
        value /= 1000.0
    return f"{value:.1f} TB"  # unreachable, kept for clarity


def format_rate(bytes_per_second: float) -> str:
    """Human-readable rate, e.g. '139 KB/s'."""
    return f"{format_bytes(bytes_per_second)}/s"


def format_stats_line(sample: TrafficSample, disconnected_text: str = "Disconnected") -> str:
    """The tray's live line: '↓ 139 KB/s   ↑ 105 KB/s   ·   3.4 GB total'."""
    if not sample.connected:
        return disconnected_text
    return (
        f"↓ {format_rate(sample.down_rate)}   "
        f"↑ {format_rate(sample.up_rate)}   ·   "
        f"{format_bytes(sample.total)} total"
    )
