"""Restore the bundled SQLite snapshot on the first start after cloning."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path


def restore_starter_database(destination: Path, bundle: Path) -> bool:
    """Verify and restore the seed atomically, preserving an existing database."""
    if destination.exists():
        return False
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Starter database is missing: {manifest_path}. Clone the complete repository.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format_version") != 1 or not manifest.get("parts"):
        raise ValueError("Unsupported or empty starter database manifest")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".starter-", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output:
            for part in manifest["parts"]:
                name = part["name"]
                if Path(name).name != name or not name.endswith(".gz"):
                    raise ValueError("Invalid starter database part name")
                archive = bundle / name
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                if digest != part["sha256"]:
                    raise ValueError(f"Starter database checksum mismatch: {name}")
                with gzip.open(archive, "rb") as source:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        digest = hashlib.sha256()
        with temporary.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        if temporary.stat().st_size != manifest["database_size"] or digest.hexdigest() != manifest["database_sha256"]:
            raise ValueError("Restored starter database checksum mismatch")
        with closing(sqlite3.connect(temporary)) as connection:
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Restored starter database failed SQLite integrity check")
        # Publishing a hard link is atomic and cannot replace an existing DB.
        try:
            os.link(temporary, destination)
        except FileExistsError:
            return False
        return True
    finally:
        temporary.unlink(missing_ok=True)
