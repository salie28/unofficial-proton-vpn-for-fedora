"""
Tests for the stats bar.

The important ones are the "never claim a connection that isn't there" cases:
PLAN.md §7 problem #2 calls that the only way this app can harm someone.
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unofficial_protonvpn.traffic import TrafficMeter, TrafficSample  # noqa: E402
from unofficial_protonvpn.widgets.stats_bar import PLACEHOLDER, StatsBar  # noqa: E402


class StubMeter(TrafficMeter):
    def __init__(self, samples):
        super().__init__()
        self.samples = list(samples)
        self.last = TrafficSample()

    def sample(self, now=None):
        if self.samples:
            self.last = self.samples.pop(0)
        return self.last

    def reset(self):
        pass


def connected_state(server_name="AT#215", device_ip="203.0.113.42",
                    protocol="wireguard"):
    state = MagicMock()
    type(state).__name__ = "Connected"
    state.context.connection.server_name = server_name
    state.context.connection.protocol = protocol
    state.context.event.context.connection_details = SimpleNamespace(
        device_ip=device_ip, device_country="AT",
        server_ipv4="203.0.113.7", server_ipv6=None)
    return state


def named_state(name):
    state = MagicMock()
    type(state).__name__ = name
    return state


def make_bar(load=42, protocol="wireguard", meter=None):
    controller = MagicMock()
    controller.get_settings.return_value.protocol = protocol
    controller.server_list.get_by_name.return_value = SimpleNamespace(load=load)
    return StatsBar(controller, meter=meter or StubMeter([]))


class StatsBarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def values(self, bar):
        return {key: label.get_text() for key, label in bar._cells.items()}

    def test_starts_empty(self):
        bar = make_bar()
        self.assertTrue(all(v == PLACEHOLDER for v in self.values(bar).values()))

    def test_populates_on_connect(self):
        bar = make_bar()
        bar._apply_state(connected_state())
        values = self.values(bar)
        self.assertEqual(values["ip"], "203.0.113.42")
        self.assertEqual(values["load"], "42%")
        self.assertEqual(values["protocol"], "WireGuard")
        bar.teardown()

    def test_clears_on_every_non_connected_state(self):
        for name in ("Disconnected", "Connecting", "Disconnecting", "Error"):
            with self.subTest(state=name):
                bar = make_bar()
                bar._apply_state(connected_state())
                bar._apply_state(named_state(name))
                values = self.values(bar)
                self.assertTrue(
                    all(v == PLACEHOLDER for v in values.values()),
                    f"stale data survived a {name} state: {values}")
                bar.teardown()

    def test_stops_polling_when_disconnected(self):
        bar = make_bar()
        bar._apply_state(connected_state())
        self.assertIsNotNone(bar._poll_source_id)
        bar._apply_state(named_state("Disconnected"))
        self.assertIsNone(bar._poll_source_id)

    def test_tick_shows_live_traffic(self):
        meter = StubMeter([TrafficSample(down_rate=139_000, up_rate=105_000,
                                         total=3_400_000_000, connected=True)])
        bar = make_bar(meter=meter)
        bar._apply_state(connected_state())
        self.assertTrue(bar._on_tick())
        values = self.values(bar)
        self.assertEqual(values["down"], "\u2193 139 KB/s")
        self.assertEqual(values["up"], "\u2191 105 KB/s")
        self.assertEqual(values["total"], "3.4 GB")
        self.assertEqual(bar.graph.samples, [(139_000, 105_000)],
                         "the chart should have been fed the same sample")
        bar.teardown()

    def test_missing_counters_blank_the_traffic_but_keep_the_connection(self):
        """No counters does not mean no VPN.

        The tunnel's device depends on the protocol - proton0 for WireGuard, a
        tun device for OpenVPN - and it can be absent while a connection is
        still coming up. Treating that as "disconnected" blanked the IP,
        protocol and load too, which are true whatever the device is called.
        """
        meter = StubMeter([
            TrafficSample(down_rate=1000, up_rate=1000, total=5000, connected=True),
            TrafficSample(connected=False),   # counters unreadable
        ])
        bar = make_bar(meter=meter)
        bar._apply_state(connected_state())
        self.assertTrue(bar._on_tick())
        self.assertTrue(bar._on_tick(), "keep polling; the device may reappear")

        values = self.values(bar)
        self.assertEqual(values["down"], PLACEHOLDER)
        self.assertEqual(values["up"], PLACEHOLDER)
        self.assertEqual(values["total"], PLACEHOLDER)
        self.assertEqual(values["ip"], "203.0.113.42",
                         "the IP comes from the connection, not the interface")
        self.assertEqual(values["protocol"], "WireGuard")
        bar.teardown()

    def test_missing_metadata_degrades_to_placeholders(self):
        controller = MagicMock()
        controller.get_settings.side_effect = RuntimeError(
            "settings must never be read here - it blocks on the executor")
        controller.server_list.get_by_name.side_effect = RuntimeError("no list")
        bar = StatsBar(controller, meter=StubMeter([]))
        bar._apply_state(connected_state(device_ip=None, protocol=None))
        values = self.values(bar)
        self.assertEqual(values["protocol"], PLACEHOLDER)
        self.assertEqual(values["load"], PLACEHOLDER)
        controller.get_settings.assert_not_called()
        bar.teardown()

    def test_status_update_does_no_work_on_the_calling_thread(self):
        """status_update runs on the executor thread; touching the controller
        there deadlocks (it submits to that same executor and waits)."""
        controller = MagicMock()
        controller.get_settings.side_effect = AssertionError("would deadlock")
        bar = StatsBar(controller, meter=StubMeter([]))
        bar.status_update(connected_state())  # must return immediately
        controller.get_settings.assert_not_called()
        self.assertIsNone(bar._poll_source_id, "no work should have run yet")

    def test_broken_state_object_does_not_raise(self):
        bar = make_bar()
        broken = MagicMock()
        type(broken).__name__ = "Connected"
        broken.context.connection.server_name = "AT#1"
        type(broken).context = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        bar._apply_state(broken)  # must not raise
        bar.teardown()


class ServerLoadBarTest(unittest.TestCase):
    """The bar eases, but must always end up on the real value."""

    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def bar(self):
        from unofficial_protonvpn.widgets.stats_bar import ServerLoadBar
        return ServerLoadBar()

    def test_first_value_appears_immediately(self):
        """Nothing to ease from, so do not animate up from zero."""
        bar = self.bar()
        bar.set_load(0.36)
        self.assertEqual(bar._load, 0.36)

    def test_clearing_is_immediate(self):
        bar = self.bar()
        bar.set_load(0.36)
        bar.set_load(None)
        self.assertIsNone(bar._load, "a cleared bar must not linger")

    def test_a_new_value_becomes_the_target(self):
        bar = self.bar()
        bar.set_load(0.20)
        bar.set_load(0.80)
        self.assertEqual(bar._target, 0.80)

    def test_colour_follows_the_load(self):
        bar = self.bar()
        for load, expected in ((0.10, bar.LOW), (0.60, bar.MEDIUM), (0.90, bar.HIGH)):
            bar._load = load
            self.assertEqual(bar._colour(), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
