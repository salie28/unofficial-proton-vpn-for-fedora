"""Tests for the recents store. Run: python3 -m unittest discover -s tests"""

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unofficial_protonvpn.recents import RecentsStore, RecentServer  # noqa: E402


class RecentsStoreTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "recents.json"
        self.store = RecentsStore(path=self.path)

    def tearDown(self):
        self._dir.cleanup()

    def test_starts_empty_when_file_missing(self):
        self.assertEqual(self.store.servers, [])
        self.assertEqual(self.store.most_recent(3), [])

    def test_records_and_orders_most_recent_first(self):
        for name in ("AT#171", "DE#42", "CH#12"):
            self.store.record(name)
        self.assertEqual(
            [s.server_name for s in self.store.most_recent(3)],
            ["CH#12", "DE#42", "AT#171"],
        )

    def test_reconnect_moves_to_front_without_duplicating(self):
        for name in ("AT#171", "DE#42", "CH#12"):
            self.store.record(name)
        self.store.record("AT#171")
        names = [s.server_name for s in self.store.servers]
        self.assertEqual(names, ["AT#171", "CH#12", "DE#42"])
        self.assertEqual(names.count("AT#171"), 1)
        self.assertEqual(self.store.servers[0].use_count, 2)

    def test_metadata_is_refreshed_but_not_erased_on_reconnect(self):
        self.store.record("AT#171", exit_country="AT", city="Vienna")
        # A later connect with no city known must not wipe the known city.
        self.store.record("AT#171")
        entry = self.store.servers[0]
        self.assertEqual(entry.city, "Vienna")
        self.assertEqual(entry.exit_country, "AT")

    def test_persists_across_instances(self):
        self.store.record("AT#171", exit_country="AT", city="Vienna")
        reloaded = RecentsStore(path=self.path)
        self.assertEqual(len(reloaded.servers), 1)
        self.assertEqual(reloaded.servers[0].label, "Vienna - AT#171")

    def test_respects_max_entries(self):
        store = RecentsStore(path=self.path, max_entries=3)
        for i in range(10):
            store.record(f"AT#{i}")
        self.assertEqual(len(store.servers), 3)
        self.assertEqual(
            [s.server_name for s in store.servers], ["AT#9", "AT#8", "AT#7"]
        )

    def test_corrupt_file_degrades_to_empty_and_is_quarantined(self):
        self.path.write_text("{ this is not json", encoding="utf-8")
        store = RecentsStore(path=self.path)
        self.assertEqual(store.servers, [])
        self.assertTrue(self.path.with_suffix(".json.corrupt").exists(),
                        "corrupt file should be moved aside, not deleted")

    def test_garbage_entries_are_skipped_not_fatal(self):
        self.path.write_text(json.dumps({
            "version": 1,
            "servers": [
                {"server_name": "AT#171"},
                {"no_name": True},
                "not a dict",
                {"server_name": ""},
                {"server_name": "DE#42", "use_count": "not a number"},
            ],
        }), encoding="utf-8")
        store = RecentsStore(path=self.path)
        # Unusable rows are dropped; a bad field only costs that field.
        self.assertEqual([s.server_name for s in store.servers], ["AT#171", "DE#42"])
        self.assertEqual(store.servers[1].use_count, 0)

    def test_file_is_private(self):
        self.store.record("AT#171")
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode, 0o600, f"expected 0600, got {oct(mode)}")

    def test_save_leaves_no_temp_files_behind(self):
        self.store.record("AT#171")
        leftovers = [p.name for p in self.path.parent.iterdir()
                     if p.name.startswith(".recents-")]
        self.assertEqual(leftovers, [])

    def test_forget_and_clear(self):
        self.store.record("AT#171")
        self.store.record("DE#42")
        self.assertTrue(self.store.forget("AT#171"))
        self.assertFalse(self.store.forget("AT#171"))
        self.assertEqual([s.server_name for s in self.store.servers], ["DE#42"])
        self.store.clear()
        self.assertEqual(self.store.servers, [])

    def test_label_falls_back_when_metadata_missing(self):
        self.assertEqual(RecentServer("AT#171").label, "AT#171")
        self.assertEqual(RecentServer("AT#171", exit_country="AT").label, "AT - AT#171")

    def test_record_ignores_empty_server_name(self):
        self.assertIsNone(self.store.record(""))
        self.assertEqual(self.store.servers, [])

    def test_unwritable_directory_does_not_raise(self):
        path = Path(self._dir.name) / "nested" / "recents.json"
        store = RecentsStore(path=path)
        os.chmod(self._dir.name, 0o500)  # read+execute only
        try:
            store.record("AT#171")  # must not raise
            self.assertEqual(store.servers[0].server_name, "AT#171")
        finally:
            os.chmod(self._dir.name, 0o700)


class SeparateStoresOverOneFileTest(unittest.TestCase):
    """The window and the tray each hold a store over the same file.

    Without a reload the window keeps serving what it read at startup, so
    Recents looks broken in the app while working in the tray.
    """

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.path = Path(self.directory) / "recents.json"

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_a_second_store_sees_writes_after_reload(self):
        writer = RecentsStore(path=self.path)
        reader = RecentsStore(path=self.path)

        self.assertEqual(reader.most_recent(), [])   # caches the empty file

        writer.record("AT#215", exit_country="AT", city="Vienna")

        self.assertEqual(reader.most_recent(), [],
                         "without a reload the cache is stale, by design")

        reader.reload()
        self.assertEqual([s.server_name for s in reader.most_recent()], ["AT#215"])

    def test_reload_on_an_empty_file_is_harmless(self):
        store = RecentsStore(path=self.path)
        store.reload()
        self.assertEqual(store.most_recent(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
