"""
The left column.

PLAN.md §4: "search field; nav: Recents, Countries (Profiles cut); filter tabs
All / Secure Core / P2P / Tor; country list with flags."

The search entry, search results and server list are Proton's own widgets,
placed here rather than stacked down the middle of the window. The nav and the
filter tabs are ours.
"""

from typing import Callable, List, Optional

from proton.vpn import logging

from ..futures import report_failure

from gi.repository import GLib, Gtk

#: Filter tabs, in order. The value is the ServerFeatureEnum name to match, or
#: None for "everything". PLAN.md §4 - Profiles and Port forwarding are cut.
FILTERS = (
    ("All", None),
    ("Secure Core", "SECURE_CORE"),
    ("P2P", "P2P"),
    ("Tor", "TOR"),
)

logger = logging.getLogger(__name__)

COUNTRIES_PAGE = "countries"
RECENTS_PAGE = "recents"


class Sidebar(Gtk.Box):
    """Search, navigation, filters and the server list."""

    #: Their sidebar's usable width is 280. Ours carries a border and margins
    #: outside that, so the column has to be wider for the inside to match -
    #: otherwise country names start truncating ("Afghanist...").
    WIDTH = 306

    def __init__(
        self,
        controller,
        search_widget: Gtk.Widget,
        search_results: Gtk.Widget,
        server_list_widget: Gtk.Widget,
        recents_view: Gtk.Widget,
        on_filter_changed: Optional[Callable[[Optional[str]], None]] = None,
        on_page_changed: Optional[Callable[[str], None]] = None,
        on_search_changed: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("sidebar")
        self.set_size_request(self.WIDTH, -1)
        # The server list sets hexpand, and that propagates up through the
        # stack to us - which would let the sidebar swallow the window and
        # squeeze the connection panel. Setting it explicitly here overrides
        # the computed value and pins the sidebar to its own width.
        self.set_hexpand(False)

        self._controller = controller
        self._on_filter_changed = on_filter_changed
        self._on_page_changed = on_page_changed
        self._filter_buttons: List[Gtk.ToggleButton] = []
        self._nav_buttons: dict = {}
        self._active_filter: Optional[str] = None
        # Set while we drive the toggle buttons ourselves, so their
        # handlers do not fight the change we are making.
        self._updating = False

        # Build every child before wiring anything up: setting a toggle button
        # active fires its handler immediately, and those handlers reach for
        # the stack and the filter bar.
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._stack.set_hexpand(False)
        # Recents sits left of Countries in the nav, so sliding matches the
        # direction you moved rather than dissolving in place.
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.set_transition_duration(180)
        self._stack.add_named(server_list_widget, COUNTRIES_PAGE)
        self._stack.add_named(recents_view, RECENTS_PAGE)
        self._stack.set_visible_child_name(COUNTRIES_PAGE)
        self._pin_width(server_list_widget, recents_view)

        self._filter_bar = self._build_filter_bar()
        nav = self._build_nav()

        self._search_timeout = None
        self._on_search_changed = on_search_changed
        if on_search_changed is not None:
            search_widget.connect("search-changed", self._on_search_entry_changed)

        search_widget.set_margin_top(12)
        search_widget.set_margin_start(12)
        search_widget.set_margin_end(12)
        search_widget.set_margin_bottom(8)

        self.fastest_row = self._build_fastest_row()

        # Visual order, top to bottom.
        self.append(search_widget)
        self.append(search_results)
        self.append(nav)
        self.append(self._filter_bar)
        self.append(self.fastest_row)
        self.append(self._stack)

    # -- search ------------------------------------------------------------

    #: Milliseconds to wait after a keystroke before filtering. Each pass walks
    #: 18,000 logicals, so filtering on every key would stutter.
    SEARCH_DEBOUNCE_MS = 180

    def _on_search_entry_changed(self, entry):
        """Debounce, then hand the query up to be applied to the list."""
        if self._search_timeout is not None:
            GLib.source_remove(self._search_timeout)

        def fire():
            self._search_timeout = None
            if self._on_search_changed:
                self._on_search_changed(entry.get_text().strip())
            return GLib.SOURCE_REMOVE

        self._search_timeout = GLib.timeout_add(self.SEARCH_DEBOUNCE_MS, fire)

    def teardown(self):
        """Drop any pending search."""
        if self._search_timeout is not None:
            GLib.source_remove(self._search_timeout)
            self._search_timeout = None

    # -- fastest country ---------------------------------------------------

    def _build_fastest_row(self) -> Gtk.Widget:
        """"Fastest country", pinned above the list as in the Windows app.

        Pinned rather than the first row of the list, so it stays reachable
        once you have scrolled and does not disappear under a filter.
        """
        button = Gtk.Button()
        button.add_css_class("fastest-row")
        button.add_css_class("flat")
        button.set_margin_start(12)
        button.set_margin_end(12)
        button.set_margin_bottom(4)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        icon = Gtk.Image.new_from_icon_name("weather-storm-symbolic")
        icon.set_pixel_size(18)
        icon.add_css_class("fastest-row-icon")
        row.append(icon)

        label = Gtk.Label(label="Fastest country")
        label.set_xalign(0)
        label.set_hexpand(True)
        label.add_css_class("fastest-row-label")
        row.append(label)

        button.set_child(row)
        button.connect("clicked", self._on_fastest_clicked)
        return button

    def _on_fastest_clicked(self, *_args):
        """Connect to the fastest server - through their controller."""
        if self._controller is None:
            return
        try:
            future = self._controller.connect_to_fastest_server()
            report_failure(future, "Connecting to the fastest server")
        except Exception:  # pylint: disable=broad-except
            logger.exception("Could not connect to the fastest server.")

    # -- navigation -------------------------------------------------------

    def _build_nav(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.add_css_class("sidebar-nav")
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_bottom(8)

        for label, page in (("Recents", RECENTS_PAGE), ("Countries", COUNTRIES_PAGE)):
            button = Gtk.ToggleButton(label=label)
            button.add_css_class("sidebar-nav-button")
            button.set_hexpand(True)
            button.connect("toggled", self._on_nav_toggled, page)
            self._nav_buttons[page] = button
            box.append(button)

        self._nav_buttons[COUNTRIES_PAGE].set_active(True)
        return box

    def _on_nav_toggled(self, button: Gtk.ToggleButton, page: str):
        if getattr(self, "_stack", None) is None or self._updating:
            return

        if not button.get_active():
            # The user clicked the tab that was already on. Keep one selected.
            if self._stack.get_visible_child_name() == page:
                self._set_active_quietly(button, True)
            return

        self._updating = True
        try:
            for other_page, other in self._nav_buttons.items():
                if other_page != page:
                    other.set_active(False)
            self._stack.set_visible_child_name(page)
            # Filters only apply to the country list.
            self._filter_bar.set_visible(page == COUNTRIES_PAGE)
        finally:
            self._updating = False

        if self._on_page_changed:
            self._on_page_changed(page)

    @property
    def current_page(self) -> str:
        """Which nav page is showing."""
        return self._stack.get_visible_child_name()

    def show_page(self, page: str):
        """Switch pages programmatically."""
        button = self._nav_buttons.get(page)
        if button is not None:
            button.set_active(True)

    # -- filters ----------------------------------------------------------

    def _build_filter_bar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.add_css_class("sidebar-filters")
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_bottom(8)

        box.set_halign(Gtk.Align.START)
        for label, feature in FILTERS:
            button = Gtk.ToggleButton(label=label)
            button.add_css_class("sidebar-filter-button")
            button.set_hexpand(False)
            button.connect("toggled", self._on_filter_toggled, feature)
            self._filter_buttons.append(button)
            box.append(button)

        self._filter_buttons[0].set_active(True)  # "All"
        return box

    def _on_filter_toggled(self, button: Gtk.ToggleButton, feature: Optional[str]):
        if self._updating:
            return

        if not button.get_active():
            if self._active_filter == feature:
                self._set_active_quietly(button, True)
            return

        self._updating = True
        try:
            for other in self._filter_buttons:
                if other is not button:
                    other.set_active(False)
        finally:
            self._updating = False

        self._active_filter = feature
        if self._on_filter_changed:
            self._on_filter_changed(feature)

    def _set_active_quietly(self, button: Gtk.ToggleButton, active: bool):
        """Change a button without its handler acting on the change."""
        self._updating = True
        try:
            button.set_active(active)
        finally:
            self._updating = False

    def _pin_width(self, *scrollables):
        """Stop the column's width from following its contents.

        A Gtk.Box measures through its layout manager, so overriding
        `do_measure` here does nothing - GTK never calls it. What does work is
        removing the two ways content can push the column wider:

        * a ScrolledWindow reports the natural width of what it contains unless
          `propagate-natural-width` is off, and
        * a long label reports a large minimum width unless it can ellipsize
          (handled where the rows are built).

        With both dealt with, `set_size_request` becomes the whole story and
        the column stays the same width under every filter.
        """
        for scrollable in scrollables:
            if isinstance(scrollable, Gtk.ScrolledWindow):
                scrollable.set_propagate_natural_width(False)
                # A permanent scrollbar, as the Windows list has: overlay
                # scrollbars fade out, so there is nothing showing where you
                # are in a list of 149 countries.
                scrollable.set_overlay_scrolling(False)
                # Keep whatever vertical policy they chose; only the horizontal
                # one matters for the column's width.
                vertical = scrollable.get_policy()[1]
                scrollable.set_policy(Gtk.PolicyType.NEVER, vertical)

    @property
    def active_filter(self) -> Optional[str]:
        """The ServerFeatureEnum name being filtered on, or None for All."""
        return self._active_filter
