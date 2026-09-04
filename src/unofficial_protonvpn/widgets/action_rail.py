"""
The action rail.

PLAN.md §4: "NetShield, Kill switch, Split tunneling, Settings. Port
forwarding cut." On the right, as in the Windows reference.

NetShield and the kill switch are real toggles here: they read and write
through Proton's own `get_setting_attr` / `save_setting_attr`, the same
accessors their settings panels use, so no settings logic is reimplemented
(PLAN.md §2). Split tunnelling needs app and IP lists, so it opens their
settings window rather than pretending to be a switch; Settings does the same.

Reads of the settings go through the executor and block until it answers, so
they must only ever happen on the GTK main thread - the deadlock that froze
this app once already.
"""

from typing import Optional

from gi.repository import GLib, Gtk, Pango

from proton.vpn import logging
from proton.vpn.app.gtk.utils.safe_signal_connect import safe_signal_connect

from ..protocols import protocol_name

logger = logging.getLogger(__name__)

NETSHIELD_SETTING = "settings.features.netshield"
SPLIT_TUNNELING_SETTING = "settings.features.split_tunneling.enabled"
#: Autoconnect is an app-configuration string, not a settings toggle: unset
#: means off, "FASTEST" means the fastest server, and anything else is a
#: country code or a server name (Controller._connect_to splits on "#").
AUTOCONNECT_SETTING = "app_configuration.connect_at_app_startup"
AUTOCONNECT_FASTEST = "FASTEST"
KILLSWITCH_SETTING = "settings.killswitch"
PROTOCOL_SETTING = "settings.protocol"

#: Protocol groups their settings panel uses. "generic" is the ordinary
#: list; "protun" is the stealth/obfuscated set.
GENERIC_PROTOCOL_GROUP = "generic"
PROTUN_PROTOCOL_GROUP = "protun"

#: Preferred order for the protocol list: WireGuard first (their default and
#: fastest), then OpenVPN, then the experimental Proton protocols. Anything
#: unrecognised keeps the connector's own ordering, after these.
PROTOCOL_ORDER = (
    "wireguard", "openvpn-udp", "openvpn-tcp",
    "protun-udp", "protun-tcp", "protun-tls", "protun-smart",
)

#: Proton's own descriptions, taken from the Windows client's strings so the
#: wording is theirs rather than ours.
PROTOCOL_DESCRIPTIONS = {
    "wireguard": "State-of-the-art protocol for security and performance.",
    "openvpn-udp": (
        "Established, well-tested, and secure. OpenVPN is less "
        "battery-efficient than some other protocols."
    ),
    "openvpn-tcp": (
        "Established, well-tested, and secure. OpenVPN is reliable in poor "
        "network conditions, but may not be as fast as other protocols."
    ),
    "protun-udp": (
        "Proton's own WireGuard framework, for increased stability and "
        "censorship resistance. Experimental."
    ),
    "protun-tcp": (
        "Proton's own WireGuard framework, for increased stability and "
        "censorship resistance. Experimental."
    ),
    "protun-tls": (
        "Overcomes VPN blocks by hiding your VPN connection from censors. "
        "Resistant to deep packet inspection, but may not be as fast."
    ),
    "protun-smart": "Auto-selects the best protocol for your connection.",
}

#: Hover explanations, in Proton's own words (their Linux settings panels).
#: NetShield's blocked-ad and tracker counts are deliberately absent: the
#: Windows app shows them, but nothing in the Linux Python API exposes the
#: statistics, so there is nothing honest to display.
RAIL_DESCRIPTIONS = {
    "NetShield": (
        "Protect yourself from ads, malware, and trackers on websites and apps."
    ),
    "Kill switch": (
        "Automatically disconnect from the internet if the VPN connection is "
        "lost. Advanced (permanent) only allows internet access while connected "
        "to Proton VPN, and stays active across restarts."
    ),
    "Split tunneling": (
        "Customize your connection by deciding which apps are protected by VPN."
    ),
    "Protocol": (
        "A VPN protocol determines how data moves between a VPN server and "
        "your device."
    ),
    "Auto connect": "Connect automatically to a server when the app starts.",
    "Settings": "Open Proton VPN's settings.",
}

