import importlib
import os
import tempfile
import unittest


class CategoryClassificationTests(unittest.TestCase):
    def _load_store(self, tmpdir):
        os.environ["CLIPPING_DB_PATH"] = os.path.join(tmpdir, "storage.sqlite3")

        import app_config
        import services.clipping_store as clipping_store

        importlib.reload(app_config)
        clipping_store = importlib.reload(clipping_store)
        clipping_store.init_db()
        return clipping_store

    def test_media_commission_is_related_institution_not_internal_committee(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            clipping_store = self._load_store(tmpdir)

            _, category, reasons = clipping_store.score_article(
                "방송미디어통신위원회 플랫폼 정책 발표",
                "방미통위가 온라인 플랫폼 제도 개선안을 논의했다.",
                "방송미디어통신위원회",
            )

            self.assertEqual(category, "유관기관 관련")
            self.assertTrue(any("방미통위" in reason for reason in reasons))

    def test_review_committee_stays_internal_committee(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            clipping_store = self._load_store(tmpdir)

            _, category, reasons = clipping_store.score_article(
                "방송미디어통신심의위원회 심의 결과 발표",
                "방미심위가 회의 결과를 공개했다.",
                "방송미디어통신심의위원회",
            )

            self.assertEqual(category, "위원회 관련")
            self.assertTrue(any("방미심위" in reason for reason in reasons))


if __name__ == "__main__":
    unittest.main()
