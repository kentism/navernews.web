import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import re
import json
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app_config import CLIPPING_DB_PATH
from services.candidate_cluster_service import (
    candidate_event_similarity,
    cluster_candidate_articles,
    cluster_common_keywords,
    select_cluster_representative,
)


DB_PATH = CLIPPING_DB_PATH
CANDIDATE_SCORE_THRESHOLD = 55
CANDIDATE_PENDING_RETENTION_DAYS = 7
STORAGE_TABLES = [
    "articles",
    "final_clipping_snapshots",
    "clipping_events",
    "clipping_candidates",
    "morning_runs",
    "candidate_keywords",
]
STORAGE_RESTORE_ORDER = [
    "clipping_candidates",
    "clipping_events",
    "morning_runs",
    "candidate_keywords",
    "final_clipping_snapshots",
    "articles",
]
DEFAULT_CATEGORIES = [
    "\uc704\uc6d0\ud68c \uad00\ub828",
    "\ubc29\uc1a1\u00b7\ud1b5\uc2e0 \uad00\ub828",
    "\uc720\uad00\uae30\uad00 \uad00\ub828",
    "\uae30\ud0c0",
]

CATEGORY_TERMS = {
    "\uc704\uc6d0\ud68c \uad00\ub828": ["\uc704\uc6d0\ud68c", "\uc804\uccb4\ud68c\uc758", "\uc2ec\uc758", "\uc758\uacb0", "\ud68c\uc758"],
    "\ubc29\uc1a1\u00b7\ud1b5\uc2e0 \uad00\ub828": ["\ubc29\uc1a1", "\ud1b5\uc2e0", "\ubc29\ud1b5\uc704", "\ubc29\uc1a1\ud1b5\uc2e0", "\ubbf8\ub514\uc5b4", "\ud50c\ub7ab\ud3fc"],
    "\uc720\uad00\uae30\uad00 \uad00\ub828": ["\uad6d\ud68c", "\uc815\ubd80", "\ub300\ud1b5\ub839\uc2e4", "\uacfc\uae30\uc815\ud1b5\ubd80", "\ubb38\uccb4\ubd80", "KCC"],
}
TRACKING_QUERY_PREFIXES = ("utm_",)


def normalize_article_url(url: str) -> str:
    """Remove non-functional analytics query parameters while preserving article identifiers."""
    cleaned_url = str(url or "").strip()
    if not cleaned_url:
        return ""

    parsed = urlparse(cleaned_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return cleaned_url

    filtered_params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith(TRACKING_QUERY_PREFIXES)
    ]
    return urlunparse(parsed._replace(query=urlencode(filtered_params, doseq=True)))

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
                score_reasons TEXT,
                suggested_category TEXT NOT NULL,
                similar_group_key TEXT,
                cluster_similarity REAL NOT NULL DEFAULT 1,
                cluster_representative INTEGER NOT NULL DEFAULT 0,
                representative_override INTEGER NOT NULL DEFAULT 0,
                cluster_excluded INTEGER NOT NULL DEFAULT 0,
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

            CREATE TABLE IF NOT EXISTS article_embeddings (
                article_id INTEGER PRIMARY KEY,
                vector_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(article_id) REFERENCES articles(id)
            );
            """
        )
        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(clipping_events)").fetchall()
        }
        if "snapshot_id" not in existing_columns:
            conn.execute("ALTER TABLE clipping_events ADD COLUMN snapshot_id INTEGER")
        candidate_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(clipping_candidates)").fetchall()
        }
        candidate_column_definitions = {
            "score_reasons": "TEXT",
            "similar_group_key": "TEXT",
            "cluster_similarity": "REAL NOT NULL DEFAULT 1",
            "cluster_representative": "INTEGER NOT NULL DEFAULT 0",
            "representative_override": "INTEGER NOT NULL DEFAULT 0",
            "cluster_excluded": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, definition in candidate_column_definitions.items():
            if column not in candidate_columns:
                conn.execute(f"ALTER TABLE clipping_candidates ADD COLUMN {column} {definition}")


def get_storage_status() -> dict:
    status = {
        "db_path": str(DB_PATH),
        "data_dir": str(DB_PATH.parent),
        "db_exists": DB_PATH.exists(),
        "db_size_bytes": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        "data_dir_writable": False,
        "write_error": None,
        "counts": {},
        "candidate_status_counts": {},
    }

    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        probe_path = DB_PATH.parent / ".write_probe"
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink(missing_ok=True)
        status["data_dir_writable"] = True
    except OSError as exc:
        status["write_error"] = str(exc)

    if not DB_PATH.exists():
        return status

    try:
        with _connect() as conn:
            for table in [
                "articles",
                "clipping_candidates",
                "clipping_events",
                "final_clipping_snapshots",
                "morning_runs",
                "candidate_keywords",
            ]:
                row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
                status["counts"][table] = row["count"] if row else 0

            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM clipping_candidates
                GROUP BY status
                ORDER BY status
                """
            ).fetchall()
            status["candidate_status_counts"] = {
                row["status"]: row["count"]
                for row in rows
            }
    except sqlite3.Error as exc:
        status["write_error"] = str(exc)

    return status


