import asyncio
import importlib
import os
import tempfile
import unittest
from dataclasses import dataclass


@dataclass
class FakeNewsItem:
    title: str
    description: str
    link: str
    originallink: str
    source: str
    pubDate: str
    domain: str


class UrlNormalizationTests(unittest.TestCase):
    def test_normalize_article_url_removes_only_utm_params(self):
        import services.clipping_store as clipping_store

        url = (
            "https://press.example.com/view?"
            "idxno=123&utm_source=naver&utm_medium=referral&empty=&UTM_campaign=spring#section"
        )

        self.assertEqual(
            clipping_store.normalize_article_url(url),
            "https://press.example.com/view?idxno=123&empty=#section",
        )

    def test_finalization_matches_article_after_utm_cleanup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLIPPING_DB_PATH"] = os.path.join(tmpdir, "storage.sqlite3")

            import app_config
            import services.clipping_store as clipping_store

            importlib.reload(app_config)
            clipping_store = importlib.reload(clipping_store)
            clipping_store.init_db()

            item = FakeNewsItem(
                title="Example policy article",
                description="Example description",
                link="https://n.news.naver.com/article/001/0001",
                originallink="https://press.example.com/view?idxno=123&utm_source=naver",
                source="Example News",
                pubDate="Mon, 18 May 2026 09:00:00 +0900",
                domain="press.example.com",
            )

            clipping_store.upsert_article(item)
            content = (
                "기타\n"
                "Example News : Example policy article\n"
                "<https://press.example.com/view?idxno=123&utm_source=naver&utm_medium=referral>\n"
            )

            result = asyncio.run(clipping_store.save_final_clipping_snapshot(content))

            self.assertEqual(result["entry_count"], 1)
            self.assertEqual(result["matched_count"], 1)
            entries = clipping_store.parse_final_clipping_entries(content)
            self.assertEqual(entries[0]["link"], "https://press.example.com/view?idxno=123")


if __name__ == "__main__":
    unittest.main()
