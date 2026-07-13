import importlib
import os
import tempfile
import unittest


SAME_STORY_TITLES = [
    "현대전 무기 된 허위정보…한미 군·정부 첫 연합 도상훈련",
    "유사시 ‘허위정보’ 유포 차단…첫 한미 합동 도상훈련 실시",
    "유사시 '허위정보' 대응 역량 강화…한미 '인지전' 대응 도상훈련 개최",
    "유사시 '허위정보' 유포 막는다…첫 한미 합동 정보전략 모의훈련",
]


class CandidateClusterAlgorithmTests(unittest.TestCase):
    def test_same_event_titles_form_one_cluster(self):
        from services.candidate_cluster_service import cluster_candidate_articles

        candidates = [
            {
                "id": index,
                "title": title,
                "description": "허위정보 유포에 대응하는 한미 도상훈련 관련 보도",
                "pub_date": "Mon, 13 Jul 2026 08:00:00 +0900",
                "score": 70 + index,
                "source": "연합뉴스" if index == 1 else f"언론사{index}",
            }
            for index, title in enumerate(SAME_STORY_TITLES, start=1)
        ]

        clusters = cluster_candidate_articles(candidates)

        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 4)

    def test_generic_shared_terms_do_not_merge_different_events(self):
        from services.candidate_cluster_service import cluster_candidate_articles

        candidates = [
            {
                "id": 1,
                "title": "한미 정상회담 개최…경제안보 협력 강화",
                "description": "정상 외교와 경제안보 협력을 논의했다",
                "pub_date": "Mon, 13 Jul 2026 08:00:00 +0900",
                "score": 80,
                "source": "연합뉴스",
            },
            {
                "id": 2,
                "title": "한미 연합훈련 실시…북한 도발 대응",
                "description": "군 당국이 연합훈련 계획을 발표했다",
                "pub_date": "Mon, 13 Jul 2026 09:00:00 +0900",
                "score": 80,
                "source": "연합뉴스",
            },
        ]

        clusters = cluster_candidate_articles(candidates)

        self.assertEqual(len(clusters), 2)

    def test_same_title_outside_time_window_stays_separate(self):
        from services.candidate_cluster_service import cluster_candidate_articles

        candidates = [
            {
                "id": 1,
                "title": "방송 플랫폼 허위정보 대응 공동 훈련",
                "description": "첫 번째 훈련",
                "pub_date": "Mon, 13 Jul 2026 08:00:00 +0900",
                "score": 80,
                "source": "연합뉴스",
            },
            {
                "id": 2,
                "title": "방송 플랫폼 허위정보 대응 공동 훈련",
                "description": "두 번째 훈련",
                "pub_date": "Thu, 16 Jul 2026 08:00:00 +0900",
                "score": 80,
                "source": "연합뉴스",
            },
        ]

        clusters = cluster_candidate_articles(candidates)

        self.assertEqual(len(clusters), 2)


class CandidateClusterStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        os.environ["CLIPPING_DB_PATH"] = os.path.join(self.tempdir.name, "storage.sqlite3")

        import app_config
        import services.clipping_store as clipping_store

        importlib.reload(app_config)
        self.store = importlib.reload(clipping_store)
        self.store.init_db()
        self._insert_candidates()

    def tearDown(self):
        self.tempdir.cleanup()

    def _insert_candidates(self):
        with self.store._connect() as conn:
            for index, title in enumerate(SAME_STORY_TITLES, start=1):
                article = conn.execute(
                    """
                    INSERT INTO articles (
                        link, original_link, title, description, source, domain,
                        pub_date, first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"https://news.example.com/{index}",
                        f"https://press.example.com/{index}",
                        title,
                        "허위정보 유포에 대응하는 한미 도상훈련 관련 보도",
                        "연합뉴스" if index == 2 else f"언론사{index}",
                        "press.example.com",
                        "Mon, 13 Jul 2026 08:00:00 +0900",
                        "2026-07-13T00:00:00+00:00",
                        "2026-07-13T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO clipping_candidates (
                        article_id, keyword, score, score_reasons,
                        suggested_category, status, created_at
                    ) VALUES (?, ?, ?, '[]', '기타', 'pending', ?)
                    """,
                    (article.lastrowid, "허위정보", 70 + index, "2026-07-13T00:00:00+00:00"),
                )

    def test_cluster_listing_collapses_related_articles(self):
        summary = self.store.recluster_pending_candidates()
        groups = self.store.list_candidate_groups("pending")

        self.assertEqual(summary["group_count"], 1)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["related_count"], 3)
        self.assertEqual(len(groups[0]["related_items"]), 3)

    def test_manual_representative_and_ungroup_are_persisted(self):
        self.store.recluster_pending_candidates()
        group = self.store.list_candidate_groups("pending")[0]
        target_id = group["related_items"][0]["id"]

        self.assertTrue(self.store.set_candidate_representative(target_id))
        self.assertEqual(self.store.list_candidate_groups("pending")[0]["id"], target_id)

        self.assertTrue(self.store.ungroup_candidate(target_id))
        self.store.recluster_pending_candidates()
        groups = self.store.list_candidate_groups("pending")
        self.assertEqual(len(groups), 2)
        self.assertTrue(any(group["id"] == target_id and group["related_count"] == 0 for group in groups))

    def test_accepting_representative_preserves_related_articles_neutrally(self):
        self.store.recluster_pending_candidates()
        representative = self.store.list_candidate_groups("pending")[0]

        accepted = self.store.accept_candidate(representative["id"], "기타")
        counts = self.store.list_candidate_status_counts()
        accepted_groups = self.store.list_candidate_groups("accepted")

        self.assertIsNotNone(accepted)
        self.assertEqual(counts.get("accepted"), 1)
        self.assertEqual(counts.get("covered"), 3)
        self.assertEqual(len(accepted_groups), 1)
        self.assertEqual(accepted_groups[0]["related_count"], 3)
        self.assertTrue(all(item["status"] == "covered" for item in accepted_groups[0]["related_items"]))

    def test_cluster_metadata_survives_storage_snapshot_round_trip(self):
        self.store.recluster_pending_candidates()
        original = self.store.list_candidate_groups("pending")
        snapshot = self.store.export_storage_snapshot()

        self.store.clear_pending_candidates()
        self.store.import_storage_snapshot(snapshot, replace=True)
        restored = self.store.list_candidate_groups("pending")

        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]["id"], original[0]["id"])
        self.assertEqual(restored[0]["related_count"], 3)
        self.assertIn("cluster_representative", snapshot["tables"]["clipping_candidates"][0])


if __name__ == "__main__":
    unittest.main()
