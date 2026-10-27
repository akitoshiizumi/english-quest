"""Package a consistent SQLite snapshot as small, ordinary Git files."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "dataset" / "vocab.db")
    parser.add_argument("--output", type=Path, default=ROOT / "dataset" / "starter")
    args = parser.parse_args()
    if (args.output / "manifest.json").exists():
        parser.error("Use a new output directory to avoid replacing a published bundle.")
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        snapshot = Path(temporary) / "vocab.db"
        with closing(sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
            from english_overlap.database import EMBEDDING_DIMENSIONS, compact_embedding_json, normalized_embedding_json
            cursor = target.execute("SELECT vocab_id,sense_id,model,input_version,vector_json FROM embeddings")
            while rows := cursor.fetchmany(64):
                target.executemany("UPDATE embeddings SET vector_json=? WHERE vocab_id=? AND sense_id=? AND model=? AND input_version=?",
                                   [(compact_embedding_json(row[4]), *row[:4]) for row in rows])
            cursor = target.execute("SELECT candidate_id,embedding_json FROM candidates WHERE embedding_json IS NOT NULL")
            while rows := cursor.fetchmany(64):
                target.executemany("UPDATE candidates SET embedding_json=? WHERE candidate_id=?",
                                   [(compact_embedding_json(row[1]), row[0]) for row in rows])
            cursor = target.execute("SELECT vocab_id,sense_id,model,input_version,vector_json FROM embeddings WHERE model LIKE 'text-embedding-3-%' AND dimensions> ?", (EMBEDDING_DIMENSIONS,))
            while rows := cursor.fetchmany(64):
                target.executemany("UPDATE embeddings SET dimensions=?,vector_json=? WHERE vocab_id=? AND sense_id=? AND model=? AND input_version=?",
                                   [(EMBEDDING_DIMENSIONS, normalized_embedding_json(row[4], EMBEDDING_DIMENSIONS), *row[:4]) for row in rows])
            cursor = target.execute("SELECT candidate_id,embedding_json FROM candidates WHERE embedding_model LIKE 'text-embedding-3-%' AND embedding_dimensions> ? AND embedding_json IS NOT NULL", (EMBEDDING_DIMENSIONS,))
            while rows := cursor.fetchmany(64):
                target.executemany("UPDATE candidates SET embedding_dimensions=?,embedding_json=? WHERE candidate_id=?",
                                   [(EMBEDDING_DIMENSIONS, normalized_embedding_json(row[1], EMBEDDING_DIMENSIONS), row[0]) for row in rows])
            target.execute("INSERT OR IGNORE INTO schema_migrations(version,applied_at_utc) VALUES (7,?)",
                           (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
            target.commit()
            target.execute("VACUUM")
            if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Source database failed integrity check")
            counts = {table: target.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                      for table in ("vocab", "materials")}
        manifest = {"format_version": 1, "database_size": snapshot.stat().st_size,
                    "counts": counts, "parts": []}
        digest = hashlib.sha256()
        with snapshot.open("rb") as source:
            for index, block in enumerate(iter(lambda: source.read(48 * 1024 * 1024), b"")):
                digest.update(block)
                name = f"vocab.db.part-{index:03d}.gz"
                compressed = gzip.compress(block, compresslevel=6, mtime=0)
                (args.output / name).write_bytes(compressed)
                manifest["parts"].append({"name": name, "sha256": hashlib.sha256(compressed).hexdigest()})
                print(f"Packaged {name}: {len(compressed):,} bytes", flush=True)
        manifest["database_sha256"] = digest.hexdigest()
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Complete: {counts}")


if __name__ == "__main__":
    main()
