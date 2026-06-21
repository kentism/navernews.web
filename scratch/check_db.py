import sqlite3
import os

db_path = "data/clipping_prototype.sqlite3"
if not os.path.exists(db_path):
    print("DB not found")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    tables = ["final_clipping_snapshots", "clipping_events", "article_embeddings", "clipping_candidates"]
    for t in tables:
        print(f"\n--- {t} ---")
        cursor.execute(f"PRAGMA table_info({t})")
        for col in cursor.fetchall():
            print(col)
    conn.close()
