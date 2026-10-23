import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from bs4 import BeautifulSoup

from app_config import APP_ACCESS_KEY
from main import app
from services.news_service import NewsItem, NewsPage, NewsServiceError
from services.search_collection import CollectionResult
from utils.template_filters import highlight_keyword


class AppTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def login(self):
        self.client.cookies.set('access_token', APP_ACCESS_KEY)

    def test_notification_and_archive_endpoints_require_authentication(self):
        for url in ['/api/stream/notifications?client_id=test', '/api/storage/export', '/api/storage/status']:
            self.assertEqual(self.client.get(url).status_code, 401, url)
        self.assertEqual(self.client.post('/api/search/collect', data={'keyword': '기사', 'since': '2026-10-23'}).status_code, 401)

    def test_retired_endpoints_cannot_fetch_arbitrary_urls_or_modify_learning(self):
        self.login()
        self.assertEqual(self.client.get('/api/article', params={'url': 'http://127.0.0.1/'}).status_code, 404)
        self.assertEqual(self.client.post('/api/clipping-finalizations', json={'content': 'test'}).status_code, 404)
        self.assertEqual(self.client.post('/api/storage/restore', json={'confirm_replace': True}).status_code, 404)

    def test_home_and_clipping_have_no_learning_controls(self):
        self.login()
        home = self.client.get('/').text
        self.assertNotIn('candidatesBtn', home)
        clipping = self.client.get('/clippings-tab').text
        self.assertNotIn('finalizeLearningBtn', clipping)
        self.assertIn('downloadClippingBtn', clipping)

    def test_home_has_saved_search_workspace_and_local_icons(self):
        self.login()
        home = BeautifulSoup(self.client.get('/').text, 'html.parser')
        for control in ['homeKeywordList', 'homeKeywordInput', 'searchSavedKeywordsBtn', 'homeRecentKeywords',
                        'searchTabsMenuBtn', 'searchTabsFilter', 'batchSearchMessage', 'retryFailedSearchesBtn',
                        'activeTabIndicator', 'batchSearchProgressFill']:
            self.assertIsNotNone(home.find(id=control), control)
        self.assertTrue(home.select('svg use[href="/static/icons.svg?v=motion-1#search"]'))
        self.assertFalse(home.select('.storage-notice'))
        scripts = [tag.get('src', '') for tag in home.select('script[src]')]
        batch_index = next(i for i, src in enumerate(scripts) if '/js/search_batch.js' in src)
        home_index = next(i for i, src in enumerate(scripts) if '/js/home_keywords.js' in src)
        self.assertLess(batch_index, home_index)
        motion_index = next(i for i, src in enumerate(scripts) if '/js/ui_motion.js' in src)
        main_index = next(i for i, src in enumerate(scripts) if '/js/main.js' in src)
        self.assertLess(motion_index, main_index)

    def test_search_toolbar_is_outside_article_grid_without_selection_controls(self):
        self.login()
        item = NewsItem(title='기사', link='https://example.com/new', description='요약')
        with patch('routers.search.fetch_news_page', new=AsyncMock(return_value=NewsPage([item], 1, 1, 1, 20))):
            response = self.client.post('/search-results', data={'keyword': '기사'})
        html = BeautifulSoup(response.text, 'html.parser')
        articles = html.select_one('.news-items')
        self.assertEqual(len(articles.select('.news-card')), 1)
        self.assertFalse(articles.select('.results-toolbar, .search-workbench'))
        self.assertFalse(html.select('.news-select, [data-select-all], [data-clip-selected]'))
        self.assertEqual(len(html.select('.search-period-controls input[type="date"]')), 2)

    def test_search_failure_is_502_not_an_empty_success(self):
        self.login()
        with patch('routers.search.fetch_news_page', new=AsyncMock(side_effect=NewsServiceError('검색 실패'))):
            response = self.client.post('/search-results', data={'keyword': '기사'})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error'], '검색 실패')

    def test_filtered_empty_page_preserves_pagination(self):
        self.login()
        page = NewsPage([], 80, 20, 1, 20)
        with patch('routers.search.fetch_news_page', new=AsyncMock(return_value=page)):
            response = self.client.post('/search-results', data={'keyword': '기사'})
        self.assertIn('data-has-more="true"', response.text)
        self.assertIn('data-next-start="21"', response.text)

    def test_refresh_requests_new_results_instead_of_reusing_cache(self):
        self.login()
        item = NewsItem(title='새 기사', link='https://example.com/new', description='')
        pages = [NewsPage([], 0, 0, 1, 20), NewsPage([item], 1, 1, 1, 20)]
        with patch('routers.search.fetch_news_page', new=AsyncMock(side_effect=pages)) as fetch:
            self.client.post('/search-results', data={'keyword': '기사'})
            response = self.client.post('/search-results', data={'keyword': '기사', 'refresh': 'true'})
        self.assertEqual(fetch.await_count, 2)
        self.assertIn('새 기사', response.text)

    def test_period_collection_reports_truncation_and_renders_controls(self):
        self.login()
        result = CollectionResult([], 1000, 0, 0, False, True)
        with patch('routers.search.collect_articles', new=AsyncMock(return_value=result)):
            response = self.client.post('/api/search/collect', data={'keyword': '기사', 'since': '2026-10-22'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['limit_reached'])
        self.assertFalse(response.json()['complete'])
        self.assertIn('data-date-since', response.json()['html'])
        self.assertNotIn('data-select-all', response.json()['html'])

    def test_invalid_period_is_a_validation_error(self):
        self.login()
        response = self.client.post('/api/search/collect', data={'keyword': '기사', 'since': '2026-10-24', 'until': '2026-10-23'})
        self.assertEqual(response.status_code, 400)

    def test_startup_does_not_contact_backup_provider(self):
        with patch('httpx.AsyncClient.send', new=AsyncMock(side_effect=AssertionError('Unexpected network'))):
            with TestClient(app) as client:
                self.assertEqual(client.get('/healthz').json()['mode'], 'search_clipping')

    def test_external_html_is_escaped_before_highlighting(self):
        result = str(highlight_keyword('<img src=x onerror=alert(1)> 정책', '정책'))
        self.assertNotIn('<img', result)
        self.assertIn('&lt;img', result)
        self.assertIn('<mark>정책</mark>', result)
