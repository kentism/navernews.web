from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from services.news_service import NEWS_API_LIMIT, NewsItem, fetch_news_page
from utils.article_urls import normalize_article_url

KST = ZoneInfo("Asia/Seoul")


def parse_date_range(since: str, until: str = "") -> tuple[datetime, datetime]:
    """Interpret both dates in Korea; the supplied end date is inclusive."""
    try:
        first = date.fromisoformat(since)
        last = date.fromisoformat(until) if until else datetime.now(KST).date()
        if first > last:
            raise ValueError
        return (datetime.combine(first, time.min, KST),
                datetime.combine(last + timedelta(days=1), time.min, KST))
    except (ValueError, OverflowError) as exc:
        raise ValueError("시작일과 종료일을 올바르게 입력해주세요.") from exc


@dataclass
class CollectionResult:
    items: list[NewsItem]
    checked_count: int
    duplicate_count: int
    invalid_date_count: int
    complete: bool
    limit_reached: bool


async def collect_articles(keyword, headers, since, until="", *, page_size=100,
                           max_results=NEWS_API_LIMIT) -> CollectionResult:
    """Collect every retrievable article in a date range without relevance scoring."""
    first, end = parse_date_range(since, until)
    items, seen = [], set()
    checked = duplicates = invalid = 0
    complete = False
    start = 1
    while start <= max_results:
        display = min(page_size, max_results - start + 1)
        page = await fetch_news_page(keyword, headers, start=start, display=display)
        checked += page.raw_count
        for item in page.items:
            try:
                published = parsedate_to_datetime(item.pubDate)
                if published.tzinfo is None:
                    raise ValueError
            except (ValueError, TypeError):
                invalid += 1
                continue
            if not first <= published < end:
                continue
            key = normalize_article_url(item.originallink or item.link)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            items.append(item)
        try:
            oldest = parsedate_to_datetime(page.oldest_pub_date)
            reached_start = oldest.tzinfo is not None and oldest < first
        except (ValueError, TypeError):
            reached_start = False
        if page.source_exhausted or reached_start:
            complete = True
            break
        if page.raw_count == 0:
            break
        start = page.next_start
    return CollectionResult(items, checked, duplicates, invalid, complete, not complete)
