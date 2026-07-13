import asyncio
import html
import os
import re
from email.utils import parsedate_to_datetime

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

from app_config import HTTP_RETRY_COUNT, HTTP_TIMEOUT_SECONDS
from app_logging import get_logger
from services.media_source_registry import MEDIA_DOMAIN_MAP, resolve_media_source
from utils.search_filters import filter_news_items


logger = get_logger("news_service")


DOMAIN_MAP = MEDIA_DOMAIN_MAP

ARTICLE_SELECTORS = [
    {"tag": "div", "class": "article_body"},
    {"tag": "div", "class": "newsct_article"},
    {"tag": "div", "class": "go_trans"},
    {"tag": "article", "class": None},
    {"tag": "div", "class": "article"},
    {"tag": "div", "id": "articleBody"},
]


class NewsItem(BaseModel):
    title: str
    link: str
    description: str
    originallink: str = ""
    source: str = ""
    pubDate: str = ""
    domain: str = ""
    formatted_pubdate: str = ""


async def get_naver_api_headers():
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")

    if not client_id or not client_secret:
        logger.warning("Naver API keys are missing")

    return {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}


async def _request_with_retry(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    last_error = None
    for attempt in range(1, HTTP_RETRY_COUNT + 1):
        try:
            response = await client.get(url, **kwargs)
            response.raise_for_status()
            return response
        except Exception as exc:
            last_error = exc
            logger.warning(
                "HTTP request failed",
                extra={"attempt": attempt, "url": url, "error": str(exc)},
            )
            if attempt < HTTP_RETRY_COUNT:
                await asyncio.sleep(0.4 * attempt)

    raise last_error


async def fetch_news(keyword: str, headers: dict, start: int = 1, display: int = 20):
    url = "https://openapi.naver.com/v1/search/news.json"
    params = {"query": keyword, "display": display, "start": start, "sort": "date"}

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await _request_with_retry(client, url, headers=headers, params=params)
            data = response.json()
    except Exception as exc:
        logger.error(
            "Failed to fetch news",
            extra={"keyword": keyword, "start": start, "display": display, "error": str(exc)},
        )
        return []

    items = []
    for item in data.get("items", []):
        raw_title = item.get("title", "")
        raw_desc = item.get("description", "")
        clean_title = html.unescape(re.sub(r"<[^>]*>", "", raw_title))
        clean_desc = html.unescape(re.sub(r"<[^>]*>", "", raw_desc))

        origin = item.get("originallink") or item.get("link") or ""
        resolution = resolve_media_source(origin, item.get("source", ""))
        domain = resolution.domain
        source = resolution.source

        raw_pub = item.get("pubDate", "")
        formatted_pub = raw_pub
        if raw_pub:
            try:
                dt = parsedate_to_datetime(raw_pub)
                formatted_pub = f"{dt.year}년 {dt.month}월 {dt.day}일 {dt.hour}시 {dt.minute}분"
            except Exception:
                logger.info("Failed to parse pubDate", extra={"pubDate": raw_pub})

        items.append(
            NewsItem(
                title=clean_title,
                link=item.get("link", ""),
                description=clean_desc,
                originallink=item.get("originallink", ""),
                source=source,
                pubDate=raw_pub,
                domain=domain,
                formatted_pubdate=formatted_pub,
            )
        )

    return filter_news_items(keyword, items)


async def parse_article(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = await _request_with_retry(client, url)
            html_content = response.text

        soup = BeautifulSoup(html_content, "html.parser")

        for selector in ARTICLE_SELECTORS:
            section = soup.find(selector["tag"], class_=selector["class"]) if selector.get("class") else soup.find(selector["tag"])
            if section:
                text = section.get_text(" ", strip=True)
                if len(text) > 50:
                    return text

        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            return og_desc.get("content", "")

        return soup.get_text(" ", strip=True)[:1000] + "..."
    except Exception as exc:
        logger.error("Article parsing failed", extra={"url": url, "error": str(exc)})
        return "기사 본문을 불러오지 못했습니다."
