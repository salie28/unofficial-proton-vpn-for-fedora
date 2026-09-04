"""
Tests for the map backdrop's projection.

The bug these exist for: projecting each point by the shortest route from the
view centre tears any country crossing the antimeridian, because neighbouring
points land at opposite edges and are joined by a line straight across the map.
"""

import sys
import unittest
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unofficial_protonvpn.widgets.backdrop import Backdrop, country_extent  # noqa: E402
from unofficial_protonvpn.widgets.map_data import COUNTRIES  # noqa: E402

WIDTH, HEIGHT = 800, 600


class ProjectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def widest_gap(self, ring, backdrop):
        points = backdrop.ring_points(ring, WIDTH, HEIGHT)
        return max(abs(b[0] - a[0]) for a, b in zip(points, points[1:]))

    def test_no_country_is_torn_across_the_map(self):
        """Every ring must stay continuous at every view we can be in."""
        backdrop = Backdrop()
        for country in ("AT", "DE", "US", "JP", "NZ", "FJ", "RU"):
            if country not in COUNTRIES:
                continue
            backdrop.set_highlight(country, animate=False)
            for code, rings in COUNTRIES.items():
                for index, ring in enumerate(rings):
                    gap = self.widest_gap(ring, backdrop)
                    self.assertLess(
                        gap, WIDTH,
                        f"{code} ring {index} tears across the map when viewing "
                        f"{country}: a {gap:.0f}px jump between neighbours")

    def test_rings_stay_continuous_at_the_default_view(self):
        backdrop = Backdrop()
        for code, rings in COUNTRIES.items():
            for ring in rings:
                self.assertLess(self.widest_gap(ring, backdrop), WIDTH, code)

    def test_a_ring_crossing_the_antimeridian_stays_whole(self):
        """The specific shape that used to tear."""
        backdrop = Backdrop()
        ring = [(170.0, 60.0), (178.0, 61.0), (-178.0, 61.0), (-170.0, 60.0),
                (-170.0, 58.0), (170.0, 58.0)]
        points = backdrop.ring_points(ring, WIDTH, HEIGHT)
        gaps = [abs(b[0] - a[0]) for a, b in zip(points, points[1:])]
        self.assertLess(max(gaps), WIDTH,
                        f"the ring was torn apart: gaps {[round(g) for g in gaps]}")

    def test_the_highlighted_country_is_framed(self):
        backdrop = Backdrop()
        backdrop.set_highlight("DE", animate=False)
        centre_lon, centre_lat, span = backdrop.view
        extent = country_extent("DE")
        self.assertAlmostEqual(centre_lon, extent[0], places=3)
        self.assertAlmostEqual(centre_lat, extent[1], places=3)
        self.assertGreater(span, extent[2], "the country must fit in the view")

    def test_clearing_the_highlight_returns_to_the_default_view(self):
        from unofficial_protonvpn.widgets.backdrop import DEFAULT_VIEW
        backdrop = Backdrop()
        backdrop.set_highlight("JP", animate=False)
        backdrop.set_highlight(None, animate=False)
        self.assertEqual(backdrop.view, DEFAULT_VIEW)

    def test_an_unknown_country_shows_nothing_rather_than_somewhere_wrong(self):
        backdrop = Backdrop()
        backdrop.set_highlight("ZZ", animate=False)
        self.assertFalse(backdrop.knows_country("ZZ"))


class CountryCoverageTest(unittest.TestCase):
    """Every country Proton offers must be shown somehow."""

    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

        import json
        cache = Path.home() / ".cache" / "Proton" / "VPN" / "serverlist.json"
        if not cache.exists():
            raise unittest.SkipTest("no cached server list")
        data = json.loads(cache.read_text())
        cls.codes = sorted({s.get("ExitCountry") for s in data.get("LogicalServers", [])
                            if s.get("ExitCountry")})

    def test_uk_is_understood(self):
        """Proton says UK; the outline data says GB."""
        from unofficial_protonvpn.widgets.backdrop import resolve_country
        self.assertEqual(resolve_country("UK"), "GB")
        self.assertIsNotNone(country_extent("UK"))

    def test_almost_every_country_has_an_outline(self):
        """A country you can connect to should be one we can draw."""
        backdrop = Backdrop()
        undrawable = [c for c in self.codes if not backdrop.knows_country(c)]
        self.assertLessEqual(
            len(undrawable), 12,
            f"too many countries cannot be drawn: {undrawable}")

    def test_countries_without_an_outline_are_marked_instead(self):
        """Monaco and friends are too small for 1:110m data."""
        backdrop = Backdrop()
        backdrop.set_marker(103.8, 1.35)          # Singapore
        backdrop.set_highlight("SG", animate=False)
        centre_lon, centre_lat, _span = backdrop.view
        self.assertAlmostEqual(centre_lon, 103.8, places=1)
        self.assertAlmostEqual(centre_lat, 1.35, places=1)

    def test_france_is_framed_on_the_mainland_not_french_guiana(self):
        """France owns territory in South America; the camera must not go there."""
        centre_lon, centre_lat, _w, _h = country_extent("FR")
        self.assertGreater(centre_lon, -6, "framed west of the Atlantic")
        self.assertLess(centre_lon, 10)
        self.assertGreater(centre_lat, 40, "framed on the European mainland")

    def test_the_united_states_is_framed_on_the_contiguous_states(self):
        centre_lon, _lat, _w, _h = country_extent("US")
        self.assertLess(centre_lon, -60, "should be over North America")
        self.assertGreater(centre_lon, -130)