#: Proton allows the protocol to be changed while connected - their own
#: settings panel does not disable it - but the change only takes effect on the
#: next connection, and they say so. We say the same rather than blocking it.
PROTOCOL_RECONNECT_NOTE = "Takes effect the next time you connect."

#: NetShield's three levels on Linux, with their own labels. There is no
#: adult-content tier here - the enum only has these.
NETSHIELD_LEVELS = (
    (0, "Off"),
    (1, "Block Malware"),
    (2, "Block ads, trackers and malware"),
)

#: NetShield: off, or block ads and tracking. The middle option
#: (malware only) stays in their settings window.
NETSHIELD_OFF = 0

#: Kill switch has three states on Linux, and all three are selectable here.
KILLSWITCH_OFF = 0
KILLSWITCH_ON = 1
KILLSWITCH_PERMANENT = 2

KILLSWITCH_LEVELS = (
    (KILLSWITCH_OFF, "Off"),
    (KILLSWITCH_ON, "Standard"),
    (KILLSWITCH_PERMANENT, "Advanced"),
)

#: Proton's own wording for each level.
KILLSWITCH_DESCRIPTIONS = {
    str(KILLSWITCH_OFF): "No kill switch. Traffic is not blocked if the VPN drops.",
    str(KILLSWITCH_ON): (
        "Automatically disconnect from the internet if the VPN connection "
        "is lost."
    ),
    str(KILLSWITCH_PERMANENT): (
        "Only allow internet access when connected to Proton VPN. Advanced "
        "kill switch stays active even when you restart your device."
    ),
}


class RailButton(Gtk.Button):
    """One rail entry: an icon, a name, and the state underneath it."""

    def __init__(self, label: str, icon_name: str):
        super().__init__()
        self.add_css_class("action-rail-button")
        self.add_css_class("flat")
        self.label_text = label

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        content.set_halign(Gtk.Align.CENTER)

        self.icon = Gtk.Image.new_from_icon_name(icon_name)
        self.icon.set_pixel_size(20)
        content.append(self.icon)

        self.caption = Gtk.Label(label=label)
        self.caption.add_css_class("action-rail-caption")
        self.caption.set_wrap(True)
        self.caption.set_justify(Gtk.Justification.CENTER)
        self.caption.set_max_width_chars(9)
        self.caption.set_ellipsize(Pango.EllipsizeMode.END)
        content.append(self.caption)

        self.state = Gtk.Label(label="")
        self.state.add_css_class("action-rail-state")
        self.state.set_visible(False)
        # A long value must never widen the rail and steal the map's width.
        # Wrap rather than ellipsize: "Ads + malware" reads fine on two lines
        # and truncating it to "Ads + mal..." tells the user nothing.
        self.state.set_wrap(True)
        self.state.set_justify(Gtk.Justification.CENTER)
        self.state.set_max_width_chars(10)
        self.state.set_ellipsize(Pango.EllipsizeMode.END)
        self.state.set_lines(2)
        content.append(self.state)

        self.set_child(content)
        self.description = RAIL_DESCRIPTIONS.get(label, "")
        self.note = ""
        if self.description:
            self.set_tooltip_text(self.description)

    def set_note(self, note: Optional[str]) -> None:
        """An extra line on the tooltip, e.g. when a change is deferred."""
        self.note = note or ""
        self.show_state(self.state.get_text() if self.state.get_visible() else None)

    def show_state(self, text: Optional[str], active: bool = False):
        """Display 'On'/'Off' under the name, or nothing for plain actions."""
        if text is None:
            self.state.set_visible(False)
            self.remove_css_class("action-rail-active")
            self.set_tooltip_text(
                "\n\n".join(p for p in (self.description, self.note) if p) or None)
            return

        self.state.set_text(text)
        self.state.set_visible(True)
        # Explanation first, current state after it - hovering should teach you
        # what the thing does, not just repeat the label.
        summary = f"{self.label_text}: {text}"
        self.set_tooltip_text(
            "\n\n".join(p for p in (summary, self.description, self.note) if p))
        if active:
            self.add_css_class("action-rail-active")
        else:
            self.remove_css_class("action-rail-active")