def _table_columns(conn, table: str) -> list[str]:
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def export_storage_snapshot() -> dict:
    init_db()
    with _connect() as conn:
        tables = {}
        for table in STORAGE_TABLES:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            tables[table] = [dict(row) for row in rows]

    return {
        "version": 1,
        "exported_at": to_iso(utc_now()),
        "storage": get_storage_status(),
        "tables": tables,
    }


def import_storage_snapshot(snapshot: dict, *, replace: bool = True) -> dict:
    if not isinstance(snapshot, dict):
        raise ValueError("Backup payload must be a JSON object.")

    tables = snapshot.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("Backup payload must contain a tables object.")

    unknown_tables = sorted(set(tables) - set(STORAGE_TABLES))
    if unknown_tables:
        raise ValueError(f"Backup payload contains unknown tables: {', '.join(unknown_tables)}")

    init_db()
    imported_counts = {}

    with _connect() as conn:
        column_map = {
            table: set(_table_columns(conn, table))
            for table in STORAGE_TABLES
        }

        if replace:
            for table in STORAGE_RESTORE_ORDER:
                conn.execute(f"DELETE FROM {table}")

        for table in STORAGE_TABLES:
            rows = tables.get(table, [])
            if not isinstance(rows, list):
                raise ValueError(f"Table {table} must be a list.")

            imported_counts[table] = 0
            allowed_columns = column_map[table]

            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError(f"Table {table} contains a non-object row.")

                unknown_columns = sorted(set(row) - allowed_columns)
                if unknown_columns:
                    raise ValueError(
                        f"Table {table} contains unknown columns: {', '.join(unknown_columns)}"
                    )

                columns = [column for column in _table_columns(conn, table) if column in row]
                if not columns:
                    continue

                placeholders = ", ".join(["?"] * len(columns))
                column_sql = ", ".join(columns)
                values = [row[column] for column in columns]
                conn.execute(
                    f"INSERT OR REPLACE INTO {table} ({column_sql}) VALUES ({placeholders})",
                    values,
                )
                imported_counts[table] += 1

    return {
        "imported_counts": imported_counts,
        "storage": get_storage_status(),
    }


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
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT created_at FROM clipping_events
                WHERE action = 'finalized'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
            if row and row["created_at"]:
                try:
                    return datetime.fromisoformat(row["created_at"]).astimezone(timezone.utc)
                except Exception:
                    pass
    except Exception as e:
        print(f"Error in get_default_cutoff: {e}")

    # Fallback to 24 hours ago
    return utc_now() - timedelta(days=1)

def list_finalizations(limit: int = 30) -> list[dict]:
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, entry_count, SUBSTR(content, 1, 150) as preview 
                FROM final_clipping_snapshots 
                ORDER BY created_at DESC 
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        print(f"Error in list_finalizations: {e}")
        return []


def get_finalization(snapshot_id: int) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, content, created_at, entry_count
            FROM final_clipping_snapshots
            WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone()
        return dict(row) if row else None


