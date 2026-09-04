"""
Structural tests for the Windows-style layout.

Follows PLAN.md §8 Step 0's approach: build the real widgets against a mock
controller, then assert the shape of the tree. No VPN connection, no window
shown, no human looking.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unofficial_protonvpn.widgets.main_layout import WindowsStyleVPNWidget  # noqa: E402
from unofficial_protonvpn.widgets.sidebar import (  # noqa: E402
    COUNTRIES_PAGE, RECENTS_PAGE, FILTERS, Sidebar,
)


def walk(widget, depth=0):
    """Yield (depth, widget) for the whole tree under `widget`."""
    yield depth, widget
    child = widget.get_first_child()
    while child is not None:
        yield from walk(child, depth + 1)
        child = child.get_next_sibling()


def load_our_css():
    """Load overlay.css, as the running app does.

    Widths depend on it: without our stylesheet the tabs keep the stock theme's
    button padding and the sidebar measures wider than it ever does in the app.
    """
    from gi.repository import Gdk

    from unofficial_protonvpn.style import load_overlay_css
    load_overlay_css(Gdk.Display.get_default())


def build_widget():
    controller = MagicMock()
    controller.user_tier = 2
    main_window = MagicMock()
    return WindowsStyleVPNWidget(controller, main_window, notifications=MagicMock())


class LayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise (no display)")
        load_our_css()

    def setUp(self):
        self.widget = build_widget()

    def test_layout_was_applied(self):
        self.assertIsNotNone(self.widget.sidebar,
                             "layout fell back to Proton's vertical stack")

    def test_upstream_widgets_we_show_survive_reparenting(self):
        """Nothing Proton built that we display may be dropped on the floor."""
        present = {id(w) for _, w in walk(self.widget)}
        for name in ("search_widget", "server_list_widget"):
            self.assertIn(id(getattr(self.widget, name)), present,
                          f"{name} is missing from the tree")

    def test_the_search_results_popup_is_not_shown(self):
        """We filter the list in place, as Windows does, so their separate
        results box is deliberately never displayed."""
        present = {id(w) for _, w in walk(self.widget)}
        self.assertNotIn(id(self.widget.search_results_widget), present)
        self.assertIsNotNone(self.widget.search_results_widget,
                             "it stays alive and wired, just not shown")

    def test_replaced_widgets_stay_alive_as_state_subscribers(self):
        """Their status widgets are replaced on screen, not discarded.

        VPNWidget keeps pushing connection states into them, so they must still
        exist - they are simply not shown (see connection_panel.py).
        """
        for name in ("connection_status_widget", "quick_connect_widget"):
            widget = getattr(self.widget, name)
            self.assertIsNotNone(widget)
            self.assertIn(widget, self.widget._state_subscribers)

    def test_three_column_shape(self):
        """Sidebar, connection panel and rail sit side by side in one row."""
        columns = self.widget.sidebar.get_parent()
        self.assertIsInstance(columns, Gtk.Box)
        self.assertEqual(columns.get_orientation(), Gtk.Orientation.HORIZONTAL)

        children = []
        child = columns.get_first_child()
        while child is not None:
            children.append(child)
            child = child.get_next_sibling()

        self.assertIs(children[0], self.widget.sidebar, "sidebar comes first")
        self.assertTrue(any(w.has_css_class("connection-panel") for w in children),
                        "no connection panel in the column row")

    def test_the_rail_floats_over_the_map(self):
        """Windows floats it on the map; it does not take a column."""
        centre = next(w for _, w in walk(self.widget)
                      if w.has_css_class("connection-panel"))
        self.assertIs(self.widget.action_rail.get_parent(), centre)
        self.assertTrue(self.widget.action_rail.has_css_class("action-rail-floating"))

    def test_content_sits_under_the_overlay_that_holds_the_gate(self):
        content = self.widget.content_overlay.get_child()
        columns = self.widget.sidebar.get_parent()
        self.assertIs(columns.get_parent(), content)
        self.assertIs(self.widget.tier_notice.get_parent(), content)
        self.assertIs(self.widget.free_gate.get_parent(), self.widget.content_overlay)

    def test_stats_are_overlaid_on_the_map_not_a_bar_across_the_window(self):
        """Windows puts the details over the map so the panes run full height."""
        details = self.widget.stats_bar.get_parent()
        self.assertTrue(details.has_css_class("connection-details"))

        centre = next(w for _, w in walk(self.widget)
                      if w.has_css_class("connection-panel"))
        inside_centre = {id(w) for _, w in walk(centre)}
        self.assertIn(id(self.widget.stats_bar), inside_centre)
        self.assertIn(id(self.widget.connection_panel.status_line), inside_centre)

    def test_the_column_row_fills_the_window(self):
        columns = self.widget.sidebar.get_parent()
        self.assertTrue(columns.get_vexpand())

    def test_sidebar_holds_search_list_and_recents(self):
        inside = {id(w) for _, w in walk(self.widget.sidebar)}
        self.assertIn(id(self.widget.search_widget), inside)
        self.assertIn(id(self.widget.server_list_widget), inside)
        self.assertIn(id(self.widget.recents_view), inside)

    def test_connection_panel_holds_our_connection_block(self):
        panel = next(w for _, w in walk(self.widget)
                     if w.has_css_class("connection-panel"))
        inside = {id(w) for _, w in walk(panel)}
        self.assertIn(id(self.widget.connection_panel), inside)
        self.assertIn(id(self.widget.backdrop), inside)

    def test_backdrop_is_not_interactive(self):
        backdrop = next(w for _, w in walk(self.widget) if w.has_css_class("backdrop"))
        self.assertFalse(backdrop.get_can_target(),
                         "the backdrop is decorative and must not take clicks")

    def test_filter_tabs_present_and_all_selected(self):
        labels = [w.get_label() for _, w in walk(self.widget.sidebar)
                  if isinstance(w, Gtk.ToggleButton)]
        for name, _feature in FILTERS:
            self.assertIn(name, labels)
        self.assertIsNone(self.widget.sidebar.active_filter, "All should be active")

    def test_nav_defaults_to_countries_and_switches_to_recents(self):
        sidebar = self.widget.sidebar
        self.assertEqual(sidebar.current_page, COUNTRIES_PAGE)
        sidebar.show_page(RECENTS_PAGE)
        self.assertEqual(sidebar.current_page, RECENTS_PAGE)
        sidebar.show_page(COUNTRIES_PAGE)
        self.assertEqual(sidebar.current_page, COUNTRIES_PAGE)

    def test_nav_cannot_end_up_with_nothing_selected(self):
        sidebar = self.widget.sidebar
        button = sidebar._nav_buttons[COUNTRIES_PAGE]
        button.set_active(False)  # user clicks the already-active tab
        self.assertEqual(sidebar.current_page, COUNTRIES_PAGE)
        self.assertTrue(button.get_active())

    def test_filters_hidden_on_the_recents_page(self):
        sidebar = self.widget.sidebar
        sidebar.show_page(RECENTS_PAGE)
        self.assertFalse(sidebar._filter_bar.get_visible())
        sidebar.show_page(COUNTRIES_PAGE)
        self.assertTrue(sidebar._filter_bar.get_visible())


class TeardownTest(unittest.TestCase):
    """Nothing we schedule may outlive the widget that scheduled it."""

    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")
        load_our_css()

    def test_unload_stops_everything_we_started(self):
        widget = build_widget()
        widget.connection_panel._start_ticking()
        widget.stats_bar._start_poll()
        widget.sidebar._search_timeout = None

        widget.unload()

        self.assertIsNone(widget.connection_panel._tick_source)
        self.assertIsNone(widget.stats_bar._poll_source_id)
        self.assertIsNone(widget.sidebar._search_timeout)

    def test_a_pending_search_is_cancelled_on_unload(self):
        """A debounced search firing after logout would touch a dead widget."""
        from gi.repository import GLib

        widget = build_widget()
        widget.sidebar._search_timeout = GLib.timeout_add(10_000, lambda: False)
        widget.unload()
        self.assertIsNone(widget.sidebar._search_timeout)


class FixedWidthColumnTest(unittest.TestCase):
    """The sidebar is a fixed column; long names truncate instead of widening it."""

    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")
        load_our_css()

    def test_width_is_identical_under_every_filter(self):
        widget = build_widget()
        widths = set()
        for feature in (None, "SECURE_CORE", "P2P", "TOR"):
            widget.sidebar._active_filter = feature
            widths.add(widget.sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[:2])
        self.assertEqual(len(widths), 1,
                         f"the column changes width between filters: {widths}")

    def test_a_long_row_that_truncates_does_not_widen_the_column(self):
        """Rows as we actually build them: long name, ellipsized."""
        from gi.repository import Pango

        widget = build_widget()
        before = widget.sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[1]

        long_row = Gtk.Label(label="Democratic Republic of the Congo" * 4)
        long_row.set_ellipsize(Pango.EllipsizeMode.END)
        widget.recents_view._list.append(long_row)

        after = widget.sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        self.assertEqual(before, after,
                         "a long row widened the column instead of truncating")

    def test_a_row_that_cannot_truncate_would_widen_the_column(self):
        """Why ellipsize is part of the mechanism, not a nicety.

        Turning off `propagate-natural-width` caps the natural width, but a
        label that cannot ellipsize still reports a large *minimum*, and
        minimums always win. Both halves are needed.
        """
        widget = build_widget()
        before = widget.sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[1]

        stubborn = Gtk.Label(label="Democratic Republic of the Congo" * 4)
        widget.recents_view._list.append(stubborn)

        after = widget.sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        self.assertGreater(after, before)

    def test_scrollables_cannot_push_the_column_wider(self):
        """The mechanism, asserted directly: GTK ignores do_measure on a Box."""
        widget = build_widget()
        for scrollable in (widget.server_list_widget, widget.recents_view):
            self.assertFalse(scrollable.get_propagate_natural_width(),
                             f"{type(scrollable).__name__} still propagates its "
                             "natural width, so content can widen the column")
            self.assertEqual(scrollable.get_policy()[0], Gtk.PolicyType.NEVER)

    def test_real_server_list_labels_all_truncate(self):
        import json

        cache = Path.home() / ".cache" / "Proton" / "VPN" / "serverlist.json"
        if not cache.exists():
            self.skipTest("no cached server list on this machine")

        from gi.repository import Pango
        from proton.vpn.session.servers import ServerList

        widget = build_widget()
        widget.display(2, ServerList.from_dict(json.loads(cache.read_text())))

        labels = [w for w in walk_widgets(widget.server_list_widget)
                  if isinstance(w, Gtk.Label)]
        self.assertGreater(len(labels), 100, "the list did not populate")

        not_truncating = [l.get_text() for l in labels
                          if l.get_ellipsize() == Pango.EllipsizeMode.NONE]
        self.assertEqual(not_truncating, [],
                         "these labels would stretch the column instead of truncating")

        self.assertEqual(widget.sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[1],
                         widget.sidebar.WIDTH)


def walk_widgets(widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from walk_widgets(child)
        child = child.get_next_sibling()


class SearchTest(unittest.TestCase):
    """Search narrows the country list itself, and composes with the tabs."""

    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")
        load_our_css()

        import json
        cache = Path.home() / ".cache" / "Proton" / "VPN" / "serverlist.json"
        if not cache.exists():
            raise unittest.SkipTest("no cached server list on this machine")
        from proton.vpn.session.servers import ServerList
        cls.server_list = ServerList.from_dict(json.loads(cache.read_text()))

    def setUp(self):
        self.widget = build_widget()
        self.widget._full_server_list = self.server_list
        self.widget._displayed_user_tier = 2

    def filtered_for(self, query, feature=None):
        self.widget._search_query = query
        self.widget.sidebar._active_filter = feature
        return self.widget._filtered(self.server_list)

    def test_searching_a_country_narrows_the_list(self):
        result = self.filtered_for("germany")
        self.assertGreater(len(result.logicals), 0)
        self.assertLess(len(result.logicals), len(self.server_list.logicals))
        for logical in result.logicals:
            self.assertEqual(logical.exit_country, "DE")

    def test_searching_a_city_works(self):
        result = self.filtered_for("vienna")
        self.assertGreater(len(result.logicals), 0)
        for logical in result.logicals:
            haystack = " ".join(str(getattr(logical, a, "") or "")
                                for a in ("city", "location", "name")).casefold()
            self.assertIn("vienna", haystack)

    def test_searching_a_server_name_works(self):
        wanted = self.server_list.logicals[0].name
        result = self.filtered_for(wanted.casefold())
        self.assertIn(wanted, [l.name for l in result.logicals])

    def test_search_is_case_insensitive(self):
        self.assertEqual(len(self.filtered_for("GERMANY").logicals),
                         len(self.filtered_for("germany").logicals))

    def test_search_composes_with_the_filter_tabs(self):
        """Searching under Secure Core gives Secure Core matches only."""
        both = self.filtered_for("switzerland", feature="SECURE_CORE")
        for logical in both.logicals:
            names = [getattr(f, "name", "") for f in (logical.features or [])]
            self.assertIn("SECURE_CORE", names)
            self.assertEqual(logical.exit_country, "CH")

    def test_an_empty_query_restores_everything(self):
        self.filtered_for("germany")
        self.assertIs(self.filtered_for(""), self.server_list)

    def test_nonsense_gives_an_empty_list_not_everything(self):
        result = self.filtered_for("zzzzzznotacountry")
        self.assertEqual(len(result.logicals), 0,
                         "a no-match search must not silently show everything")


class MapMarkerDecisionTest(unittest.TestCase):
    """Which countries get a dot, decided where the connection is handled."""

    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")
        load_our_css()

    def connect_to(self, country, longitude=10.0, latitude=50.0):
        from types import SimpleNamespace

        widget = build_widget()
        widget._controller.server_list.get_by_name.return_value = SimpleNamespace(
            exit_country=country, longitude=longitude, latitude=latitude,
            location="Somewhere")

        state = MagicMock()
        type(state).__name__ = "Connected"
        state.context.connection.server_name = f"{country}#1"
        widget._update_map_highlight(state)
        return widget

    def test_a_drawable_country_gets_no_dot(self):
        """Austria has an outline, so the dot must not appear at all."""
        widget = self.connect_to("AT")
        self.assertIsNone(widget.backdrop._marker)
        self.assertEqual(widget.backdrop.highlighted_country, "AT")

    def test_the_uk_gets_no_dot_either(self):
        """It resolves to GB, so it is drawable despite the code mismatch."""
        widget = self.connect_to("UK")
        self.assertIsNone(widget.backdrop._marker)

    def test_a_country_with_no_outline_gets_a_dot(self):
        widget = self.connect_to("HK", longitude=114.1, latitude=22.3)
        self.assertIsNotNone(widget.backdrop._marker)

    def test_switching_from_a_dot_country_clears_the_dot(self):
        """The flash: connect to Hong Kong, then Austria, dot must go."""
        from types import SimpleNamespace

        widget = self.connect_to("HK", longitude=114.1, latitude=22.3)
        self.assertIsNotNone(widget.backdrop._marker)

        widget._controller.server_list.get_by_name.return_value = SimpleNamespace(
            exit_country="AT", longitude=16.4, latitude=48.2, location="Vienna")
        state = MagicMock()
        type(state).__name__ = "Connected"
        state.context.connection.server_name = "AT#1"
        widget._update_map_highlight(state)

        self.assertIsNone(widget.backdrop._marker,
                          "the dot outlived the country that needed it")

    def test_disconnecting_clears_both(self):
        widget = self.connect_to("HK", longitude=114.1, latitude=22.3)
        state = MagicMock()
        type(state).__name__ = "Disconnected"
        widget._update_map_highlight(state)
        self.assertIsNone(widget.backdrop._marker)
        self.assertIsNone(widget.backdrop.highlighted_country)


class FilteringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise (no display)")
        load_our_css()

    def test_filter_selects_only_matching_servers(self):
        from types import SimpleNamespace

        widget = build_widget()

        def logical(name, features):
            return SimpleNamespace(
                id=name,  # ServerList indexes by id
                name=name,
                features=[SimpleNamespace(name=f) for f in features],
            )

        server_list = SimpleNamespace(
            logicals=[
                logical("AT#1", []),
                logical("CH#2", ["SECURE_CORE"]),
                logical("NL#3", ["P2P"]),
                logical("SE#4", ["SECURE_CORE", "P2P"]),
            ],
            user_tier=2,
            expiration_time=0,
            loads_expiration_time=0,
        )

        widget._full_server_list = server_list
        widget.sidebar._active_filter = "SECURE_CORE"
        filtered = widget._filtered(server_list)

        self.assertEqual(
            sorted(l.name for l in filtered.logicals), ["CH#2", "SE#4"])

    def test_all_filter_returns_the_list_untouched(self):
        widget = build_widget()
        sentinel = object()
        widget.sidebar._active_filter = None
        self.assertIs(widget._filtered(sentinel), sentinel)

    def test_filter_against_the_real_server_list(self):
        """The synthetic test can't prove this works on Proton's own data."""
        import json

        cache = Path.home() / ".cache" / "Proton" / "VPN" / "serverlist.json"
        if not cache.exists():
            self.skipTest("no cached server list on this machine")

        from proton.vpn.session.servers import ServerList

        server_list = ServerList.from_dict(json.loads(cache.read_text()))
        widget = build_widget()
        widget.sidebar._active_filter = "SECURE_CORE"
        filtered = widget._filtered(server_list)

        self.assertLess(len(filtered.logicals), len(server_list.logicals),
                        "filtering did nothing - it silently fell back")
        self.assertGreater(len(filtered.logicals), 0)
        for logical in filtered.logicals:
            names = [getattr(f, "name", "") for f in (logical.features or [])]
            self.assertIn("SECURE_CORE", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
