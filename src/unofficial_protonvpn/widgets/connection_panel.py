"""
The centre connection block.

PLAN.md §4: "country name + flag, server ID beneath (`Vienna - AT#212`),
Connect/Disconnect button, `Protected • 1 hr 30 min` status line".

This is ours rather than Proton's `VPNConnectionStatusWidget`. Theirs is built
for their 450px single-column window: it lays its children out across whatever
width it is given, so in our wider column the country name ends up stranded
against the left edge, and constraining it makes it draw outside its own
allocation. Every alignment fix fought it. Owning the ~120 lines is simpler
than bending a widget that wants a different window.

What stays Proton's: the flag icons, and every connect/disconnect call
(PLAN.md §2 - never reimplement connection logic).
"""

import time
from typing import Optional

from gi.repository import GLib, Gtk

from proton.vpn import logging

from ..futures import report_failure

logger = logging.getLogger(__name__)


def format_duration(seconds: float) -> str:
    """'1 hr 30 min', as the Windows app writes it."""
    seconds = max(int(seconds), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours and minutes:
        return f"{hours} hr {minutes} min"
    if hours:
        return f"{hours} hr"
    if minutes:
        return f"{minutes} min"
    return "just now"


class ConnectionStatusLine(Gtk.Box):
    """The "Protected • 1 hr 30 min" line.

    Lives at the bottom of the window, above the stats, as in the Windows app -
    hence a widget of its own rather than part of the connection block.
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.add_css_class("connection-status-line")

        self.icon = Gtk.Image.new_from_icon_name("changes-prevent-symbolic")
        self.icon.set_pixel_size(16)
        self.append(self.icon)

        # Shown instead of the padlock while a connection is being made, so it
        # is obvious something is happening rather than the window sitting
        # still and then suddenly showing a country.
        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(16, 16)
        self.spinner.set_visible(False)
        self.append(self.spinner)

        self.label = Gtk.Label(label="")
        self.label.add_css_class("connection-status")
        self.label.set_xalign(0)
        self.append(self.label)

    def set_locked(self, locked: bool) -> None:
        """Closed padlock when protected, open when not."""
        self.icon.set_from_icon_name(
            "changes-prevent-symbolic" if locked else "changes-allow-symbolic")

    def set_busy(self, busy: bool) -> None:
        """Spin instead of showing a padlock while connecting."""
        self.icon.set_visible(not busy)
        self.spinner.set_visible(busy)
        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()


class ConnectionPanel(Gtk.Box):
    """Flag, country, server, button and status line - centred."""

    def __init__(self, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self._controller = controller
        self._connected_since: Optional[float] = None
        self._tick_source: Optional[int] = None
        self._state_name = "Disconnected"

        self.add_css_class("connection-block")
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.START)

        self._flag_holder = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._flag_holder.set_halign(Gtk.Align.CENTER)

        self._flag: Optional[Gtk.Widget] = None
        self.country_label = Gtk.Label(label="Not connected")
        self.country_label.add_css_class("connection-country")
        self._flag_holder.append(self.country_label)
        self.append(self._flag_holder)

        self.server_label = Gtk.Label(label="")
        self.server_label.add_css_class("connection-server")
        self.server_label.set_halign(Gtk.Align.CENTER)
        self.append(self.server_label)

        self.button = Gtk.Button(label="Connect")
        self.button.add_css_class("connection-button")
        self.button.add_css_class("connect")
        self.button.set_halign(Gtk.Align.CENTER)
        self.button.connect("clicked", self._on_button_clicked)
        self.append(self.button)

        # The status line is a separate widget: the Windows app puts it at the
        # bottom of the window above the stats, not under the button.
        self.status_line = ConnectionStatusLine()
        self.status_label = self.status_line.label

        self.show_disconnected()

    # -- state -------------------------------------------------------------

    def status_update(self, connection_state) -> None:
        """Follow the connection. Safe to call from any thread."""
        GLib.idle_add(self._apply_state, connection_state)

    def _apply_state(self, connection_state) -> bool:
        """Runs on the GTK main thread."""
        try:
            name = type(connection_state).__name__
            changed = name != self._state_name
            self._state_name = name
            if changed:
                self._flash()

            if name == "Connected":
                self._set_connecting(False)
                self.status_line.set_busy(False)
                self._show_connected(connection_state)
            elif name == "Connecting":
                # Their Windows client offers Cancel here, not Connect.
                self._show_transient("Connecting to a server", "Cancel",
                                     heading="Connecting")
            elif name == "Disconnecting":
                self._show_transient("Disconnecting", "Disconnecting",
                                     heading="Disconnecting")
            elif name == "Error":
                self.show_disconnected(status="Connection failed")
            else:
                self.show_disconnected()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Could not update the connection panel.")
            self.show_disconnected()
        return GLib.SOURCE_REMOVE

    def _show_connected(self, connection_state) -> None:
        connection = getattr(getattr(connection_state, "context", None),
                             "connection", None)
        server_name = getattr(connection, "server_name", "") or ""

        country_code, city = "", ""
        try:
            logical = self._controller.server_list.get_by_name(server_name)
            country_code = getattr(logical, "exit_country", "") or ""
            city = getattr(logical, "location", "") or ""
        except Exception:  # pylint: disable=broad-except
            logger.debug(f"No metadata for {server_name}.")

        self._set_flag(country_code)
        self.country_label.set_text(self._country_name(country_code) or server_name)
        self.server_label.set_text(
            f"{city} - {server_name}" if city and server_name else server_name)

        # Their Disconnect is a neutral secondary button that only turns red on
        # hover - deliberately not red at rest.
        self.button.set_label("Disconnect")
        self.button.remove_css_class("connect")
        self.button.add_css_class("disconnect")

        if self._connected_since is None:
            self._connected_since = time.monotonic()
        self._start_ticking()
        self._refresh_status_line()

    def _set_connecting(self, connecting: bool) -> None:
        """Breathe while a connection is being made or torn down."""
        if connecting:
            self.add_css_class("connection-block-connecting")
        else:
            self.remove_css_class("connection-block-connecting")

    def _show_transient(self, status: str, button_label: str,
                        heading: str = "") -> None:
        """Connecting or disconnecting: say so, and show it moving."""
        self._set_connecting(True)
        self.status_line.set_busy(True)

        if heading:
            self.country_label.set_text(heading)
            self.server_label.set_text("")
            self._set_flag(None)

        self.status_label.set_text(status)
        self.status_label.remove_css_class("connection-status-protected")
        self.status_label.remove_css_class("connection-status-unprotected")

        self.button.set_label(button_label)
        self._stop_ticking()

    def show_disconnected(self, status: str = "Unprotected") -> None:
        """Clear everything. Never leave a claim of protection behind."""
        self._set_connecting(False)
        self.status_line.set_busy(False)
        self._connected_since = None
        self._stop_ticking()
        self._set_flag(None)

        self.country_label.set_text("Not connected")
        self.server_label.set_text("")
        self.button.set_label("Connect")
        self.button.remove_css_class("disconnect")
        self.button.add_css_class("connect")

        self.status_label.set_text(status)
        self.status_label.remove_css_class("connection-status-protected")
        self.status_label.add_css_class("connection-status-unprotected")
        self.status_line.set_locked(False)

    def _flash(self) -> None:
        """Dip the block's opacity briefly so a state change is visible.

        CSS transitions the opacity back up, so this reads as a crossfade
        between one connection state and the next rather than a hard swap.
        """
        self.add_css_class("connection-block-changing")
        GLib.timeout_add(30, self._end_flash)

    def _end_flash(self) -> bool:
        self.remove_css_class("connection-block-changing")
        return GLib.SOURCE_REMOVE

    # -- the protected line -------------------------------------------------

    def _start_ticking(self) -> None:
        if self._tick_source is None:
            self._tick_source = GLib.timeout_add_seconds(30, self._on_tick)

    def _stop_ticking(self) -> None:
        if self._tick_source is not None:
            GLib.source_remove(self._tick_source)
            self._tick_source = None

    def _on_tick(self) -> bool:
        if self._state_name != "Connected":
            self._tick_source = None
            return False
        self._refresh_status_line()
        return True

    def _refresh_status_line(self) -> None:
        self.status_label.add_css_class("connection-status-protected")
        self.status_label.remove_css_class("connection-status-unprotected")
        self.status_line.set_locked(True)
        if self._connected_since is None:
            self.status_label.set_text("Protected")
            return
        elapsed = time.monotonic() - self._connected_since
        self.status_label.set_text(f"Protected • {format_duration(elapsed)}")

    # -- helpers ------------------------------------------------------------

    def _set_flag(self, country_code: Optional[str]) -> None:
        if self._flag is not None:
            self._flag_holder.remove(self._flag)
            self._flag = None
        if not country_code:
            return
        try:
            from proton.vpn.app.gtk.widgets.vpn.serverlist.icons import CountryFlagIcon
            flag = CountryFlagIcon(country_code)
            flag.set_valign(Gtk.Align.CENTER)
            self._flag_holder.prepend(flag)
            self._flag = flag
        except Exception:  # pylint: disable=broad-except
            logger.debug(f"No flag for {country_code}.")

    @staticmethod
    def _country_name(country_code: str) -> str:
        if not country_code:
            return ""
        try:
            from proton.vpn.app.gtk.utils.country import get_localized_country_name
            return get_localized_country_name(country_code)
        except Exception:  # pylint: disable=broad-except
            return country_code

    def _on_button_clicked(self, _button) -> None:
        """Connect or disconnect - always through their controller."""
        try:
            if self._state_name in ("Connected", "Connecting"):
                logger.info("Disconnect", category="ui.panel", event="disconnect")
                future = self._controller.disconnect()
            else:
                logger.info("Connect to fastest", category="ui.panel", event="connect")
                future = self._controller.connect_to_fastest_server()
            report_failure(future, "Connection request")
        except Exception:  # pylint: disable=broad-except
            logger.exception("Connection request failed.")

    def teardown(self) -> None:
        self._stop_ticking()