def get_learning_summary() -> dict:
    init_db()
    summary = {
        "snapshot_count": 0,
        "finalized_event_count": 0,
        "candidate_count": 0,
        "last_finalized_at": None,
        "last_snapshot_entry_count": 0,
        "top_sources": [],
        "top_categories": [],
    }

    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS snapshot_count,
                    MAX(created_at) AS last_finalized_at
                FROM final_clipping_snapshots
                """
            ).fetchone()
            if row:
                summary["snapshot_count"] = int(row["snapshot_count"] or 0)
                summary["last_finalized_at"] = row["last_finalized_at"]

            row = conn.execute(
                """
                SELECT entry_count
                FROM final_clipping_snapshots
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
            if row:
                summary["last_snapshot_entry_count"] = int(row["entry_count"] or 0)

            row = conn.execute(
                "SELECT COUNT(*) AS count FROM clipping_events WHERE action = 'finalized'"
            ).fetchone()
            summary["finalized_event_count"] = int(row["count"] or 0) if row else 0

            row = conn.execute("SELECT COUNT(*) AS count FROM clipping_candidates").fetchone()
            summary["candidate_count"] = int(row["count"] or 0) if row else 0

            source_rows = conn.execute(
                """
                SELECT source, COUNT(*) AS count
                FROM clipping_events
                WHERE action = 'finalized' AND COALESCE(source, '') != ''
                GROUP BY source
                ORDER BY count DESC, source ASC
                LIMIT 5
                """
            ).fetchall()
            summary["top_sources"] = [dict(row) for row in source_rows]

            category_rows = conn.execute(
                """
                SELECT category, COUNT(*) AS count
                FROM clipping_events
                WHERE action = 'finalized' AND COALESCE(category, '') != ''
                GROUP BY category
                ORDER BY count DESC, category ASC
                LIMIT 5
                """
            ).fetchall()
            summary["top_categories"] = [dict(row) for row in category_rows]
    except sqlite3.Error as exc:
        summary["error"] = str(exc)

    return summary


def delete_finalization(snapshot_id: int) -> bool:
    with _connect() as conn:
        # 1. Clean up events
        conn.execute("DELETE FROM clipping_events WHERE snapshot_id = ?", (snapshot_id,))
        # 2. Delete snapshot
        cur = conn.execute("DELETE FROM final_clipping_snapshots WHERE id = ?", (snapshot_id,))
        return cur.rowcount > 0


def _find_article_id_by_link_conn(conn, link: str) -> Optional[int]:
    normalized_link = normalize_article_url(link)
    links = [value for value in {str(link or "").strip(), normalized_link} if value]
    if not links:
        return None

    placeholders = ",".join("?" for _ in links)
    row = conn.execute(
        f"""
        SELECT id FROM articles
        WHERE link IN ({placeholders}) OR original_link IN ({placeholders})
        ORDER BY last_seen_at DESC
        LIMIT 1
        """,
        (*links, *links),
    ).fetchone()
    if row:
        return int(row["id"])

    parsed = urlparse(normalized_link)
    prefix = urlunparse(parsed._replace(query="", fragment=""))
    if not prefix:
        return None

    rows = conn.execute(
        """
        SELECT id, link, original_link FROM articles
        WHERE link LIKE ? OR original_link LIKE ?
        ORDER BY last_seen_at DESC
        LIMIT 50
        """,
        (f"{prefix}%", f"{prefix}%"),
    ).fetchall()
    for candidate in rows:
        if (
            normalize_article_url(candidate["link"]) == normalized_link
            or normalize_article_url(candidate["original_link"]) == normalized_link
        ):
            return int(candidate["id"])

    return None


def update_finalization(snapshot_id: int, content: str) -> dict:
    entries = parse_final_clipping_entries(content)
    digest = _content_hash(content)

    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM final_clipping_snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        if not existing:
            return {"updated": False, "reason": "not_found"}

        duplicate = conn.execute(
            """
            SELECT id FROM final_clipping_snapshots
            WHERE content_hash = ? AND id != ?
            LIMIT 1
            """,
            (digest, snapshot_id),
        ).fetchone()
        if duplicate:
            return {
                "updated": False,
                "duplicate": True,
                "snapshot_id": int(duplicate["id"]),
            }

        conn.execute(
            """
            UPDATE final_clipping_snapshots
            SET content = ?, content_hash = ?, entry_count = ?
            WHERE id = ?
            """,
            (content, digest, len(entries), snapshot_id),
        )
        conn.execute("DELETE FROM clipping_events WHERE snapshot_id = ?", (snapshot_id,))

        matched_count = 0
        unmatched_count = 0
        for entry in entries:
            article_id = _find_article_id_by_link_conn(conn, entry["link"])
            if article_id:
                matched_count += 1
            else:
                unmatched_count += 1

            conn.execute(
                """
                INSERT INTO clipping_events (
                    article_id, snapshot_id, title, link, original_link, source, pub_date, category, action, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'finalized', ?)
                """,
                (
                    article_id,
                    snapshot_id,
                    entry["title"],
                    entry["link"],
                    entry["original_link"],
                    entry["source"],
                    entry["pub_date"],
                    entry["category"],
                    to_iso(utc_now()),
                ),
            )

        return {
            "updated": True,
            "snapshot_id": snapshot_id,
            "entry_count": len(entries),
            "matched_count": matched_count,
            "unmatched_count": unmatched_count,
        }


