import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app_config import APP_ACCESS_KEY
from main import app
from services.article_title_confirmation import (
    TOKEN_TTL, TitleConfirmationService, issue_confirmation, verify_confirmation,
)
from services.article_titles import TitleResult, TitleSample
from services.news_service import NewsItem, NewsPage
from services.search_collection import CollectionResult

SHORT = '방송 정책 개선을 위한 새로운 제도와 향후...'
FULL = '방송 정책 개선을 위한 새로운 제도와 향후 추진 계획 발표'
URL = 'https://news.kbs.co.kr/news/pc/view/view.do?ncd=123'


def article(**kwargs):
    values = dict(title=SHORT, link=URL, originallink=URL, description='요약')
    return NewsItem(**(values | kwargs))


class CapabilityTests(unittest.TestCase):
    def test_issue_and_verify_preserve_the_server_provided_url_and_title(self):
        capability = issue_confirmation(article())
        sample = verify_confirmation(capability['token'])
        self.assertEqual((sample.url, sample.api_title), (URL, SHORT))
        self.assertEqual(len(capability['key']), 64)

    def test_supported_articles_get_capabilities_without_an_ellipsis_or_minimum_length(self):
        for title in [FULL, SHORT.removesuffix('...'), '방송...']:
            with self.subTest(title=title):
                capability = issue_confirmation(article(title=title))
                self.assertEqual(verify_confirmation(capability['token']).api_title, title)

    def test_no_fetch_capability_for_invalid_title_lengths_or_unsupported_urls(self):
        for item in [article(title=''), article(title='가' * 401),
                     article(link='https://evil.test/a', originallink='https://evil.test/a')]:
            self.assertIsNone(issue_confirmation(item))

    def test_falls_back_to_supported_naver_article_without_fetching_it(self):
        naver = 'https://n.news.naver.com/mnews/article/001/123'
        capability = issue_confirmation(article(link=naver, originallink='https://unknown.test/a'))
        self.assertEqual(verify_confirmation(capability['token']).url, naver)

    def test_rejects_tampering_unicode_and_expired_tokens(self):
        capability = issue_confirmation(article())
        for token in [capability['token'] + '0', 'invalid', '한글.한글', 'x' * 8193]:
            with self.subTest(token=token[:20]), self.assertRaises(ValueError):
                verify_confirmation(token)
        with patch('services.article_title_confirmation.time.time', return_value=1000):
            old = issue_confirmation(article())['token']
        with patch('services.article_title_confirmation.time.time', return_value=1000 + TOKEN_TTL + 1):
            with self.assertRaises(ValueError):
                verify_confirmation(old)


class ConfirmationServiceTests(unittest.IsolatedAsyncioTestCase):
    def result(self, status='extended', url=URL):
        return TitleResult(url, SHORT, 'api', status=status, candidate_title=FULL, final_url=url)

    async def test_only_matching_results_expose_a_selectable_title_and_correct_source(self):
        for status, expected in [('extended', 'confirmed'), ('punctuation_only', 'confirmed'),
                                 ('matched', 'no_change'), ('source_also_short', 'no_change'),
                                 ('no_title', 'no_change'), ('unverified', 'unverified'),
                                 ('conflict', 'unverified'), ('timeout', 'failed'), ('http_403', 'failed')]:
            with self.subTest(status=status):
                service = TitleConfirmationService()
                service._fetch = AsyncMock(return_value=self.result(status))
                value = await service.confirm(TitleSample(URL, SHORT))
                self.assertEqual(value['status'], expected)
                if expected == 'confirmed':
                    self.assertEqual(value['title'], FULL)
                    self.assertEqual(value['source'], 'original')
                else:
                    self.assertNotIn('title', value)
                await service.close()
        service = TitleConfirmationService()
        service._fetch = AsyncMock(return_value=self.result(url='https://n.news.naver.com/mnews/article/001/123'))
        self.assertEqual((await service.confirm(TitleSample(URL, SHORT)))['source'], 'naver')
        await service.close()

    async def test_duplicate_requests_share_work_and_a_third_unique_job_is_busy(self):
        service = TitleConfirmationService()
        release, started = asyncio.Event(), asyncio.Event()
        calls = 0
        async def fetch(sample):
            nonlocal calls
            calls += 1
            if calls == 2:
                started.set()
            await release.wait()
            return self.result()
        service._fetch = fetch
        sample = TitleSample(URL, SHORT)
        requests = [asyncio.create_task(service.confirm(value)) for value in
                    [sample, sample, TitleSample(URL + '&other=1', SHORT)]]
        await started.wait()
        busy = await service.confirm(TitleSample(URL + '&third=1', SHORT))
        self.assertEqual(busy['status'], 'busy')
        self.assertEqual(calls, 2)
        release.set()
        results = await asyncio.gather(*requests)
        self.assertEqual(results[0], results[1])
        await service.close()
        self.assertFalse(service.jobs)

    async def test_shutdown_cancels_pending_jobs(self):
        service = TitleConfirmationService()
        started = asyncio.Event()
        async def fetch(sample):
            started.set()
            await asyncio.Event().wait()
        service._fetch = fetch
        request = asyncio.create_task(service.confirm(TitleSample(URL, SHORT)))
        await started.wait()
        await service.close()
        self.assertIsInstance((await asyncio.gather(request, return_exceptions=True))[0], asyncio.CancelledError)


class ConfirmationRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.token = issue_confirmation(article())['token']

    def tearDown(self):
        self.client.close()

    def login(self):
        self.client.cookies.set('access_token', APP_ACCESS_KEY)

    def test_endpoint_requires_authentication_and_a_signed_capability(self):
        with patch.object(TitleConfirmationService, 'confirm', new=AsyncMock()) as confirm:
            self.assertEqual(self.client.post('/api/search/title-confirmation', data={'token': self.token}).status_code, 401)
            self.login()
            self.assertEqual(self.client.post('/api/search/title-confirmation', data={'token': 'fake', 'url': URL}).status_code, 400)
            self.assertEqual(self.client.post('/api/search/title-confirmation', data={'url': URL}).status_code, 422)
            self.assertEqual(self.client.post('/api/search/title-confirmation', data={'token': self.token},
                                              headers={'Origin': 'https://evil.test'}).status_code, 403)
            confirm.assert_not_awaited()

    def test_valid_request_passes_only_server_signed_claims_and_disables_http_caching(self):
        self.login()
        value = {'status': 'confirmed', 'title': FULL, 'source': 'original', 'source_url': URL}
        with patch.object(TitleConfirmationService, 'confirm', new=AsyncMock(return_value=value)) as confirm:
            response = self.client.post('/api/search/title-confirmation', data={'token': self.token, 'url': 'https://evil.test'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.json(), value)
        self.assertEqual(confirm.call_args.args[0].url, URL)

    def test_latest_and_period_cards_include_opt_in_controls_without_fetching_titles(self):
        self.login()
        items = [article(), article(title=FULL), article(link='https://unsupported.test/a', originallink='https://unsupported.test/a')]
        page = NewsPage(items, 3, 3, 1, 20)
        with patch('routers.search.fetch_news_page', new=AsyncMock(return_value=page)), \
                patch.object(TitleConfirmationService, 'confirm', new=AsyncMock()) as confirm:
            response = self.client.post('/search-results', data={'keyword': '방송'})
            confirm.assert_not_awaited()
        parsed = BeautifulSoup(response.text, 'html.parser')
        buttons = parsed.select('[data-title-confirm]')
        self.assertEqual(len(buttons), 3)
        self.assertTrue(buttons[0]['data-title-token'])
        self.assertTrue(buttons[1]['data-title-token'])
        self.assertEqual(buttons[2]['data-title-token'], '')
        self.assertIn('제목이 잘린 경우', parsed.get_text())
        self.assertIn(SHORT, parsed.select_one('.news-title').get_text())
        checkbox = parsed.select_one('[data-use-confirmed-title]')
        self.assertFalse(checkbox.has_attr('checked'))
        self.assertTrue(parsed.select_one('[data-title-result]').has_attr('hidden'))
        self.assertEqual(parsed.select_one('.btn-clip-trigger')['data-title'], SHORT)
        with patch('routers.search.collect_articles', new=AsyncMock(return_value=CollectionResult(items, 3, 0, 0, True, False))):
            period = self.client.post('/api/search/collect', data={'keyword': '방송', 'since': '2026-10-23'})
        self.assertEqual(len(BeautifulSoup(period.json()['html'], 'html.parser').select('[data-title-confirm]')), 3)
