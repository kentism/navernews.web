"""Signed search-result capabilities and opt-in title confirmation jobs."""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

import httpx

from services.article_titles import DEADLINE, ENDING, ProbeFailure, TitleSample, normalized, probe_one, validate_url

TOKEN_TTL = 1800
_FALLBACK_KEY = secrets.token_bytes(32)


def _sign(value):
    secret = os.getenv('NAVER_CLIENT_SECRET', '').encode() or _FALLBACK_KEY
    key = hmac.digest(secret, b'navernews:title-confirmation:v1', 'sha256')
    return hmac.new(key, value.encode('ascii'), hashlib.sha256).hexdigest()


def issue_confirmation(item):
    """Issue a short-lived capability only for a supported, possibly cut title."""
    title = item.title
    if not 8 <= len(title) <= 400 or not ENDING.search(title) or len(normalized(title)) < 12:
        return None
    for value in [item.originallink, item.link]:
        try:
            url = str(validate_url(value))
        except ProbeFailure:
            continue
        if len(url) > 2048:
            continue
        payload = json.dumps({'u': url, 't': title, 'e': int(time.time()) + TOKEN_TTL},
                             ensure_ascii=False, separators=(',', ':')).encode()
        encoded = base64.urlsafe_b64encode(payload).decode().rstrip('=')
        return {'token': encoded + '.' + _sign(encoded),
                'key': hashlib.sha256((url + '\n' + title).encode()).hexdigest()}
    return None


def verify_confirmation(token):
    """Authenticate server-issued claims; never trust a client-provided URL."""
    try:
        if len(token) > 8192:
            raise ValueError
        encoded, signature = token.split('.')
        if not hmac.compare_digest(_sign(encoded), signature):
            raise ValueError
        claims = json.loads(base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True))
        if not isinstance(claims, dict) or set(claims) != {'u', 't', 'e'}:
            raise ValueError
        now = int(time.time())
        if type(claims['e']) is not int or not now < claims['e'] <= now + TOKEN_TTL + 5:
            raise ValueError
        if not isinstance(claims['t'], str) or not 8 <= len(claims['t']) <= 400 or not ENDING.search(claims['t']):
            raise ValueError
        if not isinstance(claims['u'], str) or len(claims['u']) > 2048:
            raise ValueError
        return TitleSample(str(validate_url(claims['u'])), claims['t'])
    except (ValueError, TypeError, KeyError, UnicodeError, ProbeFailure) as exc:
        raise ValueError('제목 확인 요청이 만료되었거나 유효하지 않습니다. 검색 결과를 새로고침해주세요.') from exc


class TitleConfirmationService:
    """Share matching in-flight work and fail fast above two jobs per worker."""

    def __init__(self):
        self.jobs = {}

    async def _fetch(self, sample):
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=0)
        async with httpx.AsyncClient(timeout=DEADLINE, limits=limits, trust_env=False) as client:
            return await probe_one(sample, client)

    async def confirm(self, sample):
        key = (sample.url, sample.api_title)
        task = self.jobs.get(key)
        if task is None:
            if len(self.jobs) >= 2:
                return {'status': 'busy', 'message': '다른 제목을 확인 중입니다. 잠시 후 다시 시도해주세요.'}
            task = asyncio.create_task(self._fetch(sample))
            self.jobs[key] = task
            def cleanup(completed):
                if self.jobs.get(key) is completed:
                    self.jobs.pop(key, None)
                if not completed.cancelled():
                    completed.exception()
            task.add_done_callback(cleanup)
        result = await asyncio.shield(task)
        if result.status in {'extended', 'punctuation_only'}:
            source_url = str(validate_url(result.final_url))
            source = 'naver' if validate_url(source_url).host in {'news.naver.com', 'n.news.naver.com'} else 'original'
            return {'status': 'confirmed', 'title': result.candidate_title,
                    'source': source, 'source_url': source_url}
        if result.status in {'matched', 'source_also_short', 'no_title'}:
            return {'status': 'no_change', 'message': '추가 제목 없음'}
        if result.status in {'unverified', 'conflict'}:
            return {'status': 'unverified', 'message': '일치 확인 불가'}
        return {'status': 'failed', 'message': '제목을 확인하지 못했습니다. 잠시 후 다시 시도해주세요.'}

    async def close(self):
        tasks = list(self.jobs.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.jobs.clear()
