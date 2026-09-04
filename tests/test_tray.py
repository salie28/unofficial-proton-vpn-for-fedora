"""Tests for the quick-access tray menu, using fakes for Proton's tray + controller."""

import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unofficial_protonvpn.recents import RecentsStore          # noqa: E402
from unofficial_protonvpn.tray import QuickAccessTrayIndicator  # noqa: E402
from unofficial_protonvpn.traffic import TrafficMeter, TrafficSample  # noqa: E402


@dataclass
class FakeMenuObject:
    label: str
    callback: object = None
    enabled: bool = True
    visible: bool = True
    is_separator: bool = False


@dataclass
class FakeTray:
    """Stands in for Proton's TrayIcon: same menu API, no DBus."""

    menu_items: list = field(default_factory=list)
    update_calls: int = 0

    def add_menu_item(self, label, callback, enabled=True, visible=True):
        self.menu_items.append(FakeMenuObject(label, callback, enabled, visible))

    def add_menu_separator(self):
        self.menu_items.append(FakeMenuObject("", is_separator=True))

    def update_menu(self):
        self.update_calls += 1

    def change_icon(self, *_args):
        pass

    @property
    def labels(self):
        return [i.label for i in self.menu_items if not i.is_separator]


class StubMeter(TrafficMeter):
    """A meter whose samples the test controls."""

    def __init__(self, samples):
        super().__init__()
        self.samples = list(samples)
        self.last = samples[-1] if samples else TrafficSample()

    def sample(self, now=None):
        if self.samples:
            self.last = self.samples.pop(0)
        return self.last

    def reset(self):
        pass


def make_indicator(connected=True, logged_in=True, recents=None, meter=None):
    controller = MagicMock()
    controller.user_logged_in = logged_in
    controller.connection_disconnected = not connected

    indicator = QuickAccessTrayIndicator(
        controller,
        recents=recents,
        meter=meter or StubMeter([TrafficSample(
            down_rate=139_000, up_rate=105_000, total=3_400_000_000, connected=connected)]),
        tray_icon=FakeTray(),
    )
    indicator._main_window = MagicMock()
    indicator._main_window.get_visible.return_value = False
    return indicator


class MenuStructureTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.store = RecentsStore(path=Path(self._dir.name) / "recents.json")

    def tearDown(self):
        self._dir.cleanup()

    def test_menu_matches_the_planned_layout(self):
        for name, city in (("CH#12", "Zurich"), ("DE#42", "Berlin"), ("AT#171", "Vienna")):
            self.store.record(name, city=city)

        indicator = make_indicator(connected=True, recents=self.store)
        indicator._build_menu()
        labels = indicator._tray.labels

        self.assertEqual(labels[0], "↓ 139 KB/s   ↑ 105 KB/s   ·   3.4 GB total")
        self.assertEqual(labels[1], "Disconnect")
        self.assertEqual(labels[2], "Quick connect (Fastest)")
        self.assertEqual(labels[3:6], ["Vienna - AT#171", "Berlin - DE#42", "Zurich - CH#12"])
        self.assertEqual(labels[-2], "Open Unofficial Proton VPN")
        self.assertIn("Quit", labels[-1])
        indicator.teardown()

    def test_open_entry_is_offered_even_when_the_window_is_visible(self):
        indicator = make_indicator(recents=self.store)
        indicator._main_window.get_visible.return_value = True
        indicator._build_menu()
        self.assertIn("Open Unofficial Proton VPN", indicator._tray.labels)
        self.assertNotIn("Hide", indicator._tray.labels)
        indicator.teardown()

    def test_open_entry_presents_the_window(self):
        indicator = make_indicator(recents=self.store)
        indicator._build_menu()
        entry = next(i for i in indicator._tray.menu_items
                     if i.label == "Open Unofficial Proton VPN")
        entry.callback()
        indicator._main_window.set_visible.assert_called_once_with(True)
        indicator._main_window.present.assert_called_once()
        indicator.teardown()

    def test_stats_line_is_not_clickable(self):
        indicator = make_indicator(recents=self.store)
        indicator._build_menu()
        self.assertFalse(indicator._tray.menu_items[0].enabled)
        indicator.teardown()

    def test_only_three_recents_are_listed(self):
        for i in range(10):
            self.store.record(f"AT#{i}", city="Vienna")
        indicator = make_indicator(recents=self.store)
        indicator._build_menu()
        recent_labels = [l for l in indicator._tray.labels if l.startswith("Vienna")]
        self.assertEqual(len(recent_labels), 3)
        indicator.teardown()

    def test_disconnect_hidden_when_not_connected(self):
        indicator = make_indicator(connected=False, recents=self.store)
        indicator._build_menu()
        labels = indicator._tray.labels
        self.assertNotIn("Disconnect", labels)
        self.assertIn("Quick connect (Fastest)", labels)
        self.assertEqual(labels[0], "Disconnected")
        indicator.teardown()

    def test_logged_out_shows_only_window_and_quit(self):
        indicator = make_indicator(logged_in=False, recents=self.store)
        indicator._build_menu()
        labels = indicator._tray.labels
        self.assertNotIn("Quick connect (Fastest)", labels)
        self.assertEqual(len(labels), 2)  # Show + Quit
        indicator.teardown()

    def test_recent_entry_connects_to_that_server(self):
        self.store.record("AT#171", city="Vienna")
        indicator = make_indicator(recents=self.store)
        indicator._build_menu()
        entry = next(i for i in indicator._tray.menu_items if i.label == "Vienna - AT#171")
        entry.callback()
        indicator._controller.connect_from_tray.assert_called_once_with("AT#171")
        indicator.teardown()

    def test_broken_menu_falls_back_to_stock_menu(self):
        indicator = make_indicator(recents=self.store)
        indicator._add_stats_line = MagicMock(side_effect=RuntimeError("upstream moved"))
        indicator._build_menu()  # must not raise
        # Proton's own menu builder ran instead.
        self.assertTrue(indicator._tray.labels)
        indicator.teardown()


class RecentsRecordingTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.store = RecentsStore(path=Path(self._dir.name) / "recents.json")
        self.indicator = make_indicator(recents=self.store)

    def tearDown(self):
        self.indicator.teardown()
        self._dir.cleanup()

    def _connected_state(self, server_name="AT#171"):
        state = MagicMock()
        type(state).__name__ = "Connected"
        state.context.connection.server_name = server_name
        return state

    def test_records_server_with_metadata_on_connect(self):
        logical = SimpleNamespace(
            location="Vienna", exit_country="AT",
            features=[SimpleNamespace(name="SECURE_CORE")])
        self.indicator._controller.server_list.get_by_name.return_value = logical

        self.indicator._remember_server(self._connected_state())

        entry = self.store.servers[0]
        self.assertEqual(entry.server_name, "AT#171")
        self.assertEqual(entry.city, "Vienna")
        self.assertEqual(entry.exit_country, "AT")
        self.assertTrue(entry.is_secure_core)

    def test_records_name_only_when_server_list_unavailable(self):
        self.indicator._controller.server_list.get_by_name.side_effect = RuntimeError
        self.indicator._remember_server(self._connected_state("DE#42"))
        self.assertEqual(self.store.servers[0].server_name, "DE#42")

    def test_repeated_connected_events_count_as_one_connection(self):
        """Proton emits Connected more than once per connection."""
        self.indicator._controller.server_list.get_by_name.return_value = None
        state = self._connected_state("AT#215")
        self.indicator._remember_server(state)
        self.indicator._remember_server(state)
        self.indicator._remember_server(state)

        self.assertEqual(len(self.store.servers), 1)
        self.assertEqual(self.store.servers[0].use_count, 1)

    def test_reconnecting_after_a_disconnect_counts_again(self):
        self.indicator._controller.server_list.get_by_name.return_value = None
        self.indicator._remember_server(self._connected_state("AT#215"))

        disconnected = MagicMock()
        type(disconnected).__name__ = "Disconnected"
        self.indicator._remember_server(disconnected)

        self.indicator._remember_server(self._connected_state("AT#215"))
        self.assertEqual(self.store.servers[0].use_count, 2)

    def test_switching_server_records_both(self):
        self.indicator._controller.server_list.get_by_name.return_value = None
        self.indicator._remember_server(self._connected_state("AT#215"))
        self.indicator._remember_server(self._connected_state("DE#42"))
        self.assertEqual([s.server_name for s in self.store.servers], ["DE#42", "AT#215"])

    def test_ignores_states_other_than_connected(self):
        state = MagicMock()
        type(state).__name__ = "Connecting"
        self.indicator._remember_server(state)
        self.assertEqual(self.store.servers, [])

    def test_status_update_never_raises_even_if_recents_break(self):
        self.indicator._recents = MagicMock()
        self.indicator._recents.record.side_effect = OSError("disk full")
        self.indicator._controller.server_list.get_by_name.return_value = None
        self.indicator.status_update(self._connected_state())  # must not raise


class PollTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.store = RecentsStore(path=Path(self._dir.name) / "recents.json")

    def tearDown(self):
        self._dir.cleanup()

    def test_poll_does_not_run_while_disconnected(self):
        indicator = make_indicator(connected=False, recents=self.store)
        indicator._build_menu()
        self.assertIsNone(indicator._poll_source_id, "no timer while disconnected")

    def test_poll_runs_while_connected(self):
        indicator = make_indicator(connected=True, recents=self.store)
        indicator._build_menu()
        self.assertIsNotNone(indicator._poll_source_id)
        indicator.teardown()
        self.assertIsNone(indicator._poll_source_id)

    def test_unchanged_label_emits_no_dbus_signal(self):
        same = TrafficSample(down_rate=1000, up_rate=1000, total=5000, connected=True)
        indicator = make_indicator(
            connected=True, recents=self.store,
            meter=StubMeter([same, same, same]))
        indicator._build_menu()
        before = indicator._tray.update_calls

        self.assertTrue(indicator._on_poll_tick())
        self.assertEqual(indicator._tray.update_calls, before,
                         "identical label must not emit LayoutUpdated")
        indicator.teardown()

    def test_changed_label_emits_one_dbus_signal(self):
        indicator = make_indicator(
            connected=True, recents=self.store,
            meter=StubMeter([
                TrafficSample(down_rate=1000, up_rate=1000, total=5000, connected=True),
                TrafficSample(down_rate=9000, up_rate=1000, total=9000, connected=True),
            ]))
        indicator._build_menu()
        before = indicator._tray.update_calls

        self.assertTrue(indicator._on_poll_tick())
        self.assertEqual(indicator._tray.update_calls, before + 1)
        self.assertIn("9.0 KB/s", indicator._tray.menu_items[0].label)
        indicator.teardown()

    def test_poll_stops_itself_when_the_tunnel_goes_away(self):
        indicator = make_indicator(
            connected=True, recents=self.store,
            meter=StubMeter([
                TrafficSample(down_rate=1000, up_rate=1000, total=5000, connected=True),
                TrafficSample(connected=False),
            ]))
        indicator._build_menu()
        self.assertFalse(indicator._on_poll_tick(), "poll should stop")
        self.assertEqual(indicator._tray.menu_items[0].label, "Disconnected")


if __name__ == "__main__":
    unittest.main(verbosity=2)
