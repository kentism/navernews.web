import asyncio
import html
import os
import re
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

from app_config import HTTP_RETRY_COUNT, HTTP_TIMEOUT_SECONDS
from app_logging import get_logger
from utils.search_filters import filter_news_items


logger = get_logger("news_service")


DOMAIN_MAP = {
    "joongang.joins.com": "중앙일보", "hani.co.kr": "한겨레", "yna.co.kr": "연합뉴스",
    "chosun.com": "조선일보", "donga.com": "동아일보", "mediatoday.co.kr": "미디어오늘",
    "journalist.or.kr": "기자협회보", "hankookilbo.com": "한국일보", "mbn.mk.co.kr": "MBN",
    "newscj.com": "천지일보", "news.jtbc.co.kr": "JTBC", "mediaus.co.kr": "미디어스",
    "dailian.co.kr": "데일리안", "view.asiae.co.kr": "아시아경제", "newspim.com": "뉴스핌",
    "news1.kr": "뉴스1", "asiatoday.co.kr": "아시아경제", "news.tvchosun.com": "TV조선",
    "digitaltoday.co.kr": "디지털투데이", "biz.chosun.com": "조선비즈", "newsis.com": "뉴시스",
    "biz.heraldcorp.com": "헤럴드경제", "etoday.co.kr": "이투데이", "ichannela.com": "채널A",
    "news.kbs.co.kr": "KBS", "kukinews.com": "쿠키뉴스", "yonhapnewstv.co.kr": "연합뉴스TV",
    "segye.com": "세계일보", "munhwa.com": "문화일보", "joongang.co.kr": "중앙일보",
    "ytn.co.kr": "YTN", "seoul.co.kr": "서울신문", "sedaily.com": "서울경제",
    "fnnews.com": "파이낸셜뉴스", "news.tf.co.kr": "더팩트", "news.sbs.co.kr": "SBS",
    "etnews.com": "전자신문", "sisajournal-e.com": "시사저널e", "zdnet.co.kr": "지디넷코리아",
    "mk.co.kr": "매일경제", "biz.sbs.co.kr": "SBSBiz", "weekly.chosun.com": "주간조선",
    "kmib.co.kr": "국민일보", "mt.co.kr": "머니투데이", "khan.co.kr": "경향신문", "inews24.com": "아이뉴스24",
    "it.chosun.com": "IT조선", "edaily.co.kr": "이데일리", "newstapa.org": "뉴스타파", "busan.com": "부산일보",
    "hankyung.com": "한국경제", "dt.co.kr": "디지털타임스", "pdjournal.com": "PD저널", "sisajournal.com": "시사저널",
    "nownews.seoul.co.kr": "서울신문", "kado.net": "강원도민일보", "imaeil.com": "매일신문", "sports.khan.co.kr": "스포츠경향",
    "pressian.com": "프레시안", "imnews.imbc.com": "MBC", "nocutnews.co.kr": "노컷뉴스", "ddaily.co.kr": "디지털데일리",
    "news.naver.com": "네이버", "news.daum.net": "다음", "sports.chosun.com": "스포츠조선",
    "sports.seoul.co.kr": "스포츠서울", "sports.donga.com": "스포츠동아", "sports.kbs.co.kr": "KBS",
    "sports.sbs.co.kr": "SBS 스포츠", "sports.mk.co.kr": "매일경제 스포츠", "news.kmib.co.kr": "국민일보",
    "news.heraldcorp.com": "헤럴드경제", "news.khan.co.kr": "경향신문", "news.hankyung.com": "한국경제",
    "news.imaeil.com": "매일신문", "news.busan.com": "부산일보", "news.joins.com": "중앙일보",
    "news.mt.co.kr": "머니투데이", "news.edaily.co.kr": "이데일리", "news.unn.net": "한국대학신문",
    "news.kukinews.com": "쿠키뉴스", "news.ajunews.com": "아주경제", "news.wowtv.co.kr": "한국경제TV",
    "news.g-enews.com": "글로벌이코노믹", "news.mtn.co.kr": "머니투데이방송", "news.ebs.co.kr": "EBS",
    "news.mbc.co.kr": "MBC", "newstomato.com": "뉴스토마토", "naeil.com": "내일신문", "insight.co.kr": "인사이트",
    "radio.ytn.co.kr": "YTN", "thebell.co.kr": "더벨", "wowtv.co.kr": "한국경제TV", "daejoilbo.com": "대전일보",
    "kyeongin.com": "경인일보", "kyeonggi.com": "경기일보", "kyeongbuk.co.kr": "경북일보", "kyongnam.com": "경남신문",
    "jnilbo.com": "전북일보", "jnnews.co.kr": "전남일보", "newdaily.co.kr": "뉴데일리", "ohmynews.com": "오마이뉴스",
    "bloter.net": "블로터", "moneys.co.kr": "머니S", "daily.hankooki.com": "데일리한국", "mbn.co.kr": "MBN",
    "jibs.co.kr": "JIBS", "topstarnews.net": "톱스타뉴스", "kookje.co.kr": "국제신문",
}

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
        source = item.get("source", "")
        netloc = urlparse(origin).netloc or ""
        domain = netloc.replace("www.", "")

        if not source:
            source = DOMAIN_MAP.get(domain, domain)

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
