import asyncio
import gzip
import unittest
from unittest.mock import patch

import httpx

from prototypes.article_title_probe import (
    MAX_BYTES, ProbeFailure, Sample, compare_title, extract_candidates,
    probe_one, public_ip, run_samples, validate_url,
)
from services.article_titles import TitleResult, apply_candidates


TITLE = '방송 정책 개선을 위한 새로운 제도와 향후 추진 계획 발표'
SHORT = '방송 정책 개선을 위한 새로운 제도와 향후...'
URL = 'https://news.kbs.co.kr/news/pc/view/view.do?ncd=123'


class TitleExtractionTests(unittest.TestCase):
    def test_extracts_article_json_ld_and_open_graph_without_running_scripts(self):
        markup = f'''<script type="application/ld+json">{{"@graph":[
            {{"@type":"NewsArticle","headline":"{TITLE}"}}]}}</script>
            <meta property="og:title" content="{TITLE}">'''
        self.assertEqual(extract_candidates(markup.encode()), [('json_ld', TITLE), ('og_title', TITLE)])

    def test_ignores_invalid_json_and_unrelated_structured_data(self):
        markup = f'''<script type="application/ld+json">invalid</script>
            <script type="application/ld+json">{{"@type":"WebSite","headline":"wrong"}}</script>
            <h1>{TITLE}</h1>'''
        self.assertEqual(extract_candidates(markup.encode()), [('heading', TITLE)])

    def test_title_tag_only_strips_an_exact_site_name_suffix(self):
        markup = f'<meta property="og:site_name" content="KBS"><title>{TITLE} | KBS</title>'
        self.assertEqual(extract_candidates(markup.encode()), [('title_tag', TITLE)])

    def test_decodes_legacy_encoding(self):
        markup = f'<meta charset="euc-kr"><meta property="og:title" content="{TITLE}">'
        self.assertEqual(extract_candidates(markup.encode('euc-kr'))[0][1], TITLE)

    def test_only_a_matching_truncated_prefix_can_be_extended(self):
        self.assertEqual(compare_title(SHORT, TITLE), 'extended')
        self.assertEqual(compare_title(TITLE, TITLE), 'matched')
        self.assertEqual(compare_title(SHORT, '관계없는 기사 제목에 대한 보도 내용'), 'unverified')
        self.assertEqual(compare_title('방송...', TITLE), 'unverified')

    def test_a_cut_title_does_not_require_a_trailing_ellipsis(self):
        self.assertEqual(compare_title(SHORT.removesuffix('...'), TITLE), 'extended')

    def test_exact_heading_wins_over_an_extended_seo_title_without_ellipsis(self):
        result = TitleResult(URL, TITLE, 'test')
        markup = f'<meta property="og:title" content="{TITLE} | KBS"><h1>{TITLE}</h1>'
        apply_candidates(result, markup.encode())
        self.assertEqual(result.status, 'matched')
        self.assertEqual(result.candidate_title, TITLE)

    def test_browser_title_suffix_is_not_an_extension_when_metadata_matches(self):
        result = TitleResult(URL, TITLE, 'test')
        markup = f'<meta property="og:title" content="{TITLE}"><title>{TITLE} - KBS</title>'
        apply_candidates(result, markup.encode())
        self.assertEqual(result.status, 'matched')

    def test_ellipsis_is_not_itself_evidence_of_truncation(self):
        title = '방송 정책 바뀐다…시민 의견 반영'
        self.assertEqual(compare_title(title, title), 'matched')
        self.assertEqual(compare_title(SHORT, SHORT), 'source_also_short')
        self.assertEqual(compare_title('국정감사까지 번진 공영방송 신뢰 논란...', '국정감사까지 번진 공영방송 신뢰 논란"'), 'punctuation_only')

    def test_can_recover_just_one_or_two_missing_characters(self):
        title = '인권위 이전 재검토 요청에 세계인권기구연합도 '
        self.assertEqual(compare_title(title + '...', title + '서한'), 'extended')
        self.assertEqual(compare_title(title + '...', title + '글'), 'extended')

    def test_url_policy_rejects_unknown_hosts_credentials_and_private_addresses(self):
        self.assertEqual(validate_url(URL).host, 'news.kbs.co.kr')
        for value in ['http://news.kbs.co.kr/a', 'https://evil.test/a',
                      'https://news.kbs.co.kr.evil.test/a', 'https://user@news.kbs.co.kr/a',
                      'https://news.kbs.co.kr:8443/a', 'https://127.0.0.1/a']:
            with self.subTest(value=value), self.assertRaises(ProbeFailure):
                validate_url(value)
        for address in ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '::ffff:127.0.0.1']:
            with self.subTest(address=address), self.assertRaises(ProbeFailure):
                public_ip([address])
        self.assertEqual(public_ip(['93.184.216.34']), '93.184.216.34')


