import asyncio
import importlib
import os
import tempfile
import unittest
from dataclasses import dataclass
from datetime import timedelta


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

    def test_clear_pending_candidates_preserves_reviewed_candidates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLIPPING_DB_PATH"] = os.path.join(tmpdir, "storage.sqlite3")

            import app_config
            import services.clipping_store as clipping_store

            importlib.reload(app_config)
            clipping_store = importlib.reload(clipping_store)
            clipping_store.init_db()

            items = [
                FakeNewsItem(
                    title=f"KCC KCC KCC policy update {idx}",
                    description="KCC policy article",
                    link=f"https://news.example.com/article/{idx}",
                    originallink=f"https://press.example.com/article/{idx}",
                    source="Example News",
                    pubDate="Mon, 18 May 2026 09:00:00 +0900",
                    domain="press.example.com",
                )
                for idx in range(1, 4)
            ]

            created = [
                asyncio.run(clipping_store.create_candidate(item, "KCC KCC KCC"))
                for item in items
            ]
            self.assertTrue(all(item["created"] for item in created))

            pending = clipping_store.list_candidates()
            clipping_store.accept_candidate(pending[0]["id"], "기타")
            clipping_store.reject_candidate(pending[1]["id"])

            deleted = clipping_store.clear_pending_candidates()

            self.assertEqual(deleted, 1)
            self.assertEqual(clipping_store.list_candidates(), [])
            self.assertEqual(len(clipping_store.list_candidates(status="accepted")), 1)
            self.assertEqual(len(clipping_store.list_candidates(status="rejected")), 1)

    def test_rejected_candidate_can_be_restored_or_deleted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLIPPING_DB_PATH"] = os.path.join(tmpdir, "storage.sqlite3")

            import app_config
            import services.clipping_store as clipping_store

            importlib.reload(app_config)
            clipping_store = importlib.reload(clipping_store)
            clipping_store.init_db()

            item = FakeNewsItem(
                title="KCC KCC KCC policy restore candidate",
                description="KCC policy article",
                link="https://news.example.com/article/restore",
                originallink="https://press.example.com/article/restore",
                source="Example News",
                pubDate="Mon, 18 May 2026 09:00:00 +0900",
                domain="press.example.com",
            )

            asyncio.run(clipping_store.create_candidate(item, "KCC KCC KCC"))
            candidate_id = clipping_store.list_candidates()[0]["id"]

            self.assertTrue(clipping_store.reject_candidate(candidate_id))
            self.assertEqual(len(clipping_store.list_candidates(status="rejected")), 1)

            self.assertTrue(clipping_store.restore_rejected_candidate(candidate_id))
            self.assertEqual(len(clipping_store.list_candidates()), 1)
            self.assertEqual(clipping_store.list_candidates()[0]["status"], "pending")

            self.assertTrue(clipping_store.delete_candidate(candidate_id))
            self.assertEqual(clipping_store.list_candidate_status_counts().get("pending", 0), 0)

    def test_cleanup_stale_pending_candidates_only_removes_old_pending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLIPPING_DB_PATH"] = os.path.join(tmpdir, "storage.sqlite3")

            import app_config
            import services.clipping_store as clipping_store

            importlib.reload(app_config)
            clipping_store = importlib.reload(clipping_store)
            clipping_store.init_db()

            items = [
                FakeNewsItem(
                    title=f"KCC KCC KCC policy stale {idx}",
                    description="KCC policy article",
                    link=f"https://news.example.com/article/stale-{idx}",
                    originallink=f"https://press.example.com/article/stale-{idx}",
                    source="Example News",
                    pubDate="Mon, 18 May 2026 09:00:00 +0900",
                    domain="press.example.com",
                )
                for idx in range(1, 4)
            ]

            for item in items:
                asyncio.run(clipping_store.create_candidate(item, "KCC KCC KCC"))

            pending = clipping_store.list_candidates()
            clipping_store.reject_candidate(pending[1]["id"])
            stale_at = clipping_store.to_iso(clipping_store.utc_now() - timedelta(days=30))
            with clipping_store._connect() as conn:
                conn.execute(
                    "UPDATE clipping_candidates SET created_at = ? WHERE id IN (?, ?)",
                    (stale_at, pending[0]["id"], pending[1]["id"]),
                )

            deleted = clipping_store.cleanup_stale_pending_candidates(days=7)

            self.assertEqual(deleted, 1)
            self.assertEqual(len(clipping_store.list_candidates()), 1)
            self.assertEqual(len(clipping_store.list_candidates(status="rejected")), 1)


if __name__ == "__main__":
    unittest.main()