def _domain_from_link(link: str) -> str:
    return (urlparse(normalize_article_url(link)).netloc or "").replace("www.", "")


def _tokenize(text: str) -> set[str]:
    cleaned = re.sub(r"[^\w가-힣]+", " ", (text or "").lower())
    return {token for token in cleaned.split() if len(token) >= 2}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _load_learning_examples(limit: int = 80) -> tuple[list[dict], list[dict]]:
    with _connect() as conn:
        finalized = [
            dict(row)
            for row in conn.execute(
                """
                SELECT title, source, category
                FROM clipping_events
                WHERE action = 'finalized'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        ]
        rejected = [
            dict(row)
            for row in conn.execute(
                """
                SELECT a.title, a.source, c.suggested_category AS category
                FROM clipping_candidates c
                JOIN articles a ON a.id = c.article_id
                WHERE c.status = 'rejected'
                ORDER BY c.reviewed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        ]
    return finalized, rejected


def score_article(title: str, description: str, keyword: str, source: str = "") -> tuple[int, str, list[str]]:
    text = f"{title} {description} {keyword}".lower()
    best_category = "\uae30\ud0c0"
    best_hits = 0
    reasons: list[str] = []

    for category, terms in CATEGORY_TERMS.items():
        hits = sum(1 for term in terms if term.lower() in text)
        if hits > best_hits:
            best_category = category
            best_hits = hits

    keyword_terms = [part.strip('+"-') for part in keyword.split() if part.strip('+"-')]
    keyword_hits = sum(1 for term in keyword_terms if term.lower() in text)

    score = 20
    if keyword_hits:
        bonus = min(25, keyword_hits * 10)
        score += bonus
        reasons.append(f"\uac80\uc0c9\uc5b4\uc640 \uc9c1\uc811 \uad00\ub828\ub41c \ud45c\ud604 +{bonus}")
    if best_hits:
        bonus = min(24, best_hits * 8)
        score += bonus
        reasons.append(f"{best_category} \ubd84\ub958 \ud0a4\uc6cc\ub4dc \ud3ec\ud568 +{bonus}")
    if source:
        score += 4
        reasons.append("\ucd9c\ucc98 \uc815\ubcf4 \ud655\uc778 +4")

    finalized, rejected = _load_learning_examples()
    current_tokens = _tokenize(f"{title} {description}")

    if finalized:
        finalized_sources = {example.get("source") for example in finalized if example.get("source")}
        if source and source in finalized_sources:
            score += 8
            reasons.append("\ucd5c\uc885\ubcf8\uc5d0 \uc790\uc8fc \ub4f1\uc7a5\ud55c \ucd9c\ucc98 +8")

        similarities = [
            _jaccard(current_tokens, _tokenize(example.get("title", "")))
            for example in finalized
        ]
        max_similarity = max(similarities or [0.0])
        if max_similarity >= 0.18:
            bonus = min(25, int(max_similarity * 60))
            score += bonus
            reasons.append(f"\ucd5c\uc885\ubcf8 \ud559\uc2b5 \uc0ac\ub840\uc640 \uc81c\ubaa9 \uc720\uc0ac +{bonus}")
    else:
        reasons.append("\uc544\uc9c1 \ud559\uc2b5 \uc0ac\ub840\uac00 \ubd80\uc871\ud574 \uac80\uc0c9\uc5b4/\ubd84\ub958 \ud0a4\uc6cc\ub4dc \uae30\ubc18\uc73c\ub85c \ud310\ub2e8")

    if rejected:
        similarities = [
            _jaccard(current_tokens, _tokenize(example.get("title", "")))
            for example in rejected
        ]
        max_similarity = max(similarities or [0.0])
        if max_similarity >= 0.18:
            penalty = min(28, int(max_similarity * 60))
            score -= penalty
            reasons.append(f"\uc81c\uc678\ud55c \uae30\uc0ac\uc640 \uc81c\ubaa9 \uc720\uc0ac -{penalty}")

    final_score = max(0, min(100, score))
    if final_score < CANDIDATE_SCORE_THRESHOLD:
        reasons.append(f"\ud6c4\ubcf4 \uc120\ubcc4 \uae30\uc900 {CANDIDATE_SCORE_THRESHOLD}\uc810 \ubbf8\ub9cc")
    return final_score, best_category, reasons

def _find_existing_article_id(conn, link: str, original_link: str) -> Optional[int]:
    for candidate_url in (link, original_link):
        article_id = _find_article_id_by_link_conn(conn, candidate_url)
        if article_id:
            return article_id
    return None


def upsert_article(item) -> int:
    now = to_iso(utc_now())
    link = normalize_article_url(item.link or item.originallink)
    original_link = normalize_article_url(item.originallink or link)
    domain = item.domain or _domain_from_link(original_link)

    with _connect() as conn:
        existing_id = _find_existing_article_id(conn, link, original_link)
        if existing_id:
            conn.execute(
                """
                UPDATE articles
                SET original_link = ?,
                    title = ?,
                    description = ?,
                    source = ?,
                    domain = ?,
                    pub_date = ?,
                    last_seen_at = ?
                WHERE id = ?
                """,
                (
                    original_link,
                    item.title,
                    item.description,
                    item.source,
                    domain,
                    item.pubDate,
                    now,
                    existing_id,
                ),
            )
            return existing_id

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


def _merge_candidate_keywords(existing_keyword: str, keyword: str) -> str:
    keywords = [
        item.strip()
        for item in str(existing_keyword or "").split(",")
        if item.strip()
    ]
    cleaned_keyword = keyword.strip()
    if cleaned_keyword and cleaned_keyword not in keywords:
        keywords.append(cleaned_keyword)
    return ", ".join(keywords)


async def create_candidate(item, keyword: str) -> dict:
    article_id = upsert_article(item)

    # Check if this article was already finalized
    with _connect() as conn:
        already_finalized = conn.execute(
            "SELECT 1 FROM clipping_events WHERE article_id = ? AND action = 'finalized' LIMIT 1",
            (article_id,)
        ).fetchone()
        if already_finalized:
            return {"status": "finalized", "created": False, "score": 0}
        existing = conn.execute(
            """
            SELECT id, keyword, status FROM clipping_candidates
            WHERE article_id = ?
            LIMIT 1
            """,
            (article_id,),
        ).fetchone()
        if existing:
            merged_keyword = _merge_candidate_keywords(existing["keyword"], keyword)
            if existing["status"] == "pending" and merged_keyword != existing["keyword"]:
                conn.execute(
                    """
                    UPDATE clipping_candidates
                    SET keyword = ?
                    WHERE id = ?
                    """,
                    (merged_keyword, existing["id"]),
                )
            return {"status": "duplicate", "created": False, "score": 0}

    score, category, reasons = score_article(item.title, item.description, keyword, item.source)
    if score < CANDIDATE_SCORE_THRESHOLD:
        return {"status": "low_score", "created": False, "score": score}

    now = to_iso(utc_now())

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO clipping_candidates (
                article_id, keyword, score, score_reasons, suggested_category, similar_group_key, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (article_id, keyword, score, json.dumps(reasons, ensure_ascii=False), category, None, now),
        )
        return {"status": "created" if cur.rowcount > 0 else "duplicate", "created": cur.rowcount > 0, "score": score}


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


def list_candidate_status_counts() -> dict[str, int]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM clipping_candidates
            GROUP BY status
            """
        ).fetchall()
        return {row["status"]: int(row["count"] or 0) for row in rows}


def _deserialize_candidate(row) -> dict:
    candidate = dict(row)
    try:
        candidate["score_reasons"] = json.loads(candidate.get("score_reasons") or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        candidate["score_reasons"] = []
    candidate["cluster_representative"] = bool(candidate.get("cluster_representative"))
    candidate["representative_override"] = bool(candidate.get("representative_override"))
    candidate["cluster_excluded"] = bool(candidate.get("cluster_excluded"))
    return candidate


def _load_candidate_rows(status: str) -> list[dict]:
    if status == "accepted":
        where_clause = """
            c.status = 'accepted'
            OR (
                c.status = 'covered'
                AND c.similar_group_key IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM clipping_candidates accepted
                    WHERE accepted.similar_group_key = c.similar_group_key
                    AND accepted.status = 'accepted'
                )
            )
        """
        params: tuple = ()
    else:
        where_clause = "c.status = ?"
        params = (status,)

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                c.id,
                c.article_id,
                c.keyword,
                c.score,
                c.score_reasons,
                c.suggested_category,
                c.similar_group_key,
                c.cluster_similarity,
                c.cluster_representative,
                c.representative_override,
                c.cluster_excluded,
                c.status,
                c.created_at,
                c.reviewed_at,
                a.title,
                a.link,
                a.original_link,
                a.description,
                a.source,
                a.domain,
                a.pub_date
            FROM clipping_candidates c
            JOIN articles a ON a.id = c.article_id
            WHERE {where_clause}
            ORDER BY c.score DESC, a.pub_date DESC, c.created_at DESC
            """,
            params,
        ).fetchall()
        return [_deserialize_candidate(row) for row in rows]


