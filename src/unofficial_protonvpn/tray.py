"""
Tray quick access.

PLAN.md §6 - "best value in the project": a live traffic line, quick connect,
and the last three servers, inline, so the common actions never need the window.

    ↓ 139 KB/s   ↑ 105 KB/s   ·   3.4 GB total
    ─────────────
    Disconnect
    Quick connect (Fastest)
    ─────────────
    Vienna - AT#171
    Berlin - DE#42
    Zurich - CH#12
    ─────────────
    Open Unofficial Proton VPN
    Quit

Built on Proton's own `TrayIndicator`, whose menu API (`add_menu_item`,
`add_menu_separator`, `update_menu`) and mutable `MenuObject` make the live
line possible. Every connect/disconnect call is still theirs (PLAN.md §2:
never reimplement connection logic).

Their DBusMenu has no `AboutToShow` hook, so the poll cannot be limited to when
the menu is open. It therefore runs only while connected, and skips
`update_menu()` when the rendered line has not changed - otherwise it would
emit a DBus signal every second for nothing.
"""

from typing import List, Optional

from gi.repository import GLib

from proton.vpn import logging
from proton.vpn.app.gtk.widgets.main.tray_indicator import TrayIndicator

from .branding import APP_ICON, APP_NAME
from .recents import RecentsStore, RecentServer
from .traffic import TrafficMeter, format_stats_line

logger = logging.getLogger(__name__)


