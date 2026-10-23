import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app_config import CLIPPING_DB_PATH

LEGACY_TABLES = ("articles", "final_clipping_snapshots", "clipping_events",
                 "clipping_candidates", "morning_runs", "candidate_keywords")


def inspect_legacy_archive(path=None, *, include_rows=False):
    """Read old learning data without creating, migrating, or changing its database."""
    path = Path(path or CLIPPING_DB_PATH)
    result = {"db_exists": path.is_file(), "db_size_bytes": path.stat().st_size if path.is_file() else 0,
              "read_only": True, "counts": {}}
    tables = {}
    if path.is_file():
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN")
            existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in LEGACY_TABLES:
                if table not in existing:
                    continue
                result["counts"][table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if include_rows:
                    tables[table] = [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
        finally:
            conn.close()
    if include_rows:
        return {"version": 1, "exported_at": datetime.now(timezone.utc).isoformat(),
                "storage": result, "tables": tables}
    return result
