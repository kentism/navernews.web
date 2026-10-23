import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from services.legacy_archive import inspect_legacy_archive


class LegacyArchiveTests(unittest.TestCase):
    def test_export_preserves_existing_database_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.sqlite3'
            with closing(sqlite3.connect(path)) as conn:
                conn.execute('CREATE TABLE final_clipping_snapshots(id INTEGER, content TEXT)')
                conn.execute('INSERT INTO final_clipping_snapshots VALUES(1, ?)', ('기존 최종본',))
                conn.commit()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            result = inspect_legacy_archive(path, include_rows=True)
            self.assertEqual(result['tables']['final_clipping_snapshots'][0]['content'], '기존 최종본')
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_missing_archive_does_not_create_database_or_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing' / 'old.sqlite3'
            self.assertFalse(inspect_legacy_archive(path)['db_exists'])
            self.assertFalse(path.parent.exists())
