import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import re
from typing import Optional
from urllib.parse import urlparse

from app_config import BASE_DIR


DB_PATH = BASE_DIR / "data" / "clipping_prototype.sqlite3"
DEFAULT_CATEGORIES = [
    "전원위 관련",
    "방송·통신 관련",
    "유관기관 관련",
    "기타",
]

CATEGORY_TERMS = {
    "전원위 관련": ["전원위", "전체회의", "위원회", "의결", "회의"],
    "방송·통신 관련": ["방송", "통신", "방통위", "방송통신", "미디어", "플랫폼"],
    "유관기관 관련": ["국회", "정부", "대통령실", "과기정통부", "문체부", "KCC"],
}


@contextmanager
def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link TEXT NOT NULL UNIQUE,
                original_link TEXT,
                title TEXT NOT NULL,
                description TEXT,
                source TEXT,
                domain TEXT,
                pub_date TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clipping_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                score INTEGER NOT NULL,
                suggested_category TEXT NOT NULL,
                similar_group_key TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                UNIQUE(article_id, keyword),
                FOREIGN KEY(article_id) REFERENCES articles(id)
            );

            CREATE TABLE IF NOT EXISTS clipping_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER,
                snapshot_id INTEGER,
                title TEXT NOT NULL,
                link TEXT NOT NULL,
                original_link TEXT,
                source TEXT,
                pub_date TEXT,
                category TEXT NOT NULL,
                action TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(article_id) REFERENCES articles(id)
            );

            CREATE TABLE IF NOT EXISTS final_clipping_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                entry_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS morning_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                cutoff_at TEXT NOT NULL,
                finished_at TEXT,
                keywords TEXT NOT NULL,
                candidate_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS candidate_keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            """
        )
        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(clipping_events)").fetchall()
        }
        if "snapshot_id" not in existing_columns:
            conn.execute("ALTER TABLE clipping_events ADD COLUMN snapshot_id INTEGER")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def parse_pub_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def get_default_cutoff() -> datetime:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT created_at FROM clipping_events
            WHERE action = 'finalized'
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
        if row:
            try:
                return datetime.fromisoformat(row["created_at"]).astimezone(timezone.utc)
            except Exception:
                pass

    return utc_now() - timedelta(days=1)


def _domain_from_link(link: str) -> str:
    return (urlparse(link or "").netloc or "").replace("www.", "")


def _group_key(title: str) -> str:
    tokens = [
        token
        for token in "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in title.lower()).split()
        if len(token) > 1
    ]
    return " ".join(tokens[:6]) or title[:24].lower()


def score_article(title: str, description: str, keyword: str, source: str = "") -> tuple[int, str]:
    text = f"{title} {description} {keyword}".lower()
    best_category = "기타"
    best_hits = 0

    for category, terms in CATEGORY_TERMS.items():
        hits = sum(1 for term in terms if term.lower() in text)
        if hits > best_hits:
            best_category = category
            best_hits = hits

    keyword_terms = [part.strip('+"-') for part in keyword.split() if part.strip('+"-')]
    keyword_hits = sum(1 for term in keyword_terms if term.lower() in text)
    score = min(100, 35 + best_hits * 18 + keyword_hits * 8)

    if source:
        score += 4

    return min(score, 100), best_category


def upsert_article(item) -> int:
    now = to_iso(utc_now())
    link = item.link or item.originallink
    original_link = item.originallink or link
    domain = item.domain or _domain_from_link(original_link)

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO articles (
                link, original_link, title, description, source, domain, pub_date, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(link) DO UPDATE SET
                original_link = excluded.original_link,
                title = excluded.title,
                description = excluded.description,
                source = excluded.source,
                domain = excluded.domain,
                pub_date = excluded.pub_date,
                last_seen_at = excluded.last_seen_at
            """,
            (
                link,
                original_link,
                item.title,
                item.description,
                item.source,
                domain,
                item.pubDate,
                now,
                now,
            ),
        )
        row = conn.execute("SELECT id FROM articles WHERE link = ?", (link,)).fetchone()
        return int(row["id"])


def create_candidate(item, keyword: str) -> bool:
    article_id = upsert_article(item)
    score, category = score_article(item.title, item.description, keyword, item.source)
    now = to_iso(utc_now())

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO clipping_candidates (
                article_id, keyword, score, suggested_category, similar_group_key, status, created_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (article_id, keyword, score, category, _group_key(item.title), now),
        )
        return cur.rowcount > 0


def list_candidate_keywords() -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT keyword FROM candidate_keywords
            ORDER BY created_at ASC, keyword ASC
            """
        ).fetchall()
        return [row["keyword"] for row in rows]


def add_candidate_keyword(keyword: str) -> bool:
    cleaned = keyword.strip()
    if not cleaned:
        return False

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO candidate_keywords (keyword, created_at)
            VALUES (?, ?)
            """,
            (cleaned, to_iso(utc_now())),
        )
        return cur.rowcount > 0


def remove_candidate_keyword(keyword: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM candidate_keywords WHERE keyword = ?", (keyword.strip(),))
        return cur.rowcount > 0


def list_candidates(status: str = "pending") -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id,
                c.keyword,
                c.score,
                c.suggested_category,
                c.similar_group_key,
                c.status,
                c.created_at,
                a.title,
                a.link,
                a.original_link,
                a.description,
                a.source,
                a.domain,
                a.pub_date,
                COUNT(peer.id) - 1 AS similar_count
            FROM clipping_candidates c
            JOIN articles a ON a.id = c.article_id
            LEFT JOIN clipping_candidates peer
                ON peer.similar_group_key = c.similar_group_key
                AND peer.status = c.status
            WHERE c.status = ?
            GROUP BY c.id
            ORDER BY c.score DESC, a.pub_date DESC, c.created_at DESC
            """,
            (status,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_candidate(candidate_id: int) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT c.*, a.title, a.link, a.original_link, a.source, a.pub_date
            FROM clipping_candidates c
            JOIN articles a ON a.id = c.article_id
            WHERE c.id = ?
            """,
            (candidate_id,),
        ).fetchone()
        return dict(row) if row else None


