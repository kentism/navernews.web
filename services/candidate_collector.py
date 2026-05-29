from datetime import datetime
from typing import Optional

from app_logging import get_logger
from services.clipping_store import create_candidate, parse_pub_date
from services.news_service import fetch_news


logger = get_logger("services.candidate_collector")


async def collect_candidates(
    *,
    keywords: list[str],
    headers: dict,
    cutoff: datetime,
    until: Optional[datetime] = None,
    max_pages: int = 5,
    display: int = 100,
) -> dict:
    """Collect candidate articles with the same scoring path used by the learning tab."""
    cleaned_keywords = []
    seen_keywords = set()
    for keyword in keywords:
        cleaned = str(keyword or "").strip()
        if cleaned and cleaned not in seen_keywords:
            cleaned_keywords.append(cleaned)
            seen_keywords.add(cleaned)

    collected = {}
    total_checked = 0
    created_count = 0
    skipped_low_score = 0
    skipped_finalized = 0
    skipped_duplicate = 0
    skipped_out_of_window = 0

    for keyword in cleaned_keywords:
        start = 1
        for _ in range(max_pages):
            items = await fetch_news(keyword, headers=headers, start=start, display=display)
            if not items:
                break

            total_checked += len(items)
            reached_cutoff = False
            for item in items:
                pub_dt = parse_pub_date(item.pubDate)
                if until and pub_dt and pub_dt > until:
                    skipped_out_of_window += 1
                    continue
                if pub_dt and pub_dt < cutoff:
                    reached_cutoff = True
                    continue

                result = await create_candidate(item, keyword)
                status = result.get("status")
                if result.get("created"):
                    created_count += 1
                elif status == "low_score":
                    skipped_low_score += 1
                elif status == "finalized":
                    skipped_finalized += 1
                elif status == "duplicate":
                    skipped_duplicate += 1

                candidate = result.get("candidate")
                if candidate and candidate.get("status") == "pending":
                    collected[int(candidate["id"])] = candidate

            if reached_cutoff:
                break

            start += display

    return {
        "keywords": cleaned_keywords,
        "checked": total_checked,
        "created": created_count,
        "skipped_low_score": skipped_low_score,
        "skipped_finalized": skipped_finalized,
        "skipped_duplicate": skipped_duplicate,
        "skipped_out_of_window": skipped_out_of_window,
        "candidates": list(collected.values()),
    }
