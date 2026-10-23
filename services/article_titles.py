"""Conservative title comparison and bounded, IP-pinned article retrieval."""

import asyncio
import html
import ipaddress
import json
import re
import socket
import time
import unicodedata
import zlib
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup


MAX_BYTES = 512 * 1024
DEADLINE = 3
ALLOWED_HOSTS = frozenset({
    'n.news.naver.com', 'news.naver.com', 'news.kbs.co.kr', 'news.jtbc.co.kr',
    'news.sbs.co.kr', 'imnews.imbc.com', 'www.yna.co.kr', 'www.yonhapnewstv.co.kr',
    'www.ytn.co.kr', 'www.newsis.com', 'www.news1.kr', 'www.khan.co.kr',
    'www.hani.co.kr', 'www.donga.com', 'www.chosun.com', 'www.hankookilbo.com',
})
ARTICLE_TYPES = {'Article', 'NewsArticle', 'ReportageNewsArticle', 'AnalysisNewsArticle'}
ENDING = re.compile(r'(?:\.{2,}|…+)\s*$')


class ProbeFailure(Exception):
    """A bounded failure reported as data, not an application error."""


@dataclass(frozen=True)
class TitleSample:
    url: str
    api_title: str
    kind: str = 'api'


@dataclass
class TitleResult:
    url: str
    api_title: str
    kind: str
    status: str = 'no_title'
    candidate_title: str = ''
    evidence: str = ''
    final_url: str = ''
    elapsed_ms: float = 0
    decoded_bytes: int = 0
    requests: int = 0


def normalized(value):
    return re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', html.unescape(value))).casefold()


def compare_title(api_title, candidate):
    """Only accept exact matches or long, matching truncated prefixes."""
    original, proposed = normalized(api_title), normalized(candidate)
    if original == proposed:
        if ENDING.search(api_title):
            if len(original) < 12:
                return 'unverified'
            return 'source_also_short' if ENDING.search(candidate) else 'punctuation_only'
        return 'matched'
    if ENDING.search(api_title):
        prefix = normalized(ENDING.sub('', api_title))
        if len(prefix) >= 12 and proposed.startswith(prefix) and len(proposed) > len(prefix):
            return 'source_also_short' if ENDING.search(candidate) else 'extended'
    return 'unverified'


def extract_candidates(content):
    """Read inert metadata/headings; never execute scripts or infer missing words."""
    soup = BeautifulSoup(content, 'html.parser')
    candidates = []

    def add(source, value):
        if not isinstance(value, str):
            return
        value = ' '.join(html.unescape(value).split())
        if 8 <= len(value) <= 400 and '\ufffd' not in value and (source, value) not in candidates:
            candidates.append((source, value))

    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            stack = [json.loads(tag.get_text())]
        except (ValueError, RecursionError):
            continue
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                types = node.get('@type', [])
                types = [types] if isinstance(types, str) else types
                if isinstance(types, list) and any(isinstance(t, str) and t.rsplit('/', 1)[-1] in ARTICLE_TYPES for t in types):
                    add('json_ld', node.get('headline'))
                stack.extend(value for value in node.values() if isinstance(value, (dict, list)))
    for source, selector in [('og_title', 'meta[property="og:title"]'),
                             ('twitter_title', 'meta[name="twitter:title"]'),
                             ('headline', 'meta[itemprop="headline"]')]:
        for tag in soup.select(selector):
            add(source, tag.get('content'))
    for tag in soup.select('h1, h2#title_area, .media_end_head_headline'):
        add('heading', tag.get_text(' ', strip=True))
    if soup.title:
        title = soup.title.get_text(' ', strip=True)
        site = soup.select_one('meta[property="og:site_name"]')
        site_name = site.get('content', '') if site else ''
        for separator in [' | ', ' - ', ' : ']:
            suffix = separator + site_name
            if site_name and title.endswith(suffix):
                title = title[:-len(suffix)]
                break
        add('title_tag', title)
    return candidates


def validate_url(value):
    """Allow only explicit HTTPS destinations; credentials and custom ports fail."""
    try:
        url = httpx.URL(value)
        if (url.scheme != 'https' or url.host not in ALLOWED_HOSTS or url.port not in (None, 443)
                or url.username or url.password):
            raise ValueError
        return url.copy_with(fragment=None)
    except (httpx.InvalidURL, ValueError) as exc:
        raise ProbeFailure('blocked_url') from exc


