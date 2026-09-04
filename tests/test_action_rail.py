"""Tests for the action rail."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unofficial_protonvpn.widgets.action_rail import (  # noqa: E402
    AUTOCONNECT_FASTEST, AUTOCONNECT_SETTING, KILLSWITCH_SETTING,
    NETSHIELD_SETTING, PROTOCOL_DESCRIPTIONS, PROTOCOL_ORDER, PROTOCOL_SETTING,
    SPLIT_TUNNELING_SETTING, ActionRail,
)


def protocol(name, label=None):
    return SimpleNamespace(protocol=name, ui_protocol=label or name)


def make_rail(netshield=0, killswitch=0, proto="wireguard", split=False,
              autoconnect=None,
              available=(("wireguard", "WireGuard"),
                         ("openvpn-udp", "OpenVPN (UDP)"))):
    controller = MagicMock()
    values = {NETSHIELD_SETTING: netshield, KILLSWITCH_SETTING: killswitch,
              PROTOCOL_SETTING: proto, SPLIT_TUNNELING_SETTING: split,
              AUTOCONNECT_SETTING: autoconnect}
    controller.get_setting_attr.side_effect = lambda name: values[name]

    def protocols(group):
        # Only the generic group carries them in these tests.
        return [protocol(n, l) for n, l in available] if group == "generic" else []
    controller.get_available_protocols.side_effect = protocols
    rail = ActionRail(controller, MagicMock())
    rail._refresh_state_on_main_thread()   # idle_add would not run without a loop
    return rail, controller, values


class RailContentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def test_rail_actions_in_order(self):
        rail, _controller, _values = make_rail()
        labels = []
        child = rail.get_first_child()
        while child is not None:
            labels.append(child.label_text)
            child = child.get_next_sibling()
        self.assertEqual(labels, ["Auto connect", "NetShield", "Kill switch",
                                  "Split tunneling", "Protocol", "Settings"],
                         "Auto connect sits at the top of the quick bar")

    def test_port_forwarding_is_not_in_the_quick_bar(self):
        """It is rarely changed; it lives in their settings panel."""
        rail, _c, _v = make_rail()
        child = rail.get_first_child()
        while child is not None:
            self.assertNotIn("port", child.label_text.lower())
            child = child.get_next_sibling()


class AutoconnectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def test_shows_off_when_unset(self):
        rail, _c, _v = make_rail(autoconnect=None)
        self.assertEqual(rail.autoconnect_button.state.get_text(), "Off")

    def test_shows_fastest_and_pinned_targets(self):
        rail, _c, _v = make_rail(autoconnect="FASTEST")
        self.assertEqual(rail.autoconnect_button.state.get_text(), "Fastest")

        rail, _c, _v = make_rail(autoconnect="DE")
        self.assertEqual(rail.autoconnect_button.state.get_text(), "Germany",
                         "country codes are shown as names")

        rail, _c, _v = make_rail(autoconnect="DE#667")
        self.assertEqual(rail.autoconnect_button.state.get_text(), "DE#667")

    def test_offers_the_current_country_and_server_when_connected(self):
        rail, _c, _v = make_rail()
        rail.set_connection(True, country="de", server="DE#667")

        offered = {}
        rail._show_menu = lambda button, entries, current, on_chosen, descriptions=None: \
            offered.update({"entries": entries})
        rail.autoconnect_button.emit("clicked")

        values = [value for value, _label in offered["entries"]]
        labels = [label for _value, label in offered["entries"]]
        self.assertEqual(values[:2], ["", AUTOCONNECT_FASTEST])
        self.assertIn("DE", values, "the stored value stays the country code")
        self.assertIn("DE#667", values)
        self.assertIn("Germany", labels, "but the user sees the country name")

    def test_offers_only_off_and_fastest_when_disconnected(self):
        rail, _c, _v = make_rail()
        rail.set_connection(False)
        offered = {}
        rail._show_menu = lambda button, entries, current, on_chosen, descriptions=None: \
            offered.update({"entries": entries})
        rail.autoconnect_button.emit("clicked")
        self.assertEqual([v for v, _l in offered["entries"]], ["", AUTOCONNECT_FASTEST])

    def test_choosing_off_saves_none_not_an_empty_string(self):
        """Their own field treats None as off; an empty string is not the same."""
        rail, controller, _v = make_rail(autoconnect="FASTEST")
        rail._on_autoconnect_chosen("")
        controller.save_setting_attr.assert_called_once_with(AUTOCONNECT_SETTING, None)

    def test_the_hover_text_explains_every_option(self):
        rail, _c, _v = make_rail()
        rail.set_connection(True, country="de", server="DE#667")
        rail._refresh_state_on_main_thread()

        tooltip = rail.autoconnect_button.get_tooltip_text()
        self.assertIn("when the app starts", tooltip)
        for expected in ("Off", "Fastest country", "Germany", "DE#667"):
            self.assertIn(expected, tooltip, f"{expected} is not explained")

    def test_the_hover_text_says_how_to_get_the_pinned_options(self):
        """Disconnected, only two options exist - say why."""
        rail, _c, _v = make_rail()
        rail.set_connection(False)
        rail._refresh_state_on_main_thread()

        tooltip = rail.autoconnect_button.get_tooltip_text()
        self.assertIn("Connect somewhere", tooltip)

    def test_choosing_fastest_saves_it(self):
        rail, controller, _v = make_rail()
        rail._on_autoconnect_chosen(AUTOCONNECT_FASTEST)
        controller.save_setting_attr.assert_called_once_with(
            AUTOCONNECT_SETTING, AUTOCONNECT_FASTEST)


class ToggleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def test_netshield_shows_its_three_levels(self):
        """Linux NetShield has Off / Malware / Ads+malware - not on-off."""
        for level, shown in ((0, "Off"), (1, "Malware"), (2, "Ads + malware")):
            with self.subTest(level=level):
                rail, _c, _v = make_rail(netshield=level)
                self.assertEqual(rail.netshield_button.state.get_text(), shown)

    def test_netshield_offers_every_level(self):
        rail, _c, _v = make_rail(netshield=0)
        offered = {}
        rail._show_menu = lambda button, entries, current, on_chosen, descriptions=None: \
            offered.update({"entries": entries, "current": current})
        rail.netshield_button.emit("clicked")
        self.assertEqual([label for _v, label in offered["entries"]],
                         ["Off", "Block Malware", "Block ads, trackers and malware"])
        self.assertEqual(offered["current"], "0")

    def test_choosing_a_netshield_level_saves_it(self):
        rail, controller, _v = make_rail(netshield=0)
        chosen = {}
        rail._show_menu = lambda button, entries, current, on_chosen, descriptions=None: \
            chosen.update({"pick": on_chosen})
        rail.netshield_button.emit("clicked")
        chosen["pick"]("2")
        controller.save_setting_attr.assert_called_once_with(NETSHIELD_SETTING, 2)

    def test_killswitch_shows_its_three_levels(self):
        for level, shown in ((0, "Off"), (1, "Standard"), (2, "Advanced")):
            with self.subTest(level=level):
                rail, _c, _v = make_rail(killswitch=level)
                self.assertEqual(rail.killswitch_button.state.get_text(), shown)

    def test_killswitch_offers_all_three_levels(self):
        rail, _c, _v = make_rail(killswitch=1)
        offered = {}
        rail._show_menu = lambda button, entries, current, on_chosen, descriptions=None: \
            offered.update({"entries": entries, "current": current})
        rail.killswitch_button.emit("clicked")
        self.assertEqual([label for _v, label in offered["entries"]],
                         ["Off", "Standard", "Advanced"])
        self.assertEqual(offered["current"], "1")

    def test_choosing_advanced_killswitch_saves_it(self):
        rail, controller, _v = make_rail(killswitch=0)
        picked = {}
        rail._show_menu = lambda button, entries, current, on_chosen, descriptions=None: \
            picked.update({"pick": on_chosen})
        rail.killswitch_button.emit("clicked")
        picked["pick"]("2")
        controller.save_setting_attr.assert_called_once_with(KILLSWITCH_SETTING, 2)

    def test_every_killswitch_level_is_explained(self):
        from unofficial_protonvpn.widgets.action_rail import (
            KILLSWITCH_DESCRIPTIONS, KILLSWITCH_LEVELS,
        )
        for value, _label in KILLSWITCH_LEVELS:
            self.assertIn(str(value), KILLSWITCH_DESCRIPTIONS)

    def test_state_label_updates_after_a_change(self):
        rail, controller, values = make_rail(netshield=0)

        def save(name, value):
            values[name] = value
        controller.save_setting_attr.side_effect = save

        rail._write_and_refresh(NETSHIELD_SETTING, 2)
        self.assertEqual(rail.netshield_button.state.get_text(), "Ads + malware")

    def test_split_tunnelling_is_a_real_toggle(self):
        rail, _c, _v = make_rail(split=False)
        self.assertEqual(rail.split_button.state.get_text(), "Off")

        rail, _c, _v = make_rail(split=True)
        self.assertEqual(rail.split_button.state.get_text(), "On")

    def test_split_tunnelling_can_be_switched_on(self):
        rail, controller, _v = make_rail(split=False)
        rail._on_split_chosen("on")
        controller.save_setting_attr.assert_called_once_with(
            SPLIT_TUNNELING_SETTING, True)

    def test_split_tunnelling_configure_opens_settings(self):
        rail, controller, _v = make_rail(split=True)
        with patch.object(ActionRail, "open_settings") as open_settings:
            rail._on_split_chosen("configure")
        open_settings.assert_called_once()
        controller.save_setting_attr.assert_not_called()

    def test_unreadable_settings_fall_back_to_the_settings_window(self):
        controller = MagicMock()
        controller.get_setting_attr.side_effect = RuntimeError("settings unavailable")
        rail = ActionRail(controller, MagicMock())

        with patch.object(ActionRail, "open_settings") as open_settings:
            rail.netshield_button.emit("clicked")
            rail.killswitch_button.emit("clicked")

        self.assertEqual(open_settings.call_count, 2)
        controller.save_setting_attr.assert_not_called()

    def test_a_failed_save_does_not_raise(self):
        rail, controller, _v = make_rail(netshield=0)
        controller.save_setting_attr.side_effect = RuntimeError("write failed")
        rail.netshield_button.emit("clicked")  # must not raise


class ProtocolButtonTest(unittest.TestCase):
    """Not in the Windows app - switching protocol from the rail."""

    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def test_shows_the_current_protocol(self):
        """Proton's own names, not a title-cased identifier."""
        for value, shown in (("wireguard", "WireGuard"),
                             ("openvpn-udp", "OpenVPN (UDP)"),
                             ("protun-tls", "Stealth"),
                             ("protun-smart", "Smart")):
            with self.subTest(protocol=value):
                rail, _c, _v = make_rail(proto=value)
                self.assertEqual(rail.protocol_button.state.get_text(), shown)

    def test_lists_the_available_protocols_with_their_own_labels(self):
        rail, _c, _v = make_rail()
        self.assertEqual(rail._available_protocols(),
                         [("wireguard", "WireGuard"), ("openvpn-udp", "OpenVPN (UDP)")])

    def test_looks_in_both_protocol_groups(self):
        """Stealth protocols live in the 'protun' group, not 'generic'."""
        rail, controller, _v = make_rail()
        groups = {call.args[0] for call in controller.get_available_protocols.call_args_list}
        rail._available_protocols()
        groups |= {call.args[0] for call in controller.get_available_protocols.call_args_list}
        self.assertIn("generic", groups)
        self.assertIn("protun", groups)

    def test_choosing_a_protocol_saves_it(self):
        rail, controller, _v = make_rail(proto="wireguard")
        rail._write_and_refresh(PROTOCOL_SETTING, "openvpn-udp")
        controller.save_setting_attr.assert_called_once_with(
            PROTOCOL_SETTING, "openvpn-udp")

    def test_no_protocols_available_falls_back_to_settings(self):
        rail, controller, _v = make_rail(available=())
        with patch.object(ActionRail, "open_settings") as open_settings:
            rail.protocol_button.emit("clicked")
        open_settings.assert_called_once()

    def test_a_broken_protocol_list_does_not_raise(self):
        rail, controller, _v = make_rail()
        controller.get_available_protocols.side_effect = RuntimeError("gone")
        self.assertEqual(rail._available_protocols(), [])


class ProtocolOrderAndLockTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def test_protocols_come_back_in_a_sensible_order(self):
        """Whatever order the connector returns, WireGuard leads."""
        jumbled = (("protun-tls", "Stealth"), ("openvpn-tcp", "OpenVPN (TCP)"),
                   ("wireguard", "WireGuard"), ("openvpn-udp", "OpenVPN (UDP)"))
        rail, _c, _v = make_rail(available=jumbled)
        self.assertEqual([name for name, _label in rail._available_protocols()],
                         ["wireguard", "openvpn-udp", "openvpn-tcp", "protun-tls"])

    def test_unknown_protocols_are_kept_at_the_end(self):
        rail, _c, _v = make_rail(available=(("future-thing", "Future"),
                                            ("wireguard", "WireGuard")))
        names = [name for name, _label in rail._available_protocols()]
        self.assertEqual(names[0], "wireguard")
        self.assertIn("future-thing", names)

    def test_every_protocol_we_order_has_an_explanation(self):
        for name in PROTOCOL_ORDER:
            self.assertIn(name, PROTOCOL_DESCRIPTIONS,
                          f"{name} has no hover explanation")

    def test_protocol_stays_usable_while_connected(self):
        """Proton keeps the control enabled and notes the change is deferred."""
        rail, _c, _v = make_rail()
        rail.set_connected(True)

        self.assertTrue(rail.protocol_button.get_sensitive(),
                        "Proton does not disable this while connected")
        self.assertIn("next time you connect",
                      rail.protocol_button.get_tooltip_text().lower())

    def test_the_deferred_note_goes_away_once_disconnected(self):
        rail, _c, _v = make_rail()
        rail.set_connected(True)
        rail.set_connected(False)
        self.assertNotIn("next time you connect",
                         (rail.protocol_button.get_tooltip_text() or "").lower())


