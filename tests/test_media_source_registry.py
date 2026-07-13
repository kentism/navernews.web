import unittest


class MediaSourceRegistryTests(unittest.TestCase):
    def test_exact_domain_mapping_has_priority(self):
        from services.media_source_registry import resolve_media_source

        result = resolve_media_source("sports.khan.co.kr")

        self.assertTrue(result.matched)
        self.assertEqual(result.source, "스포츠경향")
        self.assertEqual(result.matched_domain, "sports.khan.co.kr")

    def test_known_parent_domain_covers_new_subdomain(self):
        from services.media_source_registry import resolve_media_source

        result = resolve_media_source("mobile.yna.co.kr")

        self.assertTrue(result.matched)
        self.assertEqual(result.source, "연합뉴스")
        self.assertEqual(result.matched_domain, "yna.co.kr")

    def test_url_and_www_prefix_are_normalized(self):
        from services.media_source_registry import resolve_media_source

        result = resolve_media_source("https://www.news.cpbc.co.kr/article/123")

        self.assertTrue(result.matched)
        self.assertEqual(result.domain, "news.cpbc.co.kr")
        self.assertEqual(result.source, "CPBC")

    def test_explicit_source_is_preserved_when_meaningful(self):
        from services.media_source_registry import resolve_media_source

        result = resolve_media_source("unknown.example", explicit_source="테스트뉴스")

        self.assertTrue(result.matched)
        self.assertEqual(result.source, "테스트뉴스")
        self.assertEqual(result.match_method, "explicit_source")

    def test_unknown_domain_is_not_guessed(self):
        from services.media_source_registry import resolve_media_source

        result = resolve_media_source("https://www.unknown.example/news/1")

        self.assertFalse(result.matched)
        self.assertEqual(result.source, "unknown.example")
        self.assertIsNone(result.matched_domain)

    def test_review_rows_are_sorted_and_include_aliases(self):
        from services.media_source_registry import list_media_mappings

        rows = list_media_mappings()
        domains = [row["domain"] for row in rows]

        self.assertEqual(domains, sorted(domains))
        self.assertIn("n.news.naver.com", domains)
        self.assertIn("news.cpbc.co.kr", domains)


class MediaSourceAuditTests(unittest.TestCase):
    def test_extract_site_name_prefers_open_graph_metadata(self):
        from services.media_source_audit import extract_site_name

        html = """
            <html><head>
                <meta name="application-name" content="보조 이름">
                <meta property="og:site_name" content="공식 매체명">
                <title>기사 제목 | 사이트</title>
            </head></html>
        """

        self.assertEqual(extract_site_name(html), "공식 매체명")

    def test_consistent_metadata_becomes_review_proposal(self):
        from services.media_source_audit import propose_source_name

        proposal = propose_source_name(["테스트뉴스", " 테스트뉴스 "])

        self.assertEqual(proposal["proposed_source"], "테스트뉴스")
        self.assertEqual(proposal["review_status"], "metadata_consistent")

    def test_conflicting_metadata_requires_manual_review(self):
        from services.media_source_audit import propose_source_name

        proposal = propose_source_name(["뉴스A", "뉴스B"])

        self.assertEqual(proposal["proposed_source"], "")
        self.assertEqual(proposal["review_status"], "metadata_conflict")

    def test_review_markdown_escapes_table_delimiters(self):
        from services.media_source_audit import render_review_markdown

        document = render_review_markdown(
            [
                {
                    "domain": "example.com",
                    "proposed_source": "예시 | 뉴스",
                    "review_status": "metadata_consistent",
                    "metadata_names": ["예시 | 뉴스"],
                }
            ],
            checked_count=1,
            observed_domain_count=1,
        )

        self.assertIn("예시 \\| 뉴스", document)


if __name__ == "__main__":
    unittest.main()
