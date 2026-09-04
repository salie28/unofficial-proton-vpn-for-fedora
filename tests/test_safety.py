"""
The safety properties.

PLAN.md §7 problem #2: "UI could display 'Protected' when not connected. The
only way this app can harm someone." These tests exercise the failure paths -
failed reconnects, vanished tunnels, error states - rather than the happy path,
because the happy path was never the risk.
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
from unofficial_protonvpn.widgets.tier_notice import (  # noqa: E402
    FreeAccountGate, TierNotice, is_free_tier,
)


class ScriptedMeter(TrafficMeter):
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


def state(name, server="AT#215", ip="203.0.113.42"):
    obj = MagicMock()
    type(obj).__name__ = name
    obj.context.connection.server_name = server
    obj.context.connection.protocol = "wireguard"
    obj.context.event.context.connection_details = SimpleNamespace(device_ip=ip)
    return obj


def make_bar(meter=None):
    controller = MagicMock()
    controller.server_list.get_by_name.return_value = SimpleNamespace(load=36)
    return StatsBar(controller, meter=meter or ScriptedMeter([]))


class NeverClaimsAConnectionItDoesNotHaveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def shown(self, bar):
        return {key: label.get_text() for key, label in bar._cells.items()}

    def assert_shows_nothing(self, bar, context):
        values = self.shown(bar)
        stale = {k: v for k, v in values.items() if v != PLACEHOLDER}
        self.assertEqual(stale, {}, f"stale connection data after {context}: {stale}")

    def test_failed_reconnect_leaves_no_stale_data(self):
        """Connected, dropped, reconnect attempt fails: nothing may remain."""
        bar = make_bar()
        bar._apply_state(state("Connected"))
        self.assertEqual(self.shown(bar)["ip"], "203.0.113.42")

        bar._apply_state(state("Disconnected"))
        self.assert_shows_nothing(bar, "a disconnect")

        bar._apply_state(state("Connecting"))
        self.assert_shows_nothing(bar, "a reconnect attempt")

        bar._apply_state(state("Error"))
        self.assert_shows_nothing(bar, "a failed reconnect")

    def test_error_straight_from_connected(self):
        bar = make_bar()
        bar._apply_state(state("Connected"))
        bar._apply_state(state("Error"))
        self.assert_shows_nothing(bar, "an error")

    def test_the_protected_claim_comes_from_the_state_not_the_interface(self):
        """What decides "Protected" is Proton's connection state.

        An earlier version used a missing network device as a second authority.
        That reads as safety but is a false negative: the tunnel's device is
        named differently per protocol (proton0 for WireGuard, a tun device for
        OpenVPN), so a perfectly good connection looked disconnected and the
        whole bar blanked. The state machine is the authority; the interface
        only supplies traffic counters.
        """
        from unofficial_protonvpn.widgets.connection_panel import ConnectionPanel

        controller = MagicMock()
        controller.server_list.get_by_name.return_value = SimpleNamespace(
            exit_country="AT", location="Vienna")
        panel = ConnectionPanel(controller)

        panel._apply_state(state("Connected"))
        self.assertIn("Protected", panel.status_label.get_text())

        panel._apply_state(state("Disconnected"))
        self.assertIn("Unprotected", panel.status_label.get_text())
        panel.teardown()

    def test_traffic_blanks_when_counters_vanish_but_the_rest_stands(self):
        bar = make_bar(meter=ScriptedMeter([
            TrafficSample(down_rate=1000, up_rate=500, total=9000, connected=True),
            TrafficSample(connected=False),   # device renamed, or not up yet
        ]))
        bar._apply_state(state("Connected"))
        bar._on_tick()
        bar._on_tick()

        shown = self.shown(bar)
        self.assertEqual(shown["total"], PLACEHOLDER)
        self.assertEqual(shown["ip"], "203.0.113.42",
                         "the IP comes from the connection, not the interface")
        bar.teardown()

    def test_poll_never_survives_a_disconnect(self):
        """A running poll would keep rewriting numbers for a dead tunnel."""
        for ending in ("Disconnected", "Error", "Disconnecting"):
            with self.subTest(state=ending):
                bar = make_bar()
                bar._apply_state(state("Connected"))
                bar._apply_state(state(ending))
                self.assertIsNone(bar._poll_source_id)

    def test_reconnect_to_a_different_server_replaces_the_old_details(self):
        bar = make_bar()
        bar._apply_state(state("Connected", server="AT#215", ip="203.0.113.42"))
        bar._apply_state(state("Disconnected"))
        bar._apply_state(state("Connected", server="DE#42", ip="1.2.3.4"))
        self.assertEqual(self.shown(bar)["ip"], "1.2.3.4")
        bar.teardown()


class PaidPlanNoticeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def test_free_tier_is_recognised(self):
        self.assertTrue(is_free_tier(0))
        self.assertFalse(is_free_tier(2))   # PLUS
        self.assertFalse(is_free_tier(3))   # PM

    def test_unknown_tier_is_treated_as_paid(self):
        """A wrong guess must never nag a paying customer."""
        for value in (None, "", "nonsense", object()):
            with self.subTest(value=value):
                self.assertFalse(is_free_tier(value))

    def test_notice_shows_only_for_free_accounts(self):
        notice = TierNotice()
        self.assertFalse(notice.get_visible(), "hidden until we know the tier")

        notice.update_for_tier(0)
        self.assertTrue(notice.get_visible())

        notice.update_for_tier(2)
        self.assertFalse(notice.get_visible())

    def test_notice_is_dismissible_and_does_not_block(self):
        notice = TierNotice()
        notice.update_for_tier(0)
        dismiss = [c for c in iter_children(notice) if isinstance(c, Gtk.Button)]
        self.assertTrue(dismiss, "the notice must be dismissible")
        dismiss[0].emit("clicked")
        self.assertFalse(notice.get_visible())


class FreeAccountGateTest(unittest.TestCase):
    """The warning has to be impossible to miss, and impossible to get stuck in."""

    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def test_hidden_for_paid_accounts(self):
        gate = FreeAccountGate()
        gate.update_for_tier(2)
        self.assertFalse(gate.get_visible())

    def test_shown_for_free_accounts(self):
        gate = FreeAccountGate()
        gate.update_for_tier(0)
        self.assertTrue(gate.get_visible())

    def test_covers_the_whole_window(self):
        gate = FreeAccountGate()
        self.assertTrue(gate.get_hexpand())
        self.assertTrue(gate.get_vexpand())
        self.assertTrue(gate.get_can_target(),
                        "it must swallow clicks meant for what it covers")

    def test_says_what_actually_goes_wrong(self):
        """A warning that does not say why is not a warning."""
        blob = " ".join((FreeAccountGate.TITLE, FreeAccountGate.BODY,
                         FreeAccountGate.DETAIL)).lower()
        self.assertIn("paid", blob)
        self.assertIn("not work as intended", blob)
        for feature in ("secure core", "p2p", "tor"):
            self.assertIn(feature, blob)

    def test_says_the_vpn_itself_is_unaffected(self):
        self.assertIn("official Proton VPN app", FreeAccountGate.REASSURANCE)

    def test_acknowledging_dismisses_it(self):
        gate = FreeAccountGate()
        gate.update_for_tier(0)
        gate.acknowledge_button.emit("clicked")
        self.assertFalse(gate.get_visible(), "the button must let the user through")

    def test_it_warns_and_does_not_lock_anyone_out(self):
        """PLAN.md §1 says enforce softly: warn, never block."""
        gate = FreeAccountGate()
        gate.update_for_tier(0)
        gate.acknowledge_button.emit("clicked")
        # Nothing here re-shows it or disables anything underneath.
        self.assertFalse(gate.get_visible())
        self.assertTrue(gate.acknowledge_button.get_sensitive())


class ConnectingAnimationTest(unittest.TestCase):
    """The pulse must never outlive the state that justifies it."""

    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def panel(self):
        from unofficial_protonvpn.widgets.connection_panel import ConnectionPanel
        controller = MagicMock()
        controller.server_list.get_by_name.return_value = SimpleNamespace(
            exit_country="AT", location="Vienna")
        return ConnectionPanel(controller)

    def test_pulses_while_connecting(self):
        panel = self.panel()
        panel._apply_state(state("Connecting"))
        self.assertTrue(panel.has_css_class("connection-block-connecting"))

    def test_stops_pulsing_once_connected(self):
        panel = self.panel()
        panel._apply_state(state("Connecting"))
        panel._apply_state(state("Connected"))
        self.assertFalse(panel.has_css_class("connection-block-connecting"))
        panel.teardown()

    def test_stops_pulsing_on_failure(self):
        """A failed connect must not leave it breathing forever."""
        for ending in ("Error", "Disconnected"):
            with self.subTest(state=ending):
                panel = self.panel()
                panel._apply_state(state("Connecting"))
                panel._apply_state(state(ending))
                self.assertFalse(panel.has_css_class("connection-block-connecting"))


class ConnectingFeedbackTest(unittest.TestCase):
    """A connection attempt must be visible while it happens."""

    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def panel(self):
        from unofficial_protonvpn.widgets.connection_panel import ConnectionPanel
        controller = MagicMock()
        controller.server_list.get_by_name.return_value = SimpleNamespace(
            exit_country="AT", location="Vienna")
        return ConnectionPanel(controller), controller

    def test_connecting_says_so_and_spins(self):
        panel, _c = self.panel()
        panel._apply_state(state("Connecting"))
        self.assertEqual(panel.country_label.get_text(), "Connecting")
        self.assertTrue(panel.status_line.spinner.get_visible())
        self.assertFalse(panel.status_line.icon.get_visible())

    def test_connecting_offers_cancel_not_connect(self):
        """Their Windows client offers Cancel while a connection is forming."""
        panel, _c = self.panel()
        panel._apply_state(state("Connecting"))
        self.assertEqual(panel.button.get_label(), "Cancel")

    def test_cancel_disconnects_through_their_controller(self):
        panel, controller = self.panel()
        panel._apply_state(state("Connecting"))
        panel._on_button_clicked(panel.button)
        controller.disconnect.assert_called_once()
        controller.connect_to_fastest_server.assert_not_called()

    def test_the_spinner_stops_once_connected(self):
        panel, _c = self.panel()
        panel._apply_state(state("Connecting"))
        panel._apply_state(state("Connected"))
        self.assertFalse(panel.status_line.spinner.get_visible())
        self.assertTrue(panel.status_line.icon.get_visible())
        panel.teardown()

    def test_the_spinner_stops_if_the_attempt_fails(self):
        """A failed connect must not leave it spinning forever."""
        for ending in ("Error", "Disconnected"):
            with self.subTest(state=ending):
                panel, _c = self.panel()
                panel._apply_state(state("Connecting"))
                panel._apply_state(state(ending))
                self.assertFalse(panel.status_line.spinner.get_visible())


def iter_children(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()


if __name__ == "__main__":
    unittest.main(verbosity=2)
