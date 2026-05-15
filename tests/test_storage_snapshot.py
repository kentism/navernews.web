import importlib
import os
import tempfile
import unittest


class StorageSnapshotTests(unittest.TestCase):
    def test_export_import_round_trip_preserves_candidate_keywords(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLIPPING_DB_PATH"] = os.path.join(tmpdir, "storage.sqlite3")

            import app_config
            import services.clipping_store as clipping_store

            importlib.reload(app_config)
            clipping_store = importlib.reload(clipping_store)

            clipping_store.init_db()
            clipping_store.add_candidate_keyword("roundtrip")

            snapshot = clipping_store.export_storage_snapshot()
            clipping_store.remove_candidate_keyword("roundtrip")
            self.assertEqual(clipping_store.list_candidate_keywords(), [])

            result = clipping_store.import_storage_snapshot(snapshot, replace=True)

            self.assertEqual(clipping_store.list_candidate_keywords(), ["roundtrip"])
            self.assertEqual(result["imported_counts"]["candidate_keywords"], 1)


if __name__ == "__main__":
    unittest.main()
