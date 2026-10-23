import asyncio
import html
import os
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from app_config import HTTP_RETRY_COUNT, HTTP_TIMEOUT_SECONDS
from app_logging import get_logger
from services.media_source_registry import MEDIA_DOMAIN_MAP, resolve_media_source
from utils.search_filters import filter_news_items

logger = get_logger("news_service")
DOMAIN_MAP = MEDIA_DOMAIN_MAP
NEWS_API_LIMIT = 1000


class NewsServiceError(RuntimeError):
    """A search failure that must not be presented as an empty result."""


class NewsItem(BaseModel):
    title: str
    link: str
    description: str
    originallink: str = ""
    source: str = ""
    pubDate: str = ""
    domain: str = ""
    formatted_pubdate: str = ""


@dataclass
class NewsPage:
    items: list[NewsItem]
    total: int
    raw_count: int
    start: int
    display: int
    oldest_pub_date: str = ""

    @property
    def next_start(self) -> int:
        return self.start + self.raw_count

    @property
    def source_exhausted(self) -> bool:
        return self.raw_count < self.display or self.next_start > self.total

    @property
    def has_more(self) -> bool:
        return not self.source_exhausted and self.next_start <= NEWS_API_LIMIT


async def get_naver_api_headers():
    return {"X-Naver-Client-Id": os.getenv("NAVER_CLIENT_ID", ""),
            "X-Naver-Client-Secret": os.getenv("NAVER_CLIENT_SECRET", "")}


def _safe_news_url(value: str) -> str:
    parsed = urlparse(value or "")
    return value if parsed.scheme in {"https", "http"} and parsed.netloc else ""


async def _request_with_retry(client, url, **kwargs):
    """Retry temporary transport/upstream errors, but not permanent client errors."""
    for attempt in range(max(1, HTTP_RETRY_COUNT)):
        try:
            response = await client.get(url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500 and exc.response.status_code != 429:
                raise
            if attempt + 1 >= max(1, HTTP_RETRY_COUNT):
                raise
        except httpx.RequestError:
            if attempt + 1 >= max(1, HTTP_RETRY_COUNT):
                raise
        await asyncio.sleep(0.4 * (attempt + 1))


async def fetch_news_page(keyword: str, headers: dict, start=1, display=20) -> NewsPage:
    """Fetch one dated page and preserve raw pagination after local filtering."""
    if not headers.get("X-Naver-Client-Id") or not headers.get("X-Naver-Client-Secret"):
        raise NewsServiceError("네이버 검색 API 인증정보가 설정되지 않았습니다.")
    if not 1 <= start <= NEWS_API_LIMIT or not 1 <= display <= 100:
        raise ValueError("검색 조회 범위를 벗어났습니다.")
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await _request_with_retry(
                client, "https://openapi.naver.com/v1/search/news.json", headers=headers,
                params={"query": keyword, "display": display, "start": start, "sort": "date"},
            )
            data = response.json()
            raw_items = data["items"]
            if not isinstance(raw_items, list):
                raise ValueError("Invalid news items")
            total = int(data.get("total", len(raw_items)))
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        logger.warning("News API request failed", extra={"error_type": type(exc).__name__})
        raise NewsServiceError("네이버 뉴스 조회에 실패했습니다. 잠시 후 다시 시도해주세요.") from exc

    items = []
    for raw in raw_items:
        link = _safe_news_url(raw.get("link", ""))
        original = _safe_news_url(raw.get("originallink", ""))
        if not link and not original:
            continue
        resolution = resolve_media_source(original or link, raw.get("source", ""))
        published = raw.get("pubDate", "")
        formatted = published
        try:
            formatted = parsedate_to_datetime(published).strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            pass
        items.append(NewsItem(
            title=html.unescape(re.sub(r"<[^>]*>", "", raw.get("title", ""))),
            description=html.unescape(re.sub(r"<[^>]*>", "", raw.get("description", ""))),
            link=link or original, originallink=original, source=resolution.source,
            domain=resolution.domain, pubDate=published, formatted_pubdate=formatted,
        ))
    return NewsPage(filter_news_items(keyword, items), total, len(raw_items), start, display,
                    raw_items[-1].get("pubDate", "") if raw_items else "")


async def fetch_news(keyword: str, headers: dict, start=1, display=20):
    return (await fetch_news_page(keyword, headers, start, display)).items
