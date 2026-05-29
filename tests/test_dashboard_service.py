import importlib
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone


KST = timezone(timedelta(hours=9), "Asia/Seoul")


class DashboardServiceTests(unittest.TestCase):
    def _load_service(self, tmpdir):
        os.environ["CLIPPING_DB_PATH"] = os.path.join(tmpdir, "storage.sqlite3")

        import app_config
        import services.clipping_store as clipping_store
        import services.dashboard_service as dashboard_service

        importlib.reload(app_config)
        clipping_store = importlib.reload(clipping_store)
        return importlib.reload(dashboard_service)

    def test_dashboard_window_starts_previous_day_10_and_ends_now(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dashboard_service = self._load_service(tmpdir)
            now = datetime(2026, 5, 29, 8, 30, tzinfo=KST)

            window = dashboard_service.get_dashboard_window(now)

            self.assertEqual(window["start_kst"], "2026-05-28T10:00:00+09:00")
            self.assertEqual(window["end_kst"], "2026-05-29T08:30:00+09:00")

    def test_dashboard_groups_related_articles_and_renders_representative_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dashboard_service = self._load_service(tmpdir)
            window = dashboard_service.get_dashboard_window(
                datetime(2026, 5, 29, 9, 0, tzinfo=KST)
            )
            candidates = [
                {
                    "id": 1,
                    "article_id": 1,
                    "keyword": "방송미디어통신심의위원회",
                    "score": 78,
                    "score_reasons": ["위원회 분류 키워드 포함 +16"],
                    "suggested_category": "위원회 관련",
                    "status": "pending",
                    "similar_group_key": "방송 심의 의결",
                    "title": "방송 심의 의결 결과 발표",
                    "description": "방송 관련 심의 의결 기사",
                    "source": "테스트뉴스",
                    "domain": "example.com",
                    "link": "https://news.example.com/a",
                    "original_link": "https://press.example.com/a",
                    "pub_date": "Fri, 29 May 2026 08:00:00 +0900",
                },
                {
                    "id": 2,
                    "article_id": 2,
                    "keyword": "방송미디어통신위원회",
                    "score": 60,
                    "score_reasons": ["방송·통신 관련 분류 키워드 포함 +8"],
                    "suggested_category": "위원회 관련",
                    "status": "pending",
                    "similar_group_key": "방송 심의 의결",
                    "title": "방송 심의 의결 결과 관련 보도",
                    "description": "같은 사안의 후속 기사",
                    "source": "다른뉴스",
                    "domain": "example.org",
                    "link": "https://news.example.com/b",
                    "original_link": "https://press.example.com/b",
                    "pub_date": "Fri, 29 May 2026 08:10:00 +0900",
                },
            ]

            payload = dashboard_service.build_dashboard_payload(
                candidates=candidates,
                keywords=["방송미디어통신심의위원회", "방송미디어통신위원회"],
                window=window,
                collection={"checked": 2, "created": 2},
            )

            section = next(item for item in payload["sections"] if item["category"] == "위원회 관련")
            self.assertEqual(payload["issue_count"], 1)
            self.assertEqual(payload["related_count"], 1)
            self.assertEqual(section["items"][0]["article"]["id"], 1)
            self.assertIn("▷ 테스트뉴스 : 방송 심의 의결 결과 발표", payload["final_content"])
            self.assertNotIn("다른뉴스", payload["final_content"])

    def test_dashboard_groups_near_duplicate_titles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dashboard_service = self._load_service(tmpdir)
            window = dashboard_service.get_dashboard_window(datetime(2026, 5, 29, 9, 0, tzinfo=KST))
            candidates = [
                {
                    "id": 1,
                    "article_id": 1,
                    "keyword": "방송미디어통신심의위원회",
                    "score": 81,
                    "score_reasons": [],
                    "suggested_category": "위원회 관련",
                    "status": "pending",
                    "similar_group_key": "a",
                    "title": "[단독] 방미심위, 온라인 플랫폼 심의 기준 손본다",
                    "description": "방미심위가 온라인 플랫폼 심의 기준 개편을 검토하고 있다.",
                    "source": "테스트뉴스",
                    "domain": "example.com",
                    "link": "https://news.example.com/a",
                    "original_link": "https://press.example.com/a",
                    "pub_date": "Fri, 29 May 2026 08:00:00 +0900",
                },
                {
                    "id": 2,
                    "article_id": 2,
                    "keyword": "방송미디어통신심의위원회",
                    "score": 76,
                    "score_reasons": [],
                    "suggested_category": "위원회 관련",
                    "status": "pending",
                    "similar_group_key": "b",
                    "title": "방미심위 온라인 플랫폼 심의기준 개편 검토",
                    "description": "온라인 플랫폼 심의 기준을 손보는 방안이 논의된다.",
                    "source": "다른뉴스",
                    "domain": "example.org",
                    "link": "https://news.example.com/b",
                    "original_link": "https://press.example.com/b",
                    "pub_date": "Fri, 29 May 2026 08:05:00 +0900",
                },
            ]

            payload = dashboard_service.build_dashboard_payload(
                candidates=candidates,
                keywords=["방송미디어통신심의위원회"],
                window=window,
                collection={"checked": 2, "created": 2},
            )

            self.assertEqual(payload["issue_count"], 1)
            self.assertEqual(payload["related_count"], 1)


if __name__ == "__main__":
    unittest.main()
