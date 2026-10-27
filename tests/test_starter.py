"""First-clone restoration must preserve data and reject damaged bundles."""

import gzip
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from english_overlap.starter import restore_starter_database


class StarterDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.destination = self.root / "installed" / "vocab.db"
        original = self.root / "source.db"
        with closing(sqlite3.connect(original)) as connection, connection:
            connection.execute("CREATE TABLE words (word TEXT)")
            connection.execute("INSERT INTO words VALUES ('adventure')")
        self.raw = original.read_bytes()
        self.manifest = {"format_version": 1, "database_size": len(self.raw),
                         "database_sha256": hashlib.sha256(self.raw).hexdigest(), "parts": []}
        midpoint = len(self.raw) // 2
        for index, raw in enumerate((self.raw[:midpoint], self.raw[midpoint:])):
            name = f"part-{index}.gz"
            compressed = gzip.compress(raw)
            (self.bundle / name).write_bytes(compressed)
            self.manifest["parts"].append({"name": name, "sha256": hashlib.sha256(compressed).hexdigest()})
        self.write_manifest()

    def write_manifest(self):
        (self.bundle / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_restores_split_database_and_preserves_later_learning(self):
        self.assertTrue(restore_starter_database(self.destination, self.bundle))
        self.assertEqual(self.destination.read_bytes(), self.raw)
        with closing(sqlite3.connect(self.destination)) as connection, connection:
            connection.execute("INSERT INTO words VALUES ('progress')")
        self.assertFalse(restore_starter_database(self.destination, self.bundle))
        with closing(sqlite3.connect(self.destination)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM words").fetchone()[0], 2)

    def test_corrupt_part_leaves_no_partial_database(self):
        (self.bundle / "part-1.gz").write_bytes(b"damaged")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            restore_starter_database(self.destination, self.bundle)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.destination.parent.glob(".starter-*")), [])

    def test_missing_part_leaves_no_partial_database(self):
        (self.bundle / "part-1.gz").unlink()
        with self.assertRaises(FileNotFoundError):
            restore_starter_database(self.destination, self.bundle)
        self.assertFalse(self.destination.exists())

    def test_database_digest_is_verified(self):
        self.manifest["database_sha256"] = "0" * 64
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            restore_starter_database(self.destination, self.bundle)
        self.assertFalse(self.destination.exists())

    def test_missing_bundle_reports_how_to_recover(self):
        with self.assertRaisesRegex(FileNotFoundError, "Clone the complete repository"):
            restore_starter_database(self.destination, self.root / "missing")


if __name__ == "__main__":
    unittest.main()
