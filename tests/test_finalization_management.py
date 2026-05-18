import asyncio
import importlib
import os
import tempfile
import unittest


class FinalizationManagementTests(unittest.TestCase):
    def test_update_finalization_rebuilds_snapshot_and_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLIPPING_DB_PATH"] = os.path.join(tmpdir, "storage.sqlite3")

            import app_config
            import services.clipping_store as clipping_store

            importlib.reload(app_config)
            clipping_store = importlib.reload(clipping_store)
            clipping_store.init_db()

            original = "■ 기타\n\n▷ 테스트뉴스 : 기존 기사\n<https://example.com/old>\n"
            updated = (
                "■ 기타\n\n"
                "▷ 테스트뉴스 : 수정 기사\n<https://example.com/new>\n\n"
                "▷ 테스트뉴스 : 추가 기사\n<https://example.com/another>\n"
            )

            saved = asyncio.run(clipping_store.save_final_clipping_snapshot(original))
            result = clipping_store.update_finalization(saved["snapshot_id"], updated)
            snapshot = clipping_store.get_finalization(saved["snapshot_id"])
            summary = clipping_store.get_learning_summary()

            self.assertTrue(result["updated"])
            self.assertEqual(result["entry_count"], 2)
            self.assertEqual(snapshot["content"], updated)
            self.assertEqual(snapshot["entry_count"], 2)
            self.assertEqual(summary["finalized_event_count"], 2)


if __name__ == "__main__":
    unittest.main()