def list_candidates(status: str = "pending") -> list[dict]:
    candidates = _load_candidate_rows(status)
    group_counts: dict[str, int] = {}
    for candidate in candidates:
        group_key = candidate.get("similar_group_key")
        if group_key:
            group_counts[group_key] = group_counts.get(group_key, 0) + 1
    for candidate in candidates:
        group_key = candidate.get("similar_group_key")
        candidate["similar_count"] = max(0, group_counts.get(group_key, 1) - 1) if group_key else 0
    return candidates


def _load_finalized_source_counts(conn) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT source, COUNT(*) AS count
        FROM clipping_events
        WHERE action = 'finalized' AND source IS NOT NULL AND source != ''
        GROUP BY source
        """
    ).fetchall()
    return {str(row["source"]): int(row["count"] or 0) for row in rows}


def recluster_pending_candidates() -> dict:
    """Rebuild pending event clusters without deleting individual candidates."""
    candidates = _load_candidate_rows("pending")
    clusters = cluster_candidate_articles(candidates)

    with _connect() as conn:
        source_counts = _load_finalized_source_counts(conn)
        for cluster in clusters:
            representative = select_cluster_representative(cluster, source_counts)
            representative_id = int(representative["id"])
            minimum_id = min(int(candidate["id"]) for candidate in cluster)
            group_key = f"story:{minimum_id}" if len(cluster) > 1 else f"single:{minimum_id}"

            for candidate in cluster:
                candidate_id = int(candidate["id"])
                similarity = 1.0
                if candidate_id != representative_id:
                    similarity = candidate_event_similarity(candidate, representative)[0]
                conn.execute(
                    """
                    UPDATE clipping_candidates
                    SET similar_group_key = ?,
                        cluster_similarity = ?,
                        cluster_representative = ?
                    WHERE id = ?
                    """,
                    (group_key, round(similarity, 4), int(candidate_id == representative_id), candidate_id),
                )

    return {
        "group_count": len(clusters),
        "article_count": len(candidates),
        "related_article_count": sum(max(0, len(cluster) - 1) for cluster in clusters),
    }


def ensure_candidate_clusters() -> None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM clipping_candidates
            WHERE status = 'pending'
              AND (
                  similar_group_key IS NULL
                  OR (similar_group_key NOT LIKE 'story:%' AND similar_group_key NOT LIKE 'single:%')
              )
            LIMIT 1
            """
        ).fetchone()
    if row:
        recluster_pending_candidates()


