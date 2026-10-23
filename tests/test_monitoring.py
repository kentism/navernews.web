import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from services.monitoring import cache_search_results, poll_naver_news_task, state
from services.news_service import NewsItem, NewsServiceError


class MonitoringTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.reset_state()

    def tearDown(self):
        self.reset_state()

    def reset_state(self):
        for value in vars(state).values():
            value.clear()

    async def test_failed_keyword_does_not_block_another_keyword_notification(self):
        queue = asyncio.Queue()
        state.sse_connections['client'] = queue
        state.watch_registry.update({'실패': {'client'}, '정상': {'client'}})
        old = NewsItem(title='이전', link='https://example.com/old', description='')
        new = NewsItem(title='신규', link='https://example.com/new', description='')
        cache_search_results('정상', [old])
        with patch('services.monitoring.fetch_news', new=AsyncMock(side_effect=[NewsServiceError('mock'), [new]])), \
                patch('services.monitoring.asyncio.sleep', new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await poll_naver_news_task()
        self.assertIn('[정상]', queue.get_nowait())

    async def test_offline_stale_watch_does_not_make_api_calls(self):
        state.watch_registry['오프라인'] = {'client'}
        with patch('services.monitoring.fetch_news', new=AsyncMock()) as fetch, \
                patch('services.monitoring.asyncio.sleep', new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await poll_naver_news_task()
        fetch.assert_not_awaited()
        self.assertEqual(state.watch_registry, {})

    def test_search_cache_is_bounded(self):
        for index in range(150):
            cache_search_results(str(index), [])
        self.assertEqual(len(state.search_cache), 128)
