import unittest
from unittest.mock import AsyncMock, patch

from services.news_service import NewsItem, NewsPage, NewsServiceError
from services.search_collection import collect_articles, parse_date_range


def article(number, published, original=""):
    return NewsItem(title=f"기사 {number}", description="검색 결과", source="테스트뉴스",
                    link=f"https://example.com/{number}", originallink=original, pubDate=published)


class DateRangeTests(unittest.TestCase):
    def test_date_range_uses_korean_midnight_and_includes_end_date(self):
        start, end = parse_date_range("2026-10-23", "2026-10-23")
        self.assertEqual(start.isoformat(), "2026-10-23T00:00:00+09:00")
        self.assertEqual(end.isoformat(), "2026-10-24T00:00:00+09:00")

    def test_reversed_dates_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_date_range("2026-10-24", "2026-10-23")


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_collects_boundary_date_and_deduplicates_only_identical_urls(self):
        items = [article(1, "Fri, 23 Oct 2026 08:00:00 +0900", "https://press.test/1?utm_source=naver"),
                 article(2, "Fri, 23 Oct 2026 07:00:00 +0900", "https://press.test/1"),
                 article(3, "Thu, 22 Oct 2026 00:00:00 +0900"),
                 article(4, "Wed, 21 Oct 2026 23:59:59 +0900")]
        pages = [NewsPage(items[:2], 4, 2, 1, 2, items[1].pubDate),
                 NewsPage(items[2:], 4, 2, 3, 2, items[3].pubDate)]
        with patch("services.search_collection.fetch_news_page", new=AsyncMock(side_effect=pages)):
            result = await collect_articles("기사", {}, "2026-10-22", "2026-10-23", page_size=2)
        self.assertEqual([item.title for item in result.items], ["기사 1", "기사 3"])
        self.assertTrue(result.complete)
        self.assertEqual(result.duplicate_count, 1)

    async def test_reports_limit_instead_of_claiming_complete(self):
        items = [article(i, "Fri, 23 Oct 2026 08:00:00 +0900") for i in range(4)]
        pages = [NewsPage(items[:2], 10, 2, 1, 2, items[1].pubDate),
                 NewsPage(items[2:], 10, 2, 3, 2, items[3].pubDate)]
        with patch("services.search_collection.fetch_news_page", new=AsyncMock(side_effect=pages)):
            result = await collect_articles("기사", {}, "2026-10-01", "2026-10-23", page_size=2, max_results=4)
        self.assertFalse(result.complete)
        self.assertTrue(result.limit_reached)

    async def test_upstream_failure_is_not_returned_as_empty_success(self):
        with patch("services.search_collection.fetch_news_page", new=AsyncMock(side_effect=NewsServiceError("mock failure"))):
            with self.assertRaises(NewsServiceError):
                await collect_articles("기사", {}, "2026-10-22", "2026-10-23")

    async def test_invalid_publication_dates_are_reported(self):
        item = article(1, "invalid")
        with patch("services.search_collection.fetch_news_page", new=AsyncMock(return_value=NewsPage([item], 1, 1, 1, 100, "invalid"))):
            result = await collect_articles("기사", {}, "2026-10-22", "2026-10-23")
        self.assertEqual(result.invalid_date_count, 1)
        self.assertEqual(result.items, [])