def list_candidate_groups(status: str = "pending") -> list[dict]:
    """Return one representative per event with the remaining articles nested beneath it."""
    if status == "pending":
        ensure_candidate_clusters()

    candidates = _load_candidate_rows(status)
    grouped: dict[str, list[dict]] = {}
    for candidate in candidates:
        if status == "rejected":
            group_key = f"candidate:{candidate['id']}"
        else:
            group_key = candidate.get("similar_group_key") or f"candidate:{candidate['id']}"
        grouped.setdefault(group_key, []).append(candidate)

    groups: list[dict] = []
    for group_key, members in grouped.items():
        if status == "accepted":
            representative = next((item for item in members if item.get("status") == "accepted"), members[0])
        else:
            representative = next((item for item in members if item.get("cluster_representative")), members[0])

        related_items = [item for item in members if item["id"] != representative["id"]]
        related_items.sort(key=lambda item: (-int(item.get("score") or 0), int(item.get("id") or 0)))
        group = dict(representative)
        group["similar_group_key"] = group_key
        group["related_items"] = related_items
        group["related_count"] = len(related_items)
        group["cluster_size"] = len(members)
        group["cluster_keywords"] = cluster_common_keywords(members)
        groups.append(group)

    return groups


def set_candidate_representative(candidate_id: int) -> bool:
    ensure_candidate_clusters()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT similar_group_key FROM clipping_candidates
            WHERE id = ? AND status = 'pending'
            """,
            (candidate_id,),
        ).fetchone()
        if not row or not row["similar_group_key"]:
            return False
        conn.execute(
            """
            UPDATE clipping_candidates
            SET representative_override = 0
            WHERE similar_group_key = ? AND status = 'pending'
            """,
            (row["similar_group_key"],),
        )
        conn.execute(
            "UPDATE clipping_candidates SET representative_override = 1 WHERE id = ?",
            (candidate_id,),
        )
    recluster_pending_candidates()
    return True


def ungroup_candidate(candidate_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE clipping_candidates
            SET cluster_excluded = 1,
                representative_override = 0,
                similar_group_key = ?,
                cluster_similarity = 1,
                cluster_representative = 1
            WHERE id = ? AND status = 'pending'
            """,
            (f"single:{candidate_id}", candidate_id),
        )
    if cur.rowcount:
        recluster_pending_candidates()
        return True
    return False


