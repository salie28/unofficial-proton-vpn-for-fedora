"""
Tests for the traffic chart's geometry.

These exist because a mistake in the point maths does not crash - it renders a
chart that twitches, and nothing else catches that.
"""

import sys
import unittest
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unofficial_protonvpn.widgets.traffic_graph import TrafficGraph  # noqa: E402

WIDTH, HEIGHT = 400, 80


class GeometryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK could not initialise")

    def graph(self, samples, entry=1.0):
        graph = TrafficGraph()
        for down, up in samples:
            graph.push(down, up)
        graph._entry = entry
        return graph

    def points(self, graph, index=0):
        return graph.points_for(WIDTH, HEIGHT, graph.scale(), index)

    def test_no_samples_gives_no_points(self):
        self.assertEqual(self.points(self.graph([])), [])

    def test_one_point_per_sample(self):
        graph = self.graph([(1000, 500)] * 5)
        self.assertEqual(len(self.points(graph)), 5)

    def test_every_point_has_a_distinct_y_for_distinct_values(self):
        """The bug this file exists for: all points sharing one stale y."""
        graph = self.graph([(1000, 0), (40_000, 0), (90_000, 0)])
        ys = [y for _x, y in self.points(graph)]
        self.assertEqual(len(set(ys)), 3, f"points collapsed onto one height: {ys}")

    def test_points_stay_inside_the_chart(self):
        graph = self.graph([(0, 0), (500_000, 500_000), (250_000, 10)])
        for x, y in self.points(graph):
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(y, HEIGHT)
            self.assertLessEqual(x, WIDTH + 1)

    def test_x_positions_increase_left_to_right(self):
        graph = self.graph([(1000, 100)] * 8)
        xs = [x for x, _y in self.points(graph)]
        self.assertEqual(xs, sorted(xs))

    def test_the_newest_point_lands_at_the_right_edge(self):
        graph = self.graph([(1000, 100)] * 6)
        self.assertAlmostEqual(self.points(graph)[-1][0], WIDTH, places=6)

    def test_a_bigger_value_sits_higher(self):
        graph = self.graph([(1000, 0), (90_000, 0)])
        low, high = self.points(graph)
        self.assertLess(high[1], low[1], "larger traffic must plot higher up")

    def test_the_newest_sample_eases_in(self):
        """Mid-animation the newest point sits between old and new."""
        settled = self.graph([(10_000, 0), (90_000, 0)], entry=1.0)
        halfway = self.graph([(10_000, 0), (90_000, 0)], entry=0.5)
        starting = self.graph([(10_000, 0), (90_000, 0)], entry=0.0)

        scale = settled.scale()
        end = settled.points_for(WIDTH, HEIGHT, scale, 0)[-1][1]
        mid = halfway.points_for(WIDTH, HEIGHT, scale, 0)[-1][1]
        begin = starting.points_for(WIDTH, HEIGHT, scale, 0)[-1][1]

        self.assertGreater(begin, mid)
        self.assertGreater(mid, end)

    def test_download_and_upload_are_plotted_separately(self):
        graph = self.graph([(90_000, 1000), (90_000, 1000)])
        scale = graph.scale()
        down = graph.points_for(WIDTH, HEIGHT, scale, 0)
        up = graph.points_for(WIDTH, HEIGHT, scale, 1)
        self.assertNotEqual([y for _x, y in down], [y for _x, y in up])

    def test_scale_never_collapses_to_zero(self):
        graph = self.graph([(0, 0)] * 4)
        self.assertGreater(graph.scale(), 0)

    def test_clearing_resets_the_animation(self):
        graph = self.graph([(1000, 100)] * 3, entry=0.2)
        graph.clear()
        self.assertEqual(graph.samples, [])
        self.assertEqual(graph._entry, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