class QuickAccessTrayIndicator(TrayIndicator):
    #: Our own tray icons. Their TrayIndicator already calls change_icon() on
    #: every state change, so pointing these at our icons is all that is needed:
    #: gold when the tunnel is up, grey when it is not.
    CONNECTED_ICON = APP_ICON
    CONNECTED_ICON_DESCRIPTION = f"{APP_NAME}: connected"
    DISCONNECTED_ICON = f"{APP_ICON}-disconnected"
    DISCONNECTED_ICON_DESCRIPTION = f"{APP_NAME}: not connected"
    ERROR_ICON = f"{APP_ICON}-disconnected"
    ERROR_ICON_DESCRIPTION = f"{APP_NAME}: connection error"

    """Proton's tray indicator with a live stats line and recent servers."""

    #: §6: "a plain 1-second poll".
    POLL_INTERVAL_SECONDS = 1
    #: §6: "the last three servers listed inline".
    RECENTS_IN_MENU = 3

    DISCONNECTED_TEXT = "Disconnected"

    def __init__(self, controller, recents: Optional[RecentsStore] = None,
                 meter: Optional[TrafficMeter] = None, **kwargs):
        super().__init__(controller, **kwargs)
        self._recents = recents if recents is not None else RecentsStore()
        self._meter = meter if meter is not None else TrafficMeter()
        self._stats_item = None          # the MenuObject we mutate each tick
        self._rendered_line = None       # last label actually pushed over DBus
        self._poll_source_id = None
        self._recorded_connection = None  # server recorded for the live connection

    # -- connection status ------------------------------------------------

    def status_update(self, connection_status):
        """Record the server, then let Proton's own handling run."""
        try:
            self._remember_server(connection_status)
        except Exception:  # pylint: disable=broad-except
            # Recents are a convenience; never let them disturb a state change.
            logger.exception("Could not record recent server.")

        super().status_update(connection_status)

    def _remember_server(self, connection_status) -> None:
        """Add the connected server to our recents store."""
        if type(connection_status).__name__ != "Connected":
            # Any other state ends the current connection, so the next
            # Connected event is a genuinely new one.
            self._recorded_connection = None
            return

        connection = getattr(getattr(connection_status, "context", None),
                             "connection", None)
        server_name = getattr(connection, "server_name", None)
        if not server_name:
            return

        # Proton emits Connected more than once per connection (feature flags
        # arrive after the tunnel is up). Only the first is a new connection -
        # otherwise a single connect would count as several.
        if self._recorded_connection == server_name:
            return
        self._recorded_connection = server_name

        city, exit_country, is_secure_core = "", "", False
        try:
            logical = self._controller.server_list.get_by_name(server_name)
            if logical is not None:
                city = getattr(logical, "location", "") or ""
                exit_country = getattr(logical, "exit_country", "") or ""
                features = getattr(logical, "features", None) or []
                is_secure_core = any(
                    getattr(feature, "name", "") == "SECURE_CORE"
                    for feature in features
                )
        except Exception:  # pylint: disable=broad-except
            # Server list may not be loaded yet - the name alone is enough.
            logger.debug(f"No metadata for {server_name}; storing the name only.")

        self._recents.record(
            server_name=server_name,
            exit_country=exit_country,
            city=city,
            is_secure_core=is_secure_core,
        )

    # -- menu -------------------------------------------------------------

    def _build_menu(self):
        """Build our menu, falling back to Proton's if anything goes wrong.

        PLAN.md §7 problem #3: their refactors break us hard. A tray that
        quietly reverts to the stock menu is a far better failure than one that
        disappears.
        """
        try:
            self._build_quick_access_menu()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Falling back to the stock tray menu.")
            try:
                super()._build_menu()
            except Exception:  # pylint: disable=broad-except
                logger.exception("The stock tray menu also failed to build.")

    def _build_quick_access_menu(self):
        self._tray.menu_items.clear()
        self._stats_item = None
        self._rendered_line = None

        logged_in = self._controller.user_logged_in

        if logged_in:
            self._add_stats_line()
            self._tray.add_menu_separator()
            self._add_connection_entries()
            self._tray.add_menu_separator()
            if self._add_recent_entries():
                self._tray.add_menu_separator()

        self._add_open_window_entry()
        self._tray.add_menu_separator()
        self._setup_quit_entry()

        self._tray.update_menu()
        self._sync_poll_to_connection_state()

    def _add_stats_line(self):
        """A non-clickable line that the poll rewrites in place."""
        label = format_stats_line(self._meter.sample(), self.DISCONNECTED_TEXT)
        self._tray.add_menu_item(label, self._on_stats_line_clicked, enabled=False)
        self._stats_item = self._tray.menu_items[-1]
        self._rendered_line = label

    def _add_connection_entries(self):
        """Disconnect (when there is a connection) and Quick connect.

        Both callbacks are Proton's own - we only relabel. Their "Connect"
        already means "fastest server", so it is named for what it does.
        """
        if not self._controller.connection_disconnected:
            self._tray.add_menu_item(
                "Disconnect",
                self._on_disconnect_entry_clicked,
                enabled=self.enable_disconnect_entry is not False,
            )

        self._tray.add_menu_item(
            "Quick connect (Fastest)",
            self._on_connect_entry_clicked,
        )

    def _add_recent_entries(self) -> bool:
        """List the most recent servers. Returns whether any were added."""
        recents = self._recents.most_recent(self.RECENTS_IN_MENU)
        for server in recents:
            self._tray.add_menu_item(
                server.label,
                self._make_recent_callback(server),
            )
        return bool(recents)

    def _make_recent_callback(self, server: RecentServer):
        """Bind the server name now, not at click time."""
        name = server.server_name

        def connect():
            self._on_connect_to_pinned_entry_clicked(name)

        return connect

    def _add_open_window_entry(self):
        """Always offer to open the window, named so it is unmistakably ours.

        Proton's own entry toggles between Show and Hide, so it disappears as
        an "open" action exactly when the window is buried behind something
        else. PLAN.md §6 lists a plain "Open app" line instead.
        """
        self._tray.add_menu_item(
            f"Open {APP_NAME}",
            self._on_open_window_entry_clicked,
        )

    def _on_open_window_entry_clicked(self, *_args):
        """Show the window and bring it to the front."""
        window = self._main_window
        if window is None:
            return
        window.set_visible(True)
        window.present()

    def _on_stats_line_clicked(self, *_args):
        """The stats line is disabled, so this should never fire."""

    # -- the 1 second poll -------------------------------------------------

    def _sync_poll_to_connection_state(self):
        """Run the timer only while connected (PLAN.md §6)."""
        try:
            connected = not self._controller.connection_disconnected
        except Exception:  # pylint: disable=broad-except
            connected = False

        if connected and self._stats_item is not None:
            self._start_poll()
        else:
            self._stop_poll()

    def _start_poll(self):
        if self._poll_source_id is not None:
            return
        self._meter.reset()
        self._poll_source_id = GLib.timeout_add_seconds(
            self.POLL_INTERVAL_SECONDS, self._on_poll_tick
        )
        logger.debug("Tray traffic poll started.")

    def _stop_poll(self):
        if self._poll_source_id is None:
            return
        GLib.source_remove(self._poll_source_id)
        self._poll_source_id = None
        self._meter.reset()
        logger.debug("Tray traffic poll stopped.")

    def _on_poll_tick(self) -> bool:
        """Rewrite the stats line. Returns whether to keep polling."""
        if self._stats_item is None:
            self._poll_source_id = None
            return False

        try:
            sample = self._meter.sample()
            line = format_stats_line(sample, self.DISCONNECTED_TEXT)

            if line != self._rendered_line:
                self._stats_item.label = line
                self._rendered_line = line
                # Only now does a DBus signal go out.
                self._tray.update_menu()

            if not sample.connected:
                # The tunnel went away; stop until the next connect.
                self._poll_source_id = None
                return False
        except Exception:  # pylint: disable=broad-except
            logger.exception("Traffic poll failed; stopping it.")
            self._poll_source_id = None
            return False

        return True

    def teardown(self):
        """Stop the timer. Call before the app exits."""
        self._stop_poll()