class HoverExplanationTest(unittest.TestCase):
    """Every rail item explains itself, as the Windows app does."""

    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def test_every_button_has_an_explanation(self):
        rail, _c, _v = make_rail()
        child = rail.get_first_child()
        while child is not None:
            self.assertTrue(child.get_tooltip_text(),
                            f"{child.label_text} has no hover explanation")
            child = child.get_next_sibling()

    def test_the_explanation_survives_a_state_change(self):
        """Showing On/Off must not replace the explanation with a label echo."""
        rail, _c, _v = make_rail(netshield=2)
        tooltip = rail.netshield_button.get_tooltip_text()
        self.assertIn("Ads + malware", tooltip)
        self.assertIn("ads, malware, and trackers", tooltip)

    def test_deferred_protocol_still_explains_itself(self):
        rail, _c, _v = make_rail()
        rail.set_connected(True)
        tooltip = rail.protocol_button.get_tooltip_text()
        self.assertIn("next time you connect", tooltip.lower())
        self.assertIn("VPN protocol determines", tooltip)


class NeverTouchesConnectionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def test_rail_never_connects_or_disconnects(self):
        """PLAN.md §2: never reimplement connection logic."""
        rail, controller, _v = make_rail()
        with patch.object(ActionRail, "open_settings"):
            for button in (rail.netshield_button, rail.killswitch_button,
                           rail.split_button, rail.settings_button):
                button.emit("clicked")

        for forbidden in ("connect_to_server", "connect_to_fastest_server",
                          "disconnect", "connect_from_tray"):
            self.assertFalse(getattr(controller, forbidden).called,
                             f"the rail must not call controller.{forbidden}")


class SettingsWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def setUp(self):
        self.rail, self.controller, _v = make_rail()
        self.window = MagicMock()
        self.module = MagicMock()
        self.module.SettingsWindow.return_value = self.window

    def test_configuring_split_tunneling_opens_protons_own_window(self):
        """The toggle is ours; choosing apps and addresses is their panel."""
        with patch.dict(sys.modules,
                        {"proton.vpn.app.gtk.widgets.headerbar.menu.settings": self.module}):
            self.rail._on_split_chosen("configure")
        self.module.SettingsWindow.assert_called_once()
        self.window.present.assert_called_once()

    def test_second_open_reuses_the_window(self):
        with patch.dict(sys.modules,
                        {"proton.vpn.app.gtk.widgets.headerbar.menu.settings": self.module}):
            self.rail.open_settings()
            self.rail.open_settings()
        self.assertEqual(self.module.SettingsWindow.call_count, 1)
        self.assertEqual(self.window.present.call_count, 2)

    def test_a_broken_settings_window_does_not_raise(self):
        self.module.SettingsWindow.side_effect = RuntimeError("upstream moved")
        with patch.dict(sys.modules,
                        {"proton.vpn.app.gtk.widgets.headerbar.menu.settings": self.module}):
            self.assertIsNone(self.rail.open_settings())


if __name__ == "__main__":
    unittest.main(verbosity=2)
