"""
Tests for future-failure reporting.

The bug these exist for: `GLib.idle_add(f.result)` repeats forever, because
idle sources repeat while the callback returns something truthy and
`Future.result()` returns the connection result. In the running app that
reopened Proton's error dialog about twenty times a second.
"""

import sys
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unofficial_protonvpn.futures import report_failure  # noqa: E402


class ReportFailureTest(unittest.TestCase):
    def setUp(self):
        self.scheduled = []

        def fake_idle_add(callback, *args):
            self.scheduled.append(callback)
            return 1

        patcher = patch("unofficial_protonvpn.futures.GLib.idle_add", fake_idle_add)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_scheduled(self):
        """Run what was queued, returning each callback's return value."""
        return [callback() for callback in self.scheduled]

    def test_a_successful_future_reports_nothing(self):
        future = Future()
        future.set_result("connected")
        report_failure(future, "Connect")
        self.assertEqual(self.run_scheduled(), [False])

    def test_the_idle_source_never_repeats(self):
        """The whole point: it must remove itself after one pass."""
        from gi.repository import GLib

        future = Future()
        future.set_result("connected")
        report_failure(future, "Connect")
        for returned in self.run_scheduled():
            self.assertEqual(returned, GLib.SOURCE_REMOVE)
            self.assertFalse(returned, "a truthy return makes GLib repeat it")

    def test_a_truthy_result_still_does_not_repeat(self):
        """Future.result() returning something truthy was the actual trigger."""
        future = Future()
        future.set_result({"connection": "object"})
        report_failure(future, "Connect")
        self.assertEqual(self.run_scheduled(), [False])

    def test_a_failed_future_raises_on_the_main_thread(self):
        future = Future()
        future.set_exception(RuntimeError("no route to host"))
        report_failure(future, "Connect")

        with self.assertRaises(RuntimeError):
            self.run_scheduled()

    def test_nothing_is_scheduled_until_the_future_finishes(self):
        future = Future()
        report_failure(future, "Connect")
        self.assertEqual(self.scheduled, [])

        future.set_result("connected")
        self.assertEqual(len(self.scheduled), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
