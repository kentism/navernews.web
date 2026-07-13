from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import re
from typing import Iterable, Optional


CLUSTER_MAX_HOURS = 48
CLUSTER_SIMILARITY_THRESHOLD = 0.20
CLUSTER_STRONG_SIMILARITY_THRESHOLD = 0.35

GENERIC_NEWS_TERMS = {
    "관련",
    "단독",
    "속보",
    "종합",
    "영상",
    "포토",
    "첫",
    "실시",
    "개최",
    "강화",
    "대응",
    "한다",
    "했다",
    "위해",
    "된다",
    "나서",
}


def tokenize_event_text(text: str) -> set[str]:
    """Return meaningful Korean/Latin tokens used for event comparison."""
    cleaned = re.sub(r"[^\w가-힣]+", " ", str(text or "").lower())
    return {
        token
        for token in cleaned.split()
        if len(token) >= 2 and token not in GENERIC_NEWS_TERMS
    }


def _character_ngrams(text: str, size: int = 3) -> set[str]:
    compact = re.sub(r"[^0-9a-z가-힣]+", "", str(text or "").lower())
    if not compact:
        return set()
    if len(compact) <= size:
        return {compact}
    return {compact[index:index + size] for index in range(len(compact) - size + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def candidate_event_similarity(left: dict, right: dict) -> tuple[float, int]:
    """Measure whether two candidate records describe the same news event."""
    left_title_tokens = tokenize_event_text(left.get("title", ""))
    right_title_tokens = tokenize_event_text(right.get("title", ""))
    shared_title_tokens = len(left_title_tokens & right_title_tokens)

    title_token_score = _jaccard(left_title_tokens, right_title_tokens)
    title_ngram_score = _jaccard(
        _character_ngrams(left.get("title", "")),
        _character_ngrams(right.get("title", "")),
    )
    description_score = _jaccard(
        tokenize_event_text(left.get("description", "")),
        tokenize_event_text(right.get("description", "")),
    )

    title_score = (title_token_score * 0.65) + (title_ngram_score * 0.35)
    combined_score = (title_score * 0.80) + (description_score * 0.20)
    return combined_score, shared_title_tokens


def _parse_candidate_time(candidate: dict) -> Optional[datetime]:
    for value in (candidate.get("pub_date"), candidate.get("created_at")):
        if not value:
            continue
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            try:
                parsed = datetime.fromisoformat(str(value))
            except (TypeError, ValueError):
                continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _within_event_window(left: dict, right: dict, max_hours: int) -> bool:
    left_time = _parse_candidate_time(left)
    right_time = _parse_candidate_time(right)
    if left_time is None or right_time is None:
        return True
    return abs((left_time - right_time).total_seconds()) <= max_hours * 3600


def _should_link_candidates(left: dict, right: dict, max_hours: int) -> bool:
    if not _within_event_window(left, right, max_hours):
        return False

    similarity, shared_tokens = candidate_event_similarity(left, right)
    return (
        shared_tokens >= 3 and similarity >= CLUSTER_SIMILARITY_THRESHOLD
    ) or (
        shared_tokens >= 2 and similarity >= CLUSTER_STRONG_SIMILARITY_THRESHOLD
    )


def cluster_candidate_articles(candidates: Iterable[dict], max_hours: int = CLUSTER_MAX_HOURS) -> list[list[dict]]:
    """Group candidates by event while preserving every individual article."""
    items = list(candidates)
    if not items:
        return []

    parents = list(range(len(items)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left_index: int, right_index: int) -> None:
        left_root = find(left_index)
        right_root = find(right_index)
        if left_root != right_root:
            parents[right_root] = left_root

    for left_index, left in enumerate(items):
        if left.get("cluster_excluded"):
            continue
        for right_index in range(left_index + 1, len(items)):
            right = items[right_index]
            if right.get("cluster_excluded"):
                continue
            if _should_link_candidates(left, right, max_hours):
                union(left_index, right_index)

    grouped: dict[int, list[dict]] = {}
    for index, item in enumerate(items):
        root = index if item.get("cluster_excluded") else find(index)
        grouped.setdefault(root, []).append(item)

    clusters = list(grouped.values())
    for cluster in clusters:
        cluster.sort(key=lambda item: int(item.get("id") or 0))
    clusters.sort(key=lambda cluster: int(cluster[0].get("id") or 0))
    return clusters


def select_cluster_representative(cluster: list[dict], source_counts: Optional[dict[str, int]] = None) -> dict:
    """Select a stable representative using user history, relevance, and cluster centrality."""
    if not cluster:
        raise ValueError("A candidate cluster cannot be empty.")

    overridden = [item for item in cluster if item.get("representative_override")]
    if overridden:
        return max(overridden, key=lambda item: (int(item.get("score") or 0), -int(item.get("id") or 0)))

    source_counts = source_counts or {}
    dated_items = sorted(
        cluster,
        key=lambda item: (_parse_candidate_time(item) or datetime.max.replace(tzinfo=timezone.utc), int(item.get("id") or 0)),
    )
    earliest_id = dated_items[0].get("id") if dated_items else None

    def representative_score(item: dict) -> tuple[float, int]:
        peers = [peer for peer in cluster if peer.get("id") != item.get("id")]
        similarities = [candidate_event_similarity(item, peer)[0] for peer in peers]
        centrality = sum(similarities) / len(similarities) if similarities else 1.0
        relevance = max(0.0, min(1.0, float(item.get("score") or 0) / 100))
        source_frequency = int(source_counts.get(str(item.get("source") or ""), 0))
        source_preference = min(1.0, math.log1p(source_frequency) / math.log(11)) if source_frequency else 0.0
        completeness = min(1.0, len(str(item.get("description") or "")) / 240)
        earliest_bonus = 1.0 if item.get("id") == earliest_id else 0.0
        total = (
            relevance * 0.45
            + source_preference * 0.25
            + centrality * 0.20
            + completeness * 0.05
            + earliest_bonus * 0.05
        )
        return total, -int(item.get("id") or 0)

    return max(cluster, key=representative_score)


def cluster_common_keywords(cluster: list[dict], limit: int = 4) -> list[str]:
    """Return title tokens shared by a majority of a candidate cluster."""
    if len(cluster) < 2:
        return []

    counts: Counter[str] = Counter()
    for item in cluster:
        counts.update(tokenize_event_text(item.get("title", "")))

    minimum_count = max(2, math.ceil(len(cluster) * 0.5))
    ranked = sorted(
        (token for token, count in counts.items() if count >= minimum_count),
        key=lambda token: (-counts[token], -len(token), token),
    )
    return ranked[:limit]
