"""Tests for the traffic meter."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unofficial_protonvpn import traffic  # noqa: E402
from unofficial_protonvpn.traffic import (  # noqa: E402
    TrafficMeter, TrafficSample, find_tunnel_interface, format_bytes,
    format_rate, format_stats_line,
)


class FakeInterface:
    """Stands in for /sys/class/net/<iface>/statistics."""

    def __init__(self):
        self.counters = None  # None = interface absent (disconnected)

    def read_counters(self, _interface):
        return self.counters


class TrafficMeterTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeInterface()
        self._real = traffic.read_counters
        traffic.read_counters = self.fake.read_counters
        # Pin discovery too. The meter re-discovers the tunnel device whenever
        # the counters disappear, because it changes with the protocol
        # (proton0 for WireGuard, a tun device for OpenVPN). Without this these
        # tests pass only while the machine happens to be connected to a VPN,
        # and fail the moment it is not.
        self._real_find = traffic.find_tunnel_interface
        traffic.find_tunnel_interface = lambda: "test0"

        self.meter = TrafficMeter()
        self.meter.interface = "test0"

    def tearDown(self):
        traffic.read_counters = self._real
        traffic.find_tunnel_interface = self._real_find

    def test_disconnected_when_interface_absent(self):
        sample = self.meter.sample(now=0)
        self.assertFalse(sample.connected)
        self.assertEqual(sample.total, 0)

    def test_first_sample_reports_total_but_no_rate(self):
        self.fake.counters = (1000, 500)
        sample = self.meter.sample(now=0)
        self.assertTrue(sample.connected)
        self.assertEqual(sample.total, 1500)
        self.assertEqual(sample.down_rate, 0.0)

    def test_rates_are_delta_over_elapsed_time(self):
        self.fake.counters = (1000, 500)
        self.meter.sample(now=10.0)
        self.fake.counters = (3000, 1500)
        sample = self.meter.sample(now=12.0)  # 2 seconds later
        self.assertEqual(sample.down_rate, 1000.0)  # 2000 bytes / 2 s
        self.assertEqual(sample.up_rate, 500.0)
        self.assertEqual(sample.total, 4500)

    def test_counter_reset_is_treated_as_new_tunnel_not_negative_rate(self):
        self.fake.counters = (10_000, 5_000)
        self.meter.sample(now=0)
        self.fake.counters = (100, 50)  # interface recreated, counters restarted
        sample = self.meter.sample(now=1)
        self.assertGreaterEqual(sample.down_rate, 0.0)
        self.assertEqual(sample.down_rate, 0.0)
        self.assertEqual(sample.total, 150)

    def test_disconnect_clears_baseline_so_reconnect_shows_no_spike(self):
        self.fake.counters = (10_000, 5_000)
        self.meter.sample(now=0)
        self.fake.counters = None
        self.meter.sample(now=1)          # disconnected
        self.fake.counters = (20_000, 9_000)
        sample = self.meter.sample(now=2)  # reconnected
        self.assertEqual(sample.down_rate, 0.0, "must not bill the gap as a spike")
        self.assertEqual(sample.total, 29_000)

    def test_zero_elapsed_time_does_not_divide_by_zero(self):
        self.fake.counters = (1000, 500)
        self.meter.sample(now=5.0)
        self.fake.counters = (2000, 1000)
        sample = self.meter.sample(now=5.0)
        self.assertEqual(sample.down_rate, 0.0)


class FormattingTest(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(999), "999 B")
        self.assertEqual(format_bytes(1000), "1.0 KB")
        self.assertEqual(format_bytes(139_000), "139 KB")
        self.assertEqual(format_bytes(3_400_000_000), "3.4 GB")

    def test_format_rate(self):
        self.assertEqual(format_rate(139_000), "139 KB/s")

    def test_stats_line_matches_the_planned_shape(self):
        line = format_stats_line(
            TrafficSample(down_rate=139_000, up_rate=105_000,
                          total=3_400_000_000, connected=True))
        self.assertEqual(line, "↓ 139 KB/s   ↑ 105 KB/s   ·   3.4 GB total")

    def test_stats_line_when_disconnected(self):
        self.assertEqual(format_stats_line(TrafficSample()), "Disconnected")


class RealSysfsTest(unittest.TestCase):
    def test_reads_a_real_interface_or_returns_none(self):
        # lo always exists; a nonsense name must return None, not raise.
        self.assertIsNotNone(traffic.read_counters("lo"))
        self.assertIsNone(traffic.read_counters("definitely-not-an-interface"))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class InterfaceDiscoveryTest(unittest.TestCase):
    """Which device carries the tunnel depends on the protocol.

    Hardcoding `proton0` silently broke every non-WireGuard protocol: OpenVPN
    gets a tun device, so the figures simply stayed blank.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        patcher = patch("unofficial_protonvpn.traffic.NETWORK_DEVICES", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.root, True)

    def device(self, name, operstate="up", rx=0, tx=0):
        path = self.root / name
        (path / "statistics").mkdir(parents=True)
        (path / "operstate").write_text(operstate + "\n")
        (path / "statistics" / "rx_bytes").write_text(f"{rx}\n")
        (path / "statistics" / "tx_bytes").write_text(f"{tx}\n")

    def test_prefers_proton0_when_present(self):
        self.device("proton0")
        self.device("tun0")
        self.assertEqual(find_tunnel_interface(), "proton0")

    def test_finds_the_openvpn_tun_device(self):
        self.device("tun0", operstate="unknown")
        self.assertEqual(find_tunnel_interface(), "tun0")

    def test_ignores_the_kill_switch_devices(self):
        """These are Proton's, but they are not the tunnel."""
        self.device("pvpnksintrf0")
        self.device("ipv6leakintrf0")
        self.assertIsNone(find_tunnel_interface())

    def test_ignores_ordinary_interfaces(self):
        self.device("wlp99s0")
        self.device("enp5s0")
        self.device("docker0")
        self.assertIsNone(find_tunnel_interface())

    def test_nothing_at_all_gives_none(self):
        self.assertIsNone(find_tunnel_interface())

    def test_a_down_device_is_not_the_tunnel(self):
        self.device("tun0", operstate="down")
        self.assertIsNone(find_tunnel_interface())

    def test_the_meter_discovers_and_reports_connected(self):
        self.device("tun0", operstate="unknown", rx=1000, tx=500)
        meter = TrafficMeter()
        sample = meter.sample(now=0.0)
        self.assertTrue(sample.connected)
        self.assertEqual(meter.interface, "tun0")

    def test_the_meter_re_discovers_when_the_device_changes(self):
        """Switching protocol swaps the device underneath us."""
        self.device("tun0", operstate="unknown", rx=1000, tx=500)
        meter = TrafficMeter()
        meter.sample(now=0.0)
        self.assertEqual(meter.interface, "tun0")

        shutil.rmtree(self.root / "tun0")
        self.device("proton0", operstate="up", rx=10, tx=10)
        sample = meter.sample(now=1.0)
        self.assertTrue(sample.connected)
        self.assertEqual(meter.interface, "proton0")