class ActionRail(Gtk.Box):
    """A narrow column of actions down the right-hand edge."""

    WIDTH = 84

    def __init__(self, controller, main_window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._controller = controller
        self._main_window = main_window
        self._settings_window = None
        self._connected = False
        self._connected_country = ""
        self._connected_server = ""

        self.add_css_class("action-rail")
        self.set_size_request(self.WIDTH, -1)
        self.set_hexpand(False)
        self.set_halign(Gtk.Align.END)
        # Placement is decided where it is added to the overlay; keep the
        # widget itself neutral so the two do not fight.
        self.set_margin_top(0)
        self.set_margin_bottom(0)

        self.autoconnect_button = RailButton("Auto connect", "media-playlist-repeat-symbolic")
        self.autoconnect_button.connect("clicked", self._on_autoconnect_clicked)
        self.append(self.autoconnect_button)

        self.netshield_button = RailButton("NetShield", "security-high-symbolic")
        self.netshield_button.connect("clicked", self._on_netshield_clicked)
        self.append(self.netshield_button)

        self.killswitch_button = RailButton("Kill switch", "network-offline-symbolic")
        self.killswitch_button.connect("clicked", self._on_killswitch_clicked)
        self.append(self.killswitch_button)

        self.split_button = RailButton("Split tunneling", "network-workgroup-symbolic")
        self.split_button.connect("clicked", self._on_split_clicked)
        self.append(self.split_button)

        # Not in the Windows app: switching protocol is buried in settings there,
        # and it is something you actually reach for. Sits between split
        # tunnelling and settings, where it was asked for.
        self.protocol_button = RailButton("Protocol", "network-transmit-receive-symbolic")
        self.protocol_button.connect("clicked", self._on_protocol_clicked)
        self.append(self.protocol_button)

        self.settings_button = RailButton("Settings", "emblem-system-symbolic")
        self.settings_button.connect("clicked", lambda *_: self.open_settings())
        self.append(self.settings_button)

        self.refresh_state()

    # -- reading and writing settings -------------------------------------

    def _read(self, setting: str):
        """Read one setting. Main thread only - this blocks on the executor."""
        try:
            return self._controller.get_setting_attr(setting)
        except Exception:  # pylint: disable=broad-except
            logger.exception(f"Could not read {setting}.")
            return None

    def _write(self, setting: str, value) -> bool:
        try:
            self._controller.save_setting_attr(setting, value)
            return True
        except Exception:  # pylint: disable=broad-except
            logger.exception(f"Could not save {setting}.")
            return False

    def refresh_state(self) -> bool:
        """Update the On/Off labels from the current settings.

        Safe to call from any thread: the work is handed to the main loop.
        """
        GLib.idle_add(self._refresh_state_on_main_thread)
        return GLib.SOURCE_REMOVE

    def _refresh_state_on_main_thread(self) -> bool:
        netshield = self._read(NETSHIELD_SETTING)
        if netshield is None:
            self.netshield_button.show_state(None)
        else:
            level = int(netshield)
            short = {0: "Off", 1: "Malware", 2: "Ads + malware"}.get(level, "On")
            self.netshield_button.show_state(short, active=level != NETSHIELD_OFF)

        autoconnect = self._read(AUTOCONNECT_SETTING)
        self.autoconnect_button.description = self._autoconnect_description()
        self.autoconnect_button.show_state(
            self._autoconnect_label(autoconnect), active=bool(autoconnect))

        split = self._read(SPLIT_TUNNELING_SETTING)
        if split is None:
            self.split_button.show_state(None)
        else:
            self.split_button.show_state("On" if split else "Off", active=bool(split))

        killswitch = self._read(KILLSWITCH_SETTING)
        if killswitch is None:
            self.killswitch_button.show_state(None)
        else:
            value = int(killswitch)
            label = dict(KILLSWITCH_LEVELS).get(value, "On")
            self.killswitch_button.show_state(label, active=value != KILLSWITCH_OFF)

        protocol = self._read(PROTOCOL_SETTING)
        self.protocol_button.show_state(
            self._protocol_label(protocol) if protocol else None)

        return GLib.SOURCE_REMOVE

    # -- protocol ----------------------------------------------------------

    @staticmethod
    def _protocol_label(protocol) -> str:
        """The name to show on the rail: "Smart", not "Protun-Smart"."""
        return protocol_name(protocol, short=True) or "-"

    def _available_protocols(self):
        """Every protocol the connector offers, as (value, label) pairs.

        Both groups: "generic" is WireGuard and OpenVPN, "protun" is the
        stealth set. Labels come from each class's own `ui_protocol`, so they
        read exactly as they do in Proton's own settings.
        """
        seen = {}
        for group in (GENERIC_PROTOCOL_GROUP, PROTUN_PROTOCOL_GROUP):
            try:
                protocols = self._controller.get_available_protocols(group)
            except Exception:  # pylint: disable=broad-except
                logger.debug(f"No protocols in group {group}.")
                continue

            for protocol in protocols or []:
                name = getattr(protocol, "protocol", None)
                if not name or str(name) in seen:
                    continue
                label = getattr(protocol, "ui_protocol", None) or self._protocol_label(name)
                seen[str(name)] = str(label)

        def rank(item):
            name = item[0]
            return (PROTOCOL_ORDER.index(name)
                    if name in PROTOCOL_ORDER else len(PROTOCOL_ORDER))

        return sorted(seen.items(), key=rank)

    def _write_and_refresh(self, setting: str, value) -> None:
        """Save a setting and bring the rail's labels up to date."""
        if self._write(setting, value):
            self._refresh_state_on_main_thread()

    def _show_menu(self, button, entries, current, on_chosen, descriptions=None):
        """A small popover of choices hanging off a rail button.

        `entries` is a list of (value, label); `current` is the value to mark.
        """
        # A popover needs a real toplevel to attach to. Popping one up from a
        # widget that is not in a window crashes GTK outright, so refuse rather
        # than take the process down with us.
        if button.get_root() is None:
            logger.warning("Not showing a menu: the button is not in a window.")
            return None

        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        menu.add_css_class("protocol-menu")

        popover = Gtk.Popover()
        popover.set_child(menu)
        popover.set_parent(button)

        for value, label in entries:
            entry = Gtk.Button(label=label)
            entry.add_css_class("flat")
            entry.add_css_class("protocol-menu-item")
            if descriptions and descriptions.get(value):
                entry.set_tooltip_text(descriptions[value])
            if value == current:
                entry.add_css_class("protocol-menu-item-current")

            def chosen(_button, value=value):
                popover.popdown()
                on_chosen(value)

            entry.connect("clicked", chosen)
            menu.append(entry)

        popover.popup()
        return popover

    def set_connection(self, connected: bool, country: str = "",
                       server: str = "") -> None:
        """Remember what we are connected to, so autoconnect can offer it."""
        self._connected_country = (country or "").upper()
        self._connected_server = server or ""
        self.set_connected(connected)

    def set_connected(self, connected: bool) -> None:
        """Note that a protocol change waits for the next connection.

        Proton's own settings panel keeps the control enabled while connected
        and notifies that the change needs a new connection, so we do the same
        rather than greying it out.
        """
        self._connected = bool(connected)
        self.protocol_button.set_sensitive(True)
        self.protocol_button.set_note(
            PROTOCOL_RECONNECT_NOTE if self._connected else None)

    def _on_protocol_clicked(self, button):
        """Offer the available protocols, and switch to the chosen one."""
        entries = self._available_protocols()
        if not entries:
            self.open_settings()
            return

        current = self._read(PROTOCOL_SETTING)
        self._show_menu(
            button, entries, current=str(current) if current else "",
            on_chosen=lambda name: self._write_and_refresh(PROTOCOL_SETTING, name),
            descriptions=PROTOCOL_DESCRIPTIONS,
        )

    # -- actions -----------------------------------------------------------

    def _on_netshield_clicked(self, button):
        """Offer NetShield's three levels, as their settings panel does."""
        current = self._read(NETSHIELD_SETTING)
        if current is None:
            self.open_settings()
            return

        self._show_menu(
            button,
            [(str(value), label) for value, label in NETSHIELD_LEVELS],
            current=str(int(current)),
            on_chosen=lambda value: self._write_and_refresh(
                NETSHIELD_SETTING, int(value)),
        )

    @staticmethod
    def _country_name(country_code: str) -> str:
        """'DE' -> 'Germany'. Falls back to the code if we cannot translate."""
        if not country_code:
            return ""
        try:
            from proton.vpn.app.gtk.utils.country import get_localized_country_name
            return get_localized_country_name(country_code) or country_code
        except Exception:  # pylint: disable=broad-except
            return country_code

    def _autoconnect_description(self) -> str:
        """Explain each option, using the live country and server when we can.

        The last two entries only exist while connected, so the hover text
        names them concretely rather than talking about "a country".
        """
        lines = [RAIL_DESCRIPTIONS["Auto connect"], ""]
        lines.append("Off \u2014 start without connecting.")
        lines.append("Fastest country \u2014 the quickest server available.")

        if self._connected_country:
            country = self._country_name(self._connected_country)
            lines.append(f"{country} \u2014 any server in that country.")
        if self._connected_server:
            lines.append(f"{self._connected_server} \u2014 that exact server.")

        if not self._connected_country and not self._connected_server:
            lines.append("Connect somewhere to also pin that country or server.")

        return "\n".join(lines)

    def _autoconnect_label(self, value) -> str:
        """How the current autoconnect target reads on the rail.

        Country codes are shown as country names - the stored value stays the
        code, because that is what their Controller connects with.
        """
        if not value:
            return "Off"
        text = str(value)
        if text.upper() == AUTOCONNECT_FASTEST:
            return "Fastest"
        if "#" in text:
            return text          # a server name reads fine as-is
        return self._country_name(text)

    def _on_autoconnect_clicked(self, button):
        """Choose what to connect to when the app starts."""
        current = self._read(AUTOCONNECT_SETTING)
        current_value = "" if not current else str(current)

        entries = [("", "Off"), (AUTOCONNECT_FASTEST, "Fastest country")]
        # Offer whatever we are on right now, so pinning it is one click.
        if self._connected_country:
            entries.append((self._connected_country,
                            self._country_name(self._connected_country)))
        if self._connected_server:
            entries.append((self._connected_server, self._connected_server))

        self._show_menu(
            button, entries, current=current_value,
            on_chosen=self._on_autoconnect_chosen,
        )

    def _on_autoconnect_chosen(self, value: str):
        # Their own entry field treats an empty value as off by saving None.
        self._write_and_refresh(AUTOCONNECT_SETTING, value or None)

    def _on_split_clicked(self, button):
        """Turn split tunnelling on or off, or open settings to configure it.

        The toggle is ours to flip; choosing *which* apps and addresses to
        exclude needs their panel, so that stays a menu entry.
        """
        current = self._read(SPLIT_TUNNELING_SETTING)
        if current is None:
            self.open_settings()
            return

        enabled = bool(current)
        self._show_menu(
            button,
            [("off", "Off"), ("on", "On"), ("configure", "Configure\u2026")],
            current="on" if enabled else "off",
            on_chosen=self._on_split_chosen,
        )

    def _on_split_chosen(self, value: str):
        if value == "configure":
            self.open_settings()
            return
        self._write_and_refresh(SPLIT_TUNNELING_SETTING, value == "on")

    def _on_killswitch_clicked(self, button):
        """Offer all three kill switch levels: Off, Standard, Advanced."""
        current = self._read(KILLSWITCH_SETTING)
        if current is None:
            self.open_settings()
            return

        self._show_menu(
            button,
            [(str(value), label) for value, label in KILLSWITCH_LEVELS],
            current=str(int(current)),
            on_chosen=lambda value: self._write_and_refresh(
                KILLSWITCH_SETTING, int(value)),
            descriptions=KILLSWITCH_DESCRIPTIONS,
        )

    def open_settings(self) -> Optional[Gtk.Window]:
        """Open Proton's settings window, mirroring their own menu handler."""
        if self._settings_window is not None:
            self._settings_window.present()
            return self._settings_window

        try:
            from proton.vpn.app.gtk.widgets.headerbar.menu.settings import SettingsWindow

            tray_indicator = None
            application = getattr(self._main_window, "application", None)
            if application is not None:
                tray_indicator = getattr(application, "tray_indicator", None)

            window = SettingsWindow(self._controller, tray_indicator)
            window.set_transient_for(self._main_window)
            safe_signal_connect(window, "unrealize", self._on_settings_closed)
            window.present()
            self._settings_window = window
            return window
        except Exception:  # pylint: disable=broad-except
            logger.exception("Could not open the settings window.")
            return None

    def _on_settings_closed(self, *_args):
        self._settings_window = None
        # Settings may have changed in there; catch up.
        self.refresh_state()
