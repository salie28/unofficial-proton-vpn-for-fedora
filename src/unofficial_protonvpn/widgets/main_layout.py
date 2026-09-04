"""
The Windows-style layout.

PLAN.md §4. Proton's `VPNWidget` stacks its children down the middle of the
window; this subclass keeps every one of those widgets - and all of their
signal wiring - and only re-parents them into three columns:

    ┌──────────────┬───────────────────────────┬──────┐
    │ sidebar      │ connection panel          │ rail │   (rail: Step 6)
    │ search       │ status                    │      │
    │ Recents      │ quick connect             │      │
    │ Countries    │ backdrop                  │      │
    │ filters      │                           │      │
    │ server list  │                           │      │
    ├──────────────┴───────────────────────────┴──────┤
    │ stats bar                                        │   (Step 5)
    └──────────────────────────────────────────────────┘

Subclassing rather than rebuilding means `load()`, `display()`,
`status_update()` and `unload()` - which Proton's own code calls into - keep
working untouched. We change where widgets sit, never what they do.
"""

from typing import List, Optional

from gi.repository import GLib, Gtk, Pango

from proton.vpn import logging
from proton.vpn.app.gtk.utils.safe_signal_connect import safe_signal_connect
from proton.vpn.app.gtk.widgets.vpn.vpn_widget import VPNWidget

from ..recents import RecentsStore
from .action_rail import ActionRail
from .backdrop import Backdrop
from .connection_panel import ConnectionPanel
from .recents_view import RecentsView
from .sidebar import RECENTS_PAGE, Sidebar
from .stats_bar import StatsBar
from .tier_notice import FreeAccountGate, TierNotice

logger = logging.getLogger(__name__)


def _walk(widget):
    """Yield every widget in the tree rooted at `widget`."""
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _walk(child)
        child = child.get_next_sibling()