def restore_candidate_auto_grouping(candidate_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE clipping_candidates
            SET cluster_excluded = 0,
                similar_group_key = NULL,
                cluster_similarity = 1,
                cluster_representative = 0
            WHERE id = ? AND status = 'pending'
            """,
            (candidate_id,),
        )
    if cur.rowcount:
        recluster_pending_candidates()
        return True
    return False


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
    link = normalize_article_url(link)
    original_link = normalize_article_url(original_link or link)
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
    if not candidate or candidate.get("status") != "pending":
        return None

    final_category = category or candidate["suggested_category"]
    reviewed_at = to_iso(utc_now())
    covered_count = 0
    with _connect() as conn:
        conn.execute(
            """
            UPDATE clipping_candidates
            SET status = 'accepted',
                suggested_category = ?,
                reviewed_at = ?,
                cluster_representative = 1,
                representative_override = 1
            WHERE id = ? AND status = 'pending'
            """,
            (final_category, reviewed_at, candidate_id),
        )
        group_key = candidate.get("similar_group_key")
        if group_key and str(group_key).startswith("story:"):
            covered = conn.execute(
                """
                UPDATE clipping_candidates
                SET status = 'covered',
                    reviewed_at = ?,
                    cluster_representative = 0,
                    representative_override = 0
                WHERE similar_group_key = ?
                  AND status = 'pending'
                  AND id != ?
                """,
                (reviewed_at, group_key, candidate_id),
            )
            covered_count = int(covered.rowcount or 0)

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
    candidate["status"] = "accepted"
    candidate["related_covered_count"] = covered_count
    return candidate


def reject_candidate(candidate_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE clipping_candidates
            SET status = 'rejected', reviewed_at = ?, cluster_representative = 0
            WHERE id = ? AND status = 'pending'
            """,
            (to_iso(utc_now()), candidate_id),
        )
        updated = cur.rowcount > 0
    if updated:
        recluster_pending_candidates()
    return updated


def restore_rejected_candidate(candidate_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE clipping_candidates
            SET status = 'pending',
                reviewed_at = NULL,
                similar_group_key = NULL,
                cluster_similarity = 1,
                cluster_representative = 0,
                representative_override = 0,
                cluster_excluded = 0
            WHERE id = ? AND status = 'rejected'
            """,
            (candidate_id,),
        )
        updated = cur.rowcount > 0
    if updated:
        recluster_pending_candidates()
    return updated


def restore_covered_candidate(candidate_id: int) -> bool:
    """Return a neutrally covered related article to the pending review queue."""
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE clipping_candidates
            SET status = 'pending',
                reviewed_at = NULL,
                similar_group_key = NULL,
                cluster_similarity = 1,
                cluster_representative = 0,
                representative_override = 0,
                cluster_excluded = 0
            WHERE id = ? AND status = 'covered'
            """,
            (candidate_id,),
        )
        updated = cur.rowcount > 0
    if updated:
        recluster_pending_candidates()
    return updated