def record_clip_event(
    *,
    title: str,
    link: str,
    original_link: str,
    source: str,
    pub_date: str,
    category: str,
    action: str = "draft",
    article_id: Optional[int] = None,
    snapshot_id: Optional[int] = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO clipping_events (
                article_id, snapshot_id, title, link, original_link, source, pub_date, category, action, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article_id,
                snapshot_id,
                title,
                link,
                original_link,
                source,
                pub_date,
                category,
                action,
                to_iso(utc_now()),
            ),
        )


def accept_candidate(candidate_id: int, category: Optional[str] = None) -> Optional[dict]:
    candidate = get_candidate(candidate_id)
    if not candidate:
        return None

    final_category = category or candidate["suggested_category"]
    with _connect() as conn:
        conn.execute(
            """
            UPDATE clipping_candidates
            SET status = 'accepted', suggested_category = ?, reviewed_at = ?
            WHERE id = ?
            """,
            (final_category, to_iso(utc_now()), candidate_id),
        )

    record_clip_event(
        article_id=candidate["article_id"],
        title=candidate["title"],
        link=candidate["link"],
        original_link=candidate["original_link"],
        source=candidate["source"],
        pub_date=candidate["pub_date"],
        category=final_category,
        action="draft_candidate",
    )
    candidate["suggested_category"] = final_category
    return candidate


def reject_candidate(candidate_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE clipping_candidates
            SET status = 'rejected', reviewed_at = ?
            WHERE id = ?
            """,
            (to_iso(utc_now()), candidate_id),
        )
        return cur.rowcount > 0


def create_run(cutoff: datetime, keywords: list[str]) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO morning_runs (started_at, cutoff_at, keywords)
            VALUES (?, ?, ?)
            """,
            (to_iso(utc_now()), to_iso(cutoff), "\n".join(keywords)),
        )
        return int(cur.lastrowid)


def finish_run(run_id: int, candidate_count: int) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE morning_runs
            SET finished_at = ?, candidate_count = ?
            WHERE id = ?
            """,
            (to_iso(utc_now()), candidate_count, run_id),
        )


def _content_hash(content: str) -> str:
    import hashlib

    normalized = "\n".join(line.rstrip() for line in content.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _category_from_header(line: str) -> Optional[str]:
    stripped = line.strip().lstrip("#").strip()
    if not stripped:
        return None

    for category in DEFAULT_CATEGORIES:
        core = category.split()[0]
        if category in stripped or core in stripped:
            return category
    return None


def parse_final_clipping_entries(content: str) -> list[dict]:
    entries = []
    current_category = "기타"
    lines = content.splitlines()

    for index, line in enumerate(lines):
        category = _category_from_header(line)
        if category:
            current_category = category
            continue

        url_match = re.search(r"<?(https?://[^\s>]+)>?", line)
        if not url_match:
            continue

        previous = ""
        for prev_index in range(index - 1, -1, -1):
            if lines[prev_index].strip():
                previous = lines[prev_index].strip()
                break

        if not previous or re.search(r"<?https?://", previous):
            title = url_match.group(1)
            source = ""
        else:
            source = ""
            title = previous
            source_match = re.match(r"^\s*(?:[-*]\s*)?(?:[^\w\s])?\s*([^:：]{1,30})\s*[:：]\s*(.+)$", previous)
            if source_match:
                source = source_match.group(1).strip()
                title = source_match.group(2).strip()
            title = re.sub(r"\s*\(\d{1,2}\.\d{1,2}\.\)\s*$", "", title).strip()

        link = url_match.group(1).rstrip(".,)")
        entries.append(
            {
                "title": title,
                "link": link,
                "original_link": link,
                "source": source,
                "pub_date": "",
                "category": current_category,
            }
        )

    return entries


def find_article_id_by_link(link: str) -> Optional[int]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id FROM articles
            WHERE link = ? OR original_link = ?
            ORDER BY last_seen_at DESC
            LIMIT 1
            """,
            (link, link),
        ).fetchone()
        return int(row["id"]) if row else None


def save_final_clipping_snapshot(content: str) -> dict:
    entries = parse_final_clipping_entries(content)
    now = to_iso(utc_now())
    digest = _content_hash(content)

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO final_clipping_snapshots (content, content_hash, created_at, entry_count)
            VALUES (?, ?, ?, ?)
            """,
            (content, digest, now, len(entries)),
        )
        if cur.rowcount == 0:
            row = conn.execute(
                "SELECT id, entry_count FROM final_clipping_snapshots WHERE content_hash = ?",
                (digest,),
            ).fetchone()
            return {"snapshot_id": int(row["id"]), "entry_count": int(row["entry_count"]), "duplicate": True}

        snapshot_id = int(cur.lastrowid)

    for entry in entries:
        record_clip_event(
            article_id=find_article_id_by_link(entry["link"]),
            snapshot_id=snapshot_id,
            title=entry["title"],
            link=entry["link"],
            original_link=entry["original_link"],
            source=entry["source"],
            pub_date=entry["pub_date"],
            category=entry["category"],
            action="finalized",
        )

    return {"snapshot_id": snapshot_id, "entry_count": len(entries), "duplicate": False}
