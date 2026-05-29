import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from app_config import DASHBOARD_EXTRA_KEYWORDS, DASHBOARD_MAIN_KEYWORDS
from services.clipping_store import DEFAULT_CATEGORIES, parse_pub_date


KST = timezone(timedelta(hours=9), "Asia/Seoul")


def get_dashboard_keywords(extra_keywords: Optional[list[str]] = None) -> list[str]:
    keywords = []
    seen = set()
    for keyword in [*DASHBOARD_MAIN_KEYWORDS, *DASHBOARD_EXTRA_KEYWORDS, *(extra_keywords or [])]:
        cleaned = str(keyword or "").strip()
        if cleaned and cleaned not in seen:
            keywords.append(cleaned)
            seen.add(cleaned)
    return keywords


def get_dashboard_window(now: Optional[datetime] = None) -> dict:
    current = now or datetime.now(KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    current_kst = current.astimezone(KST)
    start_kst = (current_kst - timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    return {
        "start": start_kst.astimezone(timezone.utc),
        "end": current_kst.astimezone(timezone.utc),
        "start_kst": start_kst.isoformat(),
        "end_kst": current_kst.isoformat(),
    }


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _canonical_link(candidate: dict) -> str:
    return str(candidate.get("original_link") or candidate.get("link") or "").strip()


def _tokenize(text: str) -> set[str]:
    cleaned = re.sub(r"[^\w가-힣]+", " ", str(text or "").lower())
    return {token for token in cleaned.split() if len(token) >= 2}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _candidate_tokens(candidate: dict) -> set[str]:
    return _tokenize(f"{candidate.get('title', '')} {candidate.get('description', '')}")


def _is_related(candidate: dict, group: dict) -> bool:
    representative = group["representative"]
    if _canonical_link(candidate) and _canonical_link(candidate) == _canonical_link(representative):
        return True
    if candidate.get("similar_group_key") and candidate.get("similar_group_key") == representative.get("similar_group_key"):
        return True
    return _jaccard(_candidate_tokens(candidate), group["tokens"]) >= 0.42


def _candidate_sort_key(candidate: dict) -> tuple:
    pub_dt = parse_pub_date(candidate.get("pub_date", ""))
    timestamp = pub_dt.timestamp() if pub_dt else 0
    return (int(candidate.get("score") or 0), timestamp, int(candidate.get("id") or 0))


def _compact_candidate(candidate: dict) -> dict:
    return {
        "id": candidate.get("id"),
        "article_id": candidate.get("article_id"),
        "keyword": candidate.get("keyword") or "",
        "score": int(candidate.get("score") or 0),
        "score_reasons": candidate.get("score_reasons") or [],
        "suggested_category": candidate.get("suggested_category") or "기타",
        "status": candidate.get("status") or "pending",
        "title": _clean_text(candidate.get("title") or ""),
        "description": _clean_text(candidate.get("description") or ""),
        "source": candidate.get("source") or candidate.get("domain") or "출처 미상",
        "domain": candidate.get("domain") or "",
        "link": candidate.get("link") or "",
        "original_link": candidate.get("original_link") or candidate.get("link") or "",
        "pub_date": candidate.get("pub_date") or "",
    }


def group_dashboard_candidates(candidates: list[dict]) -> list[dict]:
    groups = []
    sorted_candidates = sorted(candidates, key=_candidate_sort_key, reverse=True)

    for candidate in sorted_candidates:
        if candidate.get("status") != "pending":
            continue

        target_group = None
        for group in groups:
            if _is_related(candidate, group):
                target_group = group
                break

        if not target_group:
            groups.append(
                {
                    "representative": candidate,
                    "related": [],
                    "tokens": _candidate_tokens(candidate),
                }
            )
            continue

        if _candidate_sort_key(candidate) > _candidate_sort_key(target_group["representative"]):
            target_group["related"].append(target_group["representative"])
            target_group["representative"] = candidate
            target_group["tokens"] = _candidate_tokens(candidate)
        else:
            target_group["related"].append(candidate)

    return groups


def _section_for_category(sections: list[dict], category: str) -> dict:
    for section in sections:
        if section["category"] == category:
            return section
    return sections[-1]


def _format_entry_date(pub_date: str) -> str:
    dt = parse_pub_date(pub_date)
    if not dt:
        return ""
    kst = dt.astimezone(KST)
    return f" ({kst.month:02d}.{kst.day:02d}.)"


def render_dashboard_final_content(sections: list[dict]) -> str:
    lines = []
    for section in sections:
        lines.append(f"■ {section['category']}")
        lines.append("")
        for item in section.get("items", []):
            article = item["article"]
            source = article.get("source") or "출처 미상"
            title = article.get("title") or "제목 없음"
            link = article.get("original_link") or article.get("link") or ""
            lines.append(f"▷ {source} : {title}{_format_entry_date(article.get('pub_date', ''))}")
            if link:
                lines.append(f"<{link}>")
            lines.append("")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_dashboard_payload(
    *,
    candidates: list[dict],
    keywords: list[str],
    window: dict,
    collection: dict,
) -> dict:
    sections = [{"category": category, "items": []} for category in DEFAULT_CATEGORIES]
    groups = group_dashboard_candidates(candidates)

    for index, group in enumerate(groups, start=1):
        representative = _compact_candidate(group["representative"])
        related = sorted(group["related"], key=_candidate_sort_key, reverse=True)
        dashboard_item = {
            "group_id": f"issue-{index}",
            "category": representative.get("suggested_category") or "기타",
            "article": representative,
            "related_articles": [_compact_candidate(item) for item in related],
            "related_count": len(related),
        }
        _section_for_category(sections, dashboard_item["category"])["items"].append(dashboard_item)

    for section in sections:
        section["items"].sort(key=lambda item: _candidate_sort_key(item["article"]), reverse=True)

    related_count = sum(item["related_count"] for section in sections for item in section["items"])
    issue_count = sum(len(section["items"]) for section in sections)

    return {
        "keywords": keywords,
        "window_start": window["start"].isoformat(),
        "window_end": window["end"].isoformat(),
        "window_start_kst": window["start_kst"],
        "window_end_kst": window["end_kst"],
        "checked": collection.get("checked", 0),
        "created": collection.get("created", 0),
        "skipped_low_score": collection.get("skipped_low_score", 0),
        "skipped_finalized": collection.get("skipped_finalized", 0),
        "skipped_duplicate": collection.get("skipped_duplicate", 0),
        "issue_count": issue_count,
        "related_count": related_count,
        "sections": sections,
        "final_content": render_dashboard_final_content(sections),
    }