class WindowsStyleVPNWidget(VPNWidget):
    """Proton's VPN widget, laid out like their Windows app."""

    #: Width of the centred connection block, in pixels.
    PANEL_WIDTH = 470

    def __init__(self, controller, main_window, notifications=None, recents=None):
        if notifications is None:
            from proton.vpn.app.gtk.widgets.main.notifications import Notifications
            notifications = Notifications
        super().__init__(controller, main_window, notifications)

        self._recents = recents if recents is not None else RecentsStore()
        self._full_server_list = None       # unfiltered, for the filter tabs
        self._displayed_user_tier = None
        self._search_query = ""

        self.recents_view = RecentsView(controller, self._recents)
        self.stats_bar = StatsBar(controller)
        self.action_rail = ActionRail(controller, main_window)
        self.tier_notice = TierNotice()
        self.free_gate = FreeAccountGate()
        self.backdrop = None
        self.connection_panel = ConnectionPanel(controller)
        self.sidebar = None

        try:
            self._apply_layout()
        except Exception:  # pylint: disable=broad-except
            # PLAN.md §2: never a half-built window. If re-parenting fails we
            # are still a working VPNWidget in Proton's own vertical layout.
            logger.exception("Could not apply the Windows-style layout; "
                             "falling back to the stock layout.")

    # -- layout -----------------------------------------------------------

    def _take_children(self) -> List[Gtk.Widget]:
        """Detach every direct child, returning them in order."""
        children = []
        child = self.get_first_child()
        while child is not None:
            children.append(child)
            child = child.get_next_sibling()
        for child in children:
            self.remove(child)
        return children

    def _apply_layout(self):
        children = self._take_children()

        # The search-results revealer is a local in their __init__; find it by
        # walking up from the widget we do have a handle on.
        revealer = self.search_results_widget.get_parent()
        if revealer is None or revealer not in children:
            revealer = next(
                (c for c in children if isinstance(c, Gtk.Revealer)), None)
        if revealer is None:
            raise RuntimeError("search results revealer not found")

        # Country names must truncate, not stretch the column: the longest is
        # "Democratic Republic of the Congo" at 32 characters.
        safe_signal_connect(self.server_list_widget, "ui-updated",
                            self._on_rows_rebuilt)

        # Their SearchResults revealer is deliberately left out of the tree.
        # It is their Linux design - a separate results box below the entry -
        # whereas the Windows app filters the list in place, which is what we
        # do. It stays alive and wired, just never shown.
        revealer.set_reveal_child(False)

        self.sidebar = Sidebar(
            controller=self._controller,
            search_widget=self.search_widget,
            search_results=Gtk.Box(),
            server_list_widget=self.server_list_widget,
            recents_view=self.recents_view,
            on_filter_changed=self._on_filter_changed,
            on_page_changed=self._on_page_changed,
            on_search_changed=self._on_search_changed,
        )

        centre = Gtk.Overlay()
        centre.add_css_class("connection-panel")
        centre.set_hexpand(True)
        self.backdrop = Backdrop()
        centre.set_child(self.backdrop)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        # Top of the column, as in the Windows app - not floating in the middle
        # of the map, where it reads as a label stuck on the continent.
        panel.set_valign(Gtk.Align.START)
        panel.set_margin_top(26)
        panel.set_halign(Gtk.Align.CENTER)
        panel.add_css_class("connection-panel-content")
        panel.append(self.connection_panel)
        centre.add_overlay(panel)

        # The status line and the stats sit *over* the map at the bottom of the
        # centre column, behind a fade - not in a bar across the whole window.
        # That is what lets the sidebar and rail run the full height, as they
        # do in the Windows app.
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        details.add_css_class("connection-details")
        details.set_valign(Gtk.Align.END)
        details.set_hexpand(True)
        # No margins: the fade has to reach the window edges, or it reads as a
        # floating grey panel that stops short of the bottom. The inset comes
        # from padding inside it instead.
        details.append(self.connection_panel.status_line)
        details.append(self.stats_bar)
        centre.add_overlay(details)

        # The rail floats over the map rather than taking a column of its own -
        # the map runs underneath it, as it does in the Windows app.
        # Top-aligned, level with the country panel opposite it. Centring left
        # it floating in the middle of the map with nothing to relate to.
        self.action_rail.set_valign(Gtk.Align.START)
        self.action_rail.set_halign(Gtk.Align.END)
        self.action_rail.set_vexpand(False)
        self.action_rail.set_margin_top(8)
        self.action_rail.set_margin_end(12)
        self.action_rail.add_css_class("action-rail-floating")
        centre.add_overlay(self.action_rail)

        columns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        columns.set_vexpand(True)
        # No separators: the Windows app divides the panes by background alone.
        columns.append(self.sidebar)
        columns.append(centre)

        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_spacing(0)
        # Paint the root: anything the columns and the stats bar do not cover
        # (margins, the strip beside the rail) otherwise shows through as bare
        # white against the dark shell.
        self.add_css_class("unofficial-layout")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.append(self.tier_notice)
        content.append(columns)

        # The free-account warning covers the whole window until it is
        # acknowledged, so it cannot be missed (PLAN.md §1).
        self.content_overlay = Gtk.Overlay()
        self.content_overlay.set_child(content)
        self.content_overlay.add_overlay(self.free_gate)
        self.append(self.content_overlay)

        # Anything we did not place (future upstream additions) goes back in,
        # so an upstream change degrades to "an extra row" rather than a
        # missing widget.
        # Their status and quick-connect widgets are replaced by our own
        # connection block (see connection_panel.py for why). They stay alive as
        # connection-state subscribers - VPNWidget keeps updating them - they
        # are simply not shown.
        placed = {
            self.search_widget, revealer, self.server_list_widget,
            self.connection_status_widget, self.quick_connect_widget,
        }
        for child in children:
            if child not in placed:
                logger.info(f"Unplaced upstream widget kept: {type(child).__name__}")
                self.append(child)

    # -- long country names -----------------------------------------------

    def _on_rows_rebuilt(self, *_args):
        """Their list rebuilds its rows on every update; re-apply after it."""
        GLib.idle_add(self.ellipsize_row_labels)

    def ellipsize_row_labels(self) -> bool:
        """Make every label in the server list truncate rather than stretch.

        The sidebar is a fixed-width column, so a long country name has to end
        in an ellipsis instead of pushing the column wider. Ellipsizing also
        drops each label's minimum width, so nothing in the list can fight the
        fixed width from below.
        """
        try:
            for widget in _walk(self.server_list_widget):
                if isinstance(widget, Gtk.Label):
                    if widget.get_ellipsize() == Pango.EllipsizeMode.NONE:
                        widget.set_ellipsize(Pango.EllipsizeMode.END)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Could not ellipsize the server list labels.")
        return GLib.SOURCE_REMOVE

    # -- filters ----------------------------------------------------------

    def display(self, user_tier: int, server_list):
        """Remember the full list, then display it (filtered, if a tab is on)."""
        self._full_server_list = server_list
        self._displayed_user_tier = user_tier

        try:
            # PLAN.md §1: paid plans only. The gate covers the window until it
            # is acknowledged; the banner stays behind it as a reminder.
            self.free_gate.update_for_tier(user_tier)
            self.tier_notice.update_for_tier(user_tier)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Could not evaluate the account tier.")

        super().display(user_tier, self._filtered(server_list))
        self.ellipsize_row_labels()

    def _filtered(self, server_list):
        """Apply the active filter tab and the search query together.

        Both narrow the same list, so they compose: searching while Secure Core
        is selected gives Secure Core matches, not everything that matches.
        """
        feature = self.sidebar.active_filter if self.sidebar else None
        query = self._search_query.casefold()
        if server_list is None or (feature is None and not query):
            return server_list

        try:
            from proton.vpn.session.servers import ServerList

            logicals = []
            for logical in server_list.logicals:
                if feature is not None and not any(
                        getattr(f, "name", "") == feature
                        for f in (getattr(logical, "features", None) or [])):
                    continue
                if query and not self._matches(logical, query):
                    continue
                logicals.append(logical)

            return ServerList(
                user_tier=server_list.user_tier,
                logicals=logicals,
                expiration_time=server_list.expiration_time,
                loads_expiration_time=server_list.loads_expiration_time,
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception("Could not filter the server list; showing everything.")
            return server_list

    @staticmethod
    def _matches(logical, query: str) -> bool:
        """Whether a server matches the query, by country, city or name."""
        for attribute in ("exit_country_name", "exit_country", "city",
                          "location", "name"):
            value = getattr(logical, attribute, None)
            if value and query in str(value).casefold():
                return True
        return False

    def _on_search_changed(self, query: str):
        """Re-display the list for a new search query."""
        if query == self._search_query:
            return
        self._search_query = query
        self._reapply_filters()

    def _reapply_filters(self):
        if self._full_server_list is None or self._displayed_user_tier is None:
            return
        try:
            super().display(self._displayed_user_tier,
                            self._filtered(self._full_server_list))
            self.ellipsize_row_labels()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Could not re-display the filtered server list.")

    def _on_filter_changed(self, _feature: Optional[str]):
        self._reapply_filters()

    def _on_page_changed(self, page: str):
        if page == RECENTS_PAGE:
            self.recents_view.refresh()

    # -- state ------------------------------------------------------------

    def status_update(self, connection_state):
        """Keep the stats bar and the Recents page in step with the connection.

        This runs on the connection state machine's thread, so everything that
        touches a widget is handed to the GTK main loop - the same thing
        Proton's own `VPNWidget.status_update` does.
        """
        super().status_update(connection_state)

        try:
            self.connection_panel.status_update(connection_state)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Could not update the connection panel.")

        try:
            self.stats_bar.status_update(connection_state)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Could not update the stats bar.")

        # Kill switch and NetShield can change with the connection, so keep the
        # rail's On/Off labels honest. refresh_state() hops to the main thread
        # itself - reading settings blocks on the executor.
        try:
            connected = type(connection_state).__name__ == "Connected"
            country, server = "", ""
            if connected:
                connection = getattr(getattr(connection_state, "context", None),
                                     "connection", None)
                server = getattr(connection, "server_name", "") or ""
                if server:
                    try:
                        logical = self._controller.server_list.get_by_name(server)
                        country = getattr(logical, "exit_country", "") or ""
                    except Exception:  # pylint: disable=broad-except
                        country = ""
            GLib.idle_add(self.action_rail.set_connection, connected, country, server)
            self.action_rail.refresh_state()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Could not refresh the action rail.")

        GLib.idle_add(self._update_map_highlight, connection_state)

        if type(connection_state).__name__ == "Connected":
            GLib.idle_add(self._refresh_recents_view)

    def _update_map_highlight(self, connection_state) -> bool:
        """Pick out the country we are connected to. Main thread only."""
        if self.backdrop is None:
            return GLib.SOURCE_REMOVE

        try:
            if type(connection_state).__name__ != "Connected":
                # Clear both together: a stale marker outliving its highlight
                # is what put a lone dot on the map mid-switch.
                self.backdrop.set_marker(None, None)
                self.backdrop.set_highlight(None)
                return GLib.SOURCE_REMOVE

            connection = getattr(getattr(connection_state, "context", None),
                                 "connection", None)
            server_name = getattr(connection, "server_name", None)
            country, longitude, latitude = "", None, None
            if server_name:
                logical = self._controller.server_list.get_by_name(server_name)
                country = getattr(logical, "exit_country", "") or ""
                longitude = getattr(logical, "longitude", None)
                latitude = getattr(logical, "latitude", None)

            # The dot is a fallback for countries the outline data cannot
            # draw (Hong Kong, Singapore, Monaco), not a companion to the
            # highlight. Setting it for every connection made it flash at the
            # server's coordinates mid-switch, while the old highlight was
            # clearing and the new one had not landed. Highlighting the
            # country is the reliable signal.
            if country and not self.backdrop.knows_country(country):
                self.backdrop.set_marker(longitude, latitude)
            else:
                self.backdrop.set_marker(None, None)

            self.backdrop.set_highlight(country or None)
        except Exception:  # pylint: disable=broad-except
            # A map that cannot work out where you are shows nothing, rather
            # than showing somewhere wrong.
            logger.exception("Could not highlight the connected country.")
            self.backdrop.set_highlight(None)
        return GLib.SOURCE_REMOVE

    def _refresh_recents_view(self) -> bool:
        """Runs on the GTK main thread."""
        try:
            self.recents_view.refresh()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Could not refresh the recents view.")
        return GLib.SOURCE_REMOVE

    def unload(self):
        """Stop our pollers along with Proton's own teardown."""
        try:
            self.connection_panel.teardown()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Connection panel teardown failed.")
        try:
            self.stats_bar.teardown()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Stats bar teardown failed.")
        try:
            # A debounced search could otherwise fire after logout and touch a
            # widget that is on its way out.
            if self.sidebar is not None:
                self.sidebar.teardown()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Sidebar teardown failed.")
        super().unload()
