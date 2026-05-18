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


class CandidateDedupTests(unittest.TestCase):
    def test_same_article_from_multiple_keywords_creates_one_candidate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLIPPING_DB_PATH"] = os.path.join(tmpdir, "storage.sqlite3")

            import app_config
            import services.clipping_store as clipping_store

            importlib.reload(app_config)
            clipping_store = importlib.reload(clipping_store)
            clipping_store.init_db()

            item = FakeNewsItem(
                title="방송 통신 위원회 심의 의결 플랫폼 정책",
                description="방송 통신 미디어 플랫폼 규제 관련 기사",
                link="https://news.example.com/article/1",
                originallink="https://press.example.com/article/1",
                source="테스트뉴스",
                pubDate="Mon, 18 May 2026 09:00:00 +0900",
                domain="press.example.com",
            )

            first = asyncio.run(clipping_store.create_candidate(item, "방송 통신 위원회"))
            second = asyncio.run(clipping_store.create_candidate(item, "플랫폼 규제"))
            candidates = clipping_store.list_candidates()

            self.assertTrue(first["created"])
            self.assertEqual(second["status"], "duplicate")
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["keyword"], "방송 통신 위원회, 플랫폼 규제")

    def test_same_original_link_with_different_search_links_is_one_candidate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLIPPING_DB_PATH"] = os.path.join(tmpdir, "storage.sqlite3")

            import app_config
            import services.clipping_store as clipping_store

            importlib.reload(app_config)
            clipping_store = importlib.reload(clipping_store)
            clipping_store.init_db()

            first_item = FakeNewsItem(
                title="방송 통신 위원회 심의 의결 플랫폼 정책",
                description="방송 통신 미디어 플랫폼 규제 관련 기사",
                link="https://n.news.naver.com/article/001/0001?query=a",
                originallink="https://press.example.com/article/1",
                source="테스트뉴스",
                pubDate="Mon, 18 May 2026 09:00:00 +0900",
                domain="press.example.com",
            )
            second_item = FakeNewsItem(
                title=first_item.title,
                description=first_item.description,
                link="https://n.news.naver.com/article/001/0001?query=b",
                originallink=first_item.originallink,
                source=first_item.source,
                pubDate=first_item.pubDate,
                domain=first_item.domain,
            )

            first = asyncio.run(clipping_store.create_candidate(first_item, "방송 통신 위원회"))
            second = asyncio.run(clipping_store.create_candidate(second_item, "플랫폼 규제"))
            candidates = clipping_store.list_candidates()

            self.assertTrue(first["created"])
            self.assertEqual(second["status"], "duplicate")
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["keyword"], "방송 통신 위원회, 플랫폼 규제")


if __name__ == "__main__":
    unittest.main()