class ActuallyDrawsTest(unittest.TestCase):
    """Exercise the real draw path.

    Every other test here checks geometry, which is why a missing _draw_marker
    shipped: the method was called but never defined, and nothing drew. In the
    app that surfaced as Proton's "an unexpected error occurred" dialog, once
    per frame. These tests render to a real Cairo surface, so a missing method
    or a bad call fails here instead.
    """

    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def draw(self, backdrop):
        import cairo
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 300)
        context = cairo.Context(surface)
        backdrop._draw(None, context, 400, 300)
        return surface

    def test_draws_with_nothing_highlighted(self):
        self.draw(Backdrop())

    def test_draws_with_a_country_highlighted(self):
        backdrop = Backdrop()
        backdrop.set_highlight("DE", animate=False)
        self.draw(backdrop)

    def test_draws_a_marker_for_a_country_with_no_outline(self):
        """The exact path that was missing its method."""
        backdrop = Backdrop()
        backdrop.set_marker(103.8, 1.35)      # Singapore
        backdrop.set_highlight("SG", animate=False)
        self.assertIsNone(country_extent("SG"), "SG must have no outline")
        self.draw(backdrop)

    def test_draws_mid_animation(self):
        backdrop = Backdrop()
        backdrop.set_marker(7.4, 43.7)        # Monaco
        backdrop.set_highlight("MC", animate=False)
        backdrop._highlight_progress = 0.4
        self.draw(backdrop)

    def test_draws_at_a_silly_size(self):
        backdrop = Backdrop()
        backdrop.set_highlight("US", animate=False)
        import cairo
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 12, 8)
        backdrop._draw(None, cairo.Context(surface), 12, 8)

    def test_every_proton_country_draws(self):
        """Walk the real list; any one of them could be the broken path."""
        import json
        cache = Path.home() / ".cache" / "Proton" / "VPN" / "serverlist.json"
        if not cache.exists():
            self.skipTest("no cached server list")
        data = json.loads(cache.read_text())
        codes = sorted({s.get("ExitCountry") for s in data.get("LogicalServers", [])
                        if s.get("ExitCountry")})

        backdrop = Backdrop()
        for code in codes:
            with self.subTest(country=code):
                backdrop.set_marker(10.0, 50.0)
                backdrop.set_highlight(code, animate=False)
                self.draw(backdrop)


class MarkerOnlyWhenNeededTest(unittest.TestCase):
    """The dot is a fallback, not a companion to the highlight."""

    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def test_a_country_with_an_outline_shows_no_marker(self):
        backdrop = Backdrop()
        backdrop.set_marker(None, None)
        backdrop.set_highlight("AT", animate=False)
        self.assertIsNone(backdrop._marker)

    def test_a_country_without_an_outline_keeps_its_marker(self):
        backdrop = Backdrop()
        backdrop.set_marker(114.1, 22.3)      # Hong Kong
        backdrop.set_highlight("HK", animate=False)
        self.assertIsNotNone(backdrop._marker)

    def test_clearing_the_marker_survives_a_highlight_change(self):
        """The flash: switching countries must not reveal a stale dot."""
        backdrop = Backdrop()
        backdrop.set_marker(114.1, 22.3)
        backdrop.set_highlight("HK", animate=False)

        backdrop.set_marker(None, None)
        backdrop.set_highlight(None, animate=False)
        self.assertIsNone(backdrop._marker,
                          "a cleared marker must not linger between countries")


if __name__ == "__main__":
    unittest.main(verbosity=2)