def delete_candidate(candidate_id: int) -> bool:
    with _connect() as conn:
        candidate = conn.execute(
            "SELECT status, similar_group_key FROM clipping_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if not candidate:
            return False
        if candidate["status"] == "accepted" and candidate["similar_group_key"]:
            conn.execute(
                """
                UPDATE clipping_candidates
                SET status = 'pending',
                    reviewed_at = NULL,
                    similar_group_key = NULL,
                    cluster_similarity = 1,
                    cluster_representative = 0,
                    representative_override = 0
                WHERE similar_group_key = ? AND status = 'covered'
                """,
                (candidate["similar_group_key"],),
            )
        cur = conn.execute("DELETE FROM clipping_candidates WHERE id = ?", (candidate_id,))
        deleted = cur.rowcount > 0
        should_recluster = candidate["status"] in {"pending", "accepted"}
    if deleted and should_recluster:
        recluster_pending_candidates()
    return deleted


def clear_pending_candidates() -> int:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM clipping_candidates WHERE status = 'pending'")
        return cur.rowcount


def cleanup_stale_pending_candidates(days: int = CANDIDATE_PENDING_RETENTION_DAYS) -> int:
    cutoff = to_iso(utc_now() - timedelta(days=days))
    with _connect() as conn:
        cur = conn.execute(
            """
            DELETE FROM clipping_candidates
            WHERE status = 'pending' AND created_at < ?
            """,
            (cutoff,),
        )
        deleted = int(cur.rowcount or 0)
    if deleted:
        recluster_pending_candidates()
    return deleted


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
    current_category = "\uae30\ud0c0"
    lines = content.splitlines()

    for index, line in enumerate(lines):
        category = _category_from_header(line)
        if category:
            current_category = category
            continue

        url_match = re.search(r"(?:<|\[.*\]\()?(https?://[^\s>)]+)(?:>|\))?", line)
        if not url_match:
            continue

        link = normalize_article_url(url_match.group(1).rstrip(".,)"))

        previous = ""
        for prev_index in range(index - 1, -1, -1):
            p_line = lines[prev_index].strip()
            if p_line and not re.search(r"https?://", p_line) and not p_line.startswith("#"):
                previous = p_line
                break

        title = link
        source = ""

        if previous:
            source_match = re.match(r"^\s*(?:[\u25b7\-*]\s*)?([^:\uff1a]+)\s*[:\uff1a]\s*(.+)$", previous)
            if source_match:
                source = source_match.group(1).strip()
                title = source_match.group(2).strip()
            else:
                title = previous.lstrip("\u25b7-* ").strip()

            title = re.sub(r"\s*[\(\[]\d{1,2}\.\d{1,2}\.?[\)\]]\s*$", "", title).strip()

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
        return _find_article_id_by_link_conn(conn, link)


async def save_final_clipping_snapshot(content: str) -> dict:
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
            return {
                "snapshot_id": int(row["id"]),
                "entry_count": int(row["entry_count"]),
                "matched_count": None,
                "unmatched_count": None,
                "duplicate": True,
            }

        snapshot_id = int(cur.lastrowid)

    matched_count = 0
    unmatched_count = 0
    for entry in entries:
        article_id = find_article_id_by_link(entry["link"])
        if article_id:
            matched_count += 1
        else:
            unmatched_count += 1
        
        record_clip_event(
            article_id=article_id,
            snapshot_id=snapshot_id,
            title=entry["title"],
            link=entry["link"],
            original_link=entry["original_link"],
            source=entry["source"],
            pub_date=entry["pub_date"],
            category=entry["category"],
            action="finalized",
        )

    return {
        "snapshot_id": snapshot_id,
        "entry_count": len(entries),
        "matched_count": matched_count,
        "unmatched_count": unmatched_count,
        "duplicate": False,
    }


# Initialize DB on import
init_db()
