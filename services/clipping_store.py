import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import re
import json
from typing import Optional
from urllib.parse import urlparse

from app_config import CLIPPING_DB_PATH


DB_PATH = CLIPPING_DB_PATH
CANDIDATE_SCORE_THRESHOLD = 55
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
        if "score_reasons" not in candidate_columns:
            conn.execute("ALTER TABLE clipping_candidates ADD COLUMN score_reasons TEXT")


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

def delete_finalization(snapshot_id: int) -> bool:
    with _connect() as conn:
        # 1. Clean up events
        conn.execute("DELETE FROM clipping_events WHERE snapshot_id = ?", (snapshot_id,))
        # 2. Delete snapshot
        cur = conn.execute("DELETE FROM final_clipping_snapshots WHERE id = ?", (snapshot_id,))
        return cur.rowcount > 0


def _domain_from_link(link: str) -> str:
    return (urlparse(link or "").netloc or "").replace("www.", "")


def _group_key(title: str) -> str:
    tokens = [
        token
        for token in "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in title.lower()).split()
        if len(token) > 1
    ]
    return " ".join(tokens[:6]) or title[:24].lower()


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
            SELECT status FROM clipping_candidates
            WHERE article_id = ? AND keyword = ?
            LIMIT 1
            """,
            (article_id, keyword),
        ).fetchone()
        if existing:
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
            (article_id, keyword, score, json.dumps(reasons, ensure_ascii=False), category, _group_key(item.title), now),
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


def list_candidates(status: str = "pending") -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id,
                c.keyword,
                c.score,
                c.score_reasons,
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
        candidates = []
        for row in rows:
            candidate = dict(row)
            try:
                candidate["score_reasons"] = json.loads(candidate.get("score_reasons") or "[]")
            except Exception:
                candidate["score_reasons"] = []
            candidates.append(candidate)
        return candidates


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

        link = url_match.group(1).rstrip(".,)")

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
