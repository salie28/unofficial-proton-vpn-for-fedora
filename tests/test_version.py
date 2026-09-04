"""
Tests for how the app treats Proton's version.

Nothing is pinned: it runs against whatever is installed. These check it
neither blocks on a version it has not seen, nor stays silent about one.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unofficial_protonvpn.branding import (  # noqa: E402
    SUPPORTED_UPSTREAM_MAJOR, TESTED_UPSTREAM_VERSIONS,
)


class VersionNoteTest(unittest.TestCase):
    def note_for(self, version):
        """Run the version note against a given upstream version."""
        from unofficial_protonvpn import __main__ as entry

        logged = {"info": [], "warning": []}

        class FakeLogger:
            def info(self, message, **_kwargs):
                logged["info"].append(message)

            def warning(self, message, **_kwargs):
                logged["warning"].append(message)

        with patch("unofficial_protonvpn.identity.upstream_version",
                   return_value=version), \
             patch("proton.vpn.logging.getLogger", return_value=FakeLogger()), \
             patch.object(sys, "stderr"):
            entry._note_upstream_version()
        return logged

    def test_a_tested_version_is_recorded_quietly(self):
        version = TESTED_UPSTREAM_VERSIONS[0] + ".1"
        logged = self.note_for(version)
        self.assertEqual(logged["warning"], [], "a tested version must not warn")
        self.assertTrue(any(version in m for m in logged["info"]))

    def test_a_newer_minor_release_does_not_warn(self):
        """Proton ships every couple of weeks; nagging every time is noise."""
        logged = self.note_for(f"{SUPPORTED_UPSTREAM_MAJOR}.99.0")
        self.assertEqual(logged["warning"], [])
        self.assertTrue(logged["info"])

    def test_a_different_major_series_warns(self):
        newer_major = str(int(SUPPORTED_UPSTREAM_MAJOR) + 1)
        logged = self.note_for(f"{newer_major}.0.0")
        self.assertTrue(logged["warning"], "a major bump is worth saying out loud")
        self.assertIn(newer_major, logged["warning"][0])

    def test_an_unknown_version_does_not_raise(self):
        self.note_for("unknown")

    def test_nothing_is_pinned(self):
        """The app must never refuse to start over a version number."""
        import inspect

        from unofficial_protonvpn import __main__ as entry
        source = inspect.getsource(entry._note_upstream_version)
        for refusal in ("sys.exit", "raise SystemExit", "return 1"):
            self.assertNotIn(refusal, source,
                             "the version note must never stop the app")


if __name__ == "__main__":
    unittest.main(verbosity=2)
