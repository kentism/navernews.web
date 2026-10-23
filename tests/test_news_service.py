import unittest
from unittest.mock import patch

import httpx

from services.news_service import NewsServiceError, fetch_news_page

HEADERS = {'X-Naver-Client-Id': 'test', 'X-Naver-Client-Secret': 'test'}


class NewsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_credentials_fail_explicitly(self):
        with self.assertRaises(NewsServiceError):
            await fetch_news_page('기사', {})

    async def test_transport_failure_is_not_empty_results(self):
        def handler(request):
            raise httpx.ConnectError('mock failure', request=request)
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch('services.news_service.httpx.AsyncClient', return_value=client), patch('services.news_service.HTTP_RETRY_COUNT', 1):
            with self.assertRaises(NewsServiceError):
                await fetch_news_page('기사', HEADERS)

    async def test_non_http_article_urls_are_not_rendered(self):
        def handler(request):
            return httpx.Response(200, json={'total': 1, 'items': [
                {'title': '기사', 'description': '', 'link': 'javascript:alert(1)'}]})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch('services.news_service.httpx.AsyncClient', return_value=client):
            page = await fetch_news_page('기사', HEADERS)
        self.assertEqual(page.raw_count, 1)
        self.assertEqual(page.items, [])