def public_ip(addresses):
    """Reject mixed public/private DNS and choose a validated connection address."""
    parsed = [ipaddress.ip_address(address) for address in dict.fromkeys(addresses)]
    if not parsed or any(not address.is_global or address.is_multicast for address in parsed):
        raise ProbeFailure('blocked_dns')
    parsed.sort(key=lambda address: address.version)
    return str(parsed[0])


async def resolve_public_ip(hostname):
    rows = await asyncio.get_running_loop().getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    return public_ip([row[4][0] for row in rows])


def apply_candidates(result, content):
    candidates = extract_candidates(content)
    extensions = [(source, title) for source, title in candidates if compare_title(result.api_title, title) == 'extended']
    if len({normalized(title) for _, title in extensions}) > 1:
        result.status = 'conflict'
        return
    for status in ['extended', 'matched', 'punctuation_only', 'source_also_short', 'unverified']:
        for source, title in candidates:
            if compare_title(result.api_title, title) == status:
                result.status, result.candidate_title, result.evidence = status, title, source
                return


async def read_html(response, result):
    """Bound both wire input and decoded output, including compressed responses."""
    if response.is_stream_consumed:
        content = response.content
        result.decoded_bytes = len(content)
        if len(content) > MAX_BYTES:
            raise ProbeFailure('too_large')
        return content
    encoding = response.headers.get('content-encoding', '').strip().lower()
    if encoding not in {'', 'identity', 'gzip', 'deflate'}:
        raise ProbeFailure('unsupported_encoding')
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS if encoding == 'gzip' else zlib.MAX_WBITS) if encoding in {'gzip', 'deflate'} else None
    content = bytearray()
    wire_bytes = 0
    try:
        async for chunk in response.aiter_raw(chunk_size=16384):
            wire_bytes += len(chunk)
            if wire_bytes > MAX_BYTES:
                raise ProbeFailure('too_large')
            decoded = decoder.decompress(chunk, MAX_BYTES - result.decoded_bytes + 1) if decoder else chunk
            result.decoded_bytes += len(decoded)
            if result.decoded_bytes > MAX_BYTES:
                raise ProbeFailure('too_large')
            content.extend(decoded)
        if decoder and (not decoder.eof or decoder.unused_data):
            raise ProbeFailure('invalid_encoding')
    except zlib.error as exc:
        raise ProbeFailure('invalid_encoding') from exc
    return bytes(content)


async def probe_one(sample, client, *, resolver=resolve_public_ip, timeout=DEADLINE):
    """Fetch at most three hops within one deadline, pinned to validated IPs."""
    result = TitleResult(sample.url, sample.api_title, sample.kind)
    started = time.perf_counter()
    try:
        async with asyncio.timeout(timeout):
            current = validate_url(sample.url)
            for hop in range(3):
                result.final_url = str(current)
                address = public_ip([await resolver(current.host)])
                target = current.copy_with(host=address)
                # Connection: close prevents cross-host reuse when two domains share an IP.
                headers = {'Host': current.host, 'Connection': 'close', 'Accept': 'text/html',
                           'Accept-Encoding': 'identity', 'User-Agent': 'NewsClippingTitleCheck/1.0'}
                result.requests += 1
                async with client.stream('GET', target, headers=headers,
                                         extensions={'sni_hostname': current.host}, follow_redirects=False) as response:
                    if response.is_redirect:
                        if hop == 2:
                            raise ProbeFailure('redirect_limit')
                        current = validate_url(str(current.join(response.headers.get('location', ''))))
                        continue
                    if response.status_code != 200:
                        raise ProbeFailure(f'http_{response.status_code}')
                    if response.headers.get('content-type', '').split(';', 1)[0].lower() not in {'text/html', 'application/xhtml+xml'}:
                        raise ProbeFailure('not_html')
                    content = await read_html(response, result)
                    apply_candidates(result, content)
                    break
    except ProbeFailure as exc:
        result.status = str(exc)
    except (TimeoutError, httpx.TimeoutException):
        result.status = 'timeout'
    except (httpx.HTTPError, OSError):
        result.status = 'network_error'
    finally:
        result.elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return result