class TitleFetchTests(unittest.IsolatedAsyncioTestCase):
    async def resolve(self, hostname):
        return '93.184.216.34'

    async def run_probe(self, handler, *, timeout=3):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await probe_one(Sample(URL, SHORT), client, resolver=self.resolve, timeout=timeout)

    async def test_pins_connection_and_keeps_original_host_for_tls_and_http(self):
        async def handler(request):
            self.assertEqual(request.url.host, '93.184.216.34')
            self.assertEqual(request.headers['host'], 'news.kbs.co.kr')
            self.assertEqual(request.extensions['sni_hostname'], 'news.kbs.co.kr')
            self.assertEqual(request.headers['connection'], 'close')
            return httpx.Response(200, headers={'content-type': 'text/html'},
                                  text=f'<head><meta property="og:title" content="{TITLE}"></head>')
        result = await self.run_probe(handler)
        self.assertEqual(result.status, 'extended')
        self.assertEqual(result.candidate_title, TITLE)
        self.assertEqual(result.api_title, SHORT)
        self.assertEqual(result.requests, 1)

    async def test_rejects_a_redirect_to_an_unapproved_destination(self):
        result = await self.run_probe(lambda _: httpx.Response(302, headers={'location': 'https://127.0.0.1/'}))
        self.assertEqual(result.status, 'blocked_url')
        self.assertEqual(result.requests, 1)

    async def test_revalidates_and_follows_a_relative_redirect(self):
        paths = []
        def handler(request):
            paths.append(request.url.path)
            if len(paths) == 1:
                return httpx.Response(302, headers={'location': '/article/123'})
            return httpx.Response(200, headers={'content-type': 'text/html'},
                                  text=f'<meta property="og:title" content="{TITLE}">')
        result = await self.run_probe(handler)
        self.assertEqual(result.status, 'extended')
        self.assertEqual(result.requests, 2)
        self.assertEqual(result.final_url, 'https://news.kbs.co.kr/article/123')

    async def test_redirect_loop_is_bounded(self):
        result = await self.run_probe(lambda _: httpx.Response(302, headers={'location': '/again'}))
        self.assertEqual(result.status, 'redirect_limit')
        self.assertEqual(result.requests, 3)

    async def test_private_dns_never_reaches_transport(self):
        async def resolver(hostname):
            return '127.0.0.1'
        def handler(request):
            self.fail('An internal address must not be fetched')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await probe_one(Sample(URL, SHORT), client, resolver=resolver)
        self.assertEqual(result.status, 'blocked_dns')
        self.assertEqual(result.requests, 0)

    async def test_timeout_does_not_return_a_replacement_title(self):
        async def handler(request):
            await asyncio.sleep(.1)
            return httpx.Response(200)
        result = await self.run_probe(handler, timeout=.01)
        self.assertEqual(result.status, 'timeout')
        self.assertEqual(result.api_title, SHORT)
        self.assertEqual(result.candidate_title, '')

    async def test_blocks_large_or_non_html_responses_and_reports_http_errors(self):
        cases = [
            (httpx.Response(200, headers={'content-type': 'text/html'}, content=b'x' * (MAX_BYTES + 1)), 'too_large'),
            (httpx.Response(200, headers={'content-type': 'application/pdf'}, content=b'PDF'), 'not_html'),
            (httpx.Response(403), 'http_403'),
        ]
        for response, expected in cases:
            with self.subTest(expected=expected):
                result = await self.run_probe(lambda _, response=response: response)
                self.assertEqual(result.status, expected)

    async def test_reports_conflicting_full_titles_without_accepting_one(self):
        markup = f'<meta property="og:title" content="{TITLE}"><h1>{TITLE} (수정)</h1>'
        result = await self.run_probe(lambda _: httpx.Response(200, headers={'content-type': 'text/html'}, text=markup))
        self.assertEqual(result.status, 'conflict')
        self.assertEqual(result.candidate_title, '')

    async def test_compressed_html_is_bounded_after_decoding(self):
        for content, expected in [(f'<meta property="og:title" content="{TITLE}">'.encode(), 'extended'),
                                  (b'x' * (MAX_BYTES + 1), 'too_large')]:
            compressed = gzip.compress(content)
            result = await self.run_probe(lambda _: httpx.Response(200,
                headers={'content-type': 'text/html', 'content-encoding': 'gzip'}, stream=httpx.ByteStream(compressed)))
            self.assertEqual(result.status, expected)

    async def test_limits_total_samples_and_concurrent_jobs_without_network(self):
        active = peak = calls = 0
        async def fake_probe(*args, **kwargs):
            nonlocal active, peak, calls
            active += 1
            calls += 1
            peak = max(peak, active)
            await asyncio.sleep(.01)
            active -= 1
            return 'mocked'
        with patch('prototypes.article_title_probe.probe_one', new=fake_probe):
            results = await run_samples([Sample(URL, SHORT)] * 9)
        self.assertEqual(len(results), 6)
        self.assertEqual(calls, 6)
        self.assertEqual(peak, 2)
