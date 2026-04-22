import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from utils.search_filters import filter_news_items
from utils.template_filters import extract_highlight_keyword, time_ago


@dataclass
class FakeNewsItem:
    title: str
    description: str
    link: str


class SearchFilterTests(unittest.TestCase):
    def test_include_filter_keeps_matching_items_only(self):
        items = [
            FakeNewsItem(title="유튜브 정책 변화", description="방송통신 기사", link="a"),
            FakeNewsItem(title="플랫폼 규제", description="일반 기사", link="b"),
        ]

        filtered = filter_news_items('플랫폼 +"유튜브"', items)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].link, "a")

    def test_exclude_filter_removes_matching_items(self):
        items = [
            FakeNewsItem(title="방송 정책", description="나무위키 요약", link="a"),
            FakeNewsItem(title="방송 정책", description="전문 기사", link="b"),
        ]

        filtered = filter_news_items("방송 -나무위키", items)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].link, "b")


class TemplateFilterTests(unittest.TestCase):
    def test_time_ago_for_recent_timestamp(self):
        value = datetime.now(timezone.utc) - timedelta(minutes=5)
        self.assertEqual(time_ago(value), "5분 전")

    def test_extract_highlight_keyword_removes_advanced_terms(self):
        keyword = '과방위 +"유튜브" -나무위키'
        self.assertEqual(extract_highlight_keyword(keyword), "과방위")


if __name__ == "__main__":
    unittest.main()
