"""SQLite persistence and reversible schema migrations for the learning app."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import tempfile
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class _ClosingConnection(sqlite3.Connection):
    """Make `with connect(...)` commit/rollback and release the file handle."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def database_path() -> Path:
    """Resolve the app DB lazily so tests can point it at an isolated file."""
    configured = os.environ.get("ENGLISH_OVERLAP_DB")
    return Path(configured).expanduser().resolve() if configured else ROOT / "dataset" / "vocab.db"


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path is not None else database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15, factory=_ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def backup_database(path: str | Path, destination: str | Path | None = None) -> Path:
    """Create a consistent SQLite backup; never replace an existing backup."""
    source = Path(path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if destination is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination_path = source.with_name(f"{source.stem}.backup-{stamp}.sqlite3")
    else:
        destination_path = Path(destination).resolve()
    if source == destination_path:
        raise ValueError("Backup destination must differ from the source database")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        raise FileExistsError(destination_path)

    fd, temporary_name = tempfile.mkstemp(prefix=".sqlite-backup-", suffix=".tmp", dir=destination_path.parent)
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(temporary_path)) as dst:
            src.backup(dst)
            result = dst.execute("PRAGMA quick_check").fetchone()[0]
            if result != "ok":
                raise sqlite3.DatabaseError(f"Backup integrity check failed: {result}")
        os.replace(temporary_path, destination_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination_path


def restore_database(backup_path: str | Path, destination: str | Path) -> None:
    """Restore a verified backup atomically, preserving a safety copy first."""
    backup = Path(backup_path).resolve()
    target = Path(destination).resolve()
    if backup == target or not backup.is_file():
        raise ValueError("A separate existing backup file is required")
    with closing(sqlite3.connect(backup)) as conn:
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("The selected backup is not a valid SQLite database")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup_database(target)
    fd, temporary_name = tempfile.mkstemp(prefix=".sqlite-restore-", suffix=".tmp", dir=target.parent)
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        with closing(sqlite3.connect(backup)) as src, closing(sqlite3.connect(temporary_path)) as dst:
            src.backup(dst)
            if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("Restored database failed its integrity check")
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)


def list_database_backups(path: str | Path | None = None) -> list[dict]:
    db_path = Path(path) if path is not None else database_path()
    if not db_path.parent.exists():
        return []
    backups = []
    for item in db_path.parent.glob(f"{db_path.stem}.backup-*.sqlite3"):
        try:
            stat = item.stat()
            backups.append({
                "name": item.name,
                "size_bytes": stat.st_size,
                "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
            })
        except OSError:
            continue
    return sorted(backups, key=lambda item: item["modified_at_utc"], reverse=True)


def database_status(path: str | Path | None = None) -> dict:
    db_path = Path(path) if path is not None else database_path()
    if not db_path.is_file():
        return {"exists": False, "path": str(db_path), "schema_version": 0, "size_bytes": 0,
                "integrity": "missing", "latest_backup": None}
    with closing(sqlite3.connect(db_path)) as conn:
        has_migrations = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        schema_version = conn.execute("SELECT coalesce(max(version),0) FROM schema_migrations").fetchone()[0] if has_migrations else 0
        integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
    backups = list_database_backups(db_path)
    return {"exists": True, "path": str(db_path), "schema_version": schema_version,
            "size_bytes": db_path.stat().st_size, "integrity": integrity,
            "latest_backup": backups[0] if backups else None}


def _create_legacy_vocab_if_missing(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS vocab (
        vocab_id TEXT PRIMARY KEY,
        english TEXT NOT NULL,
        japanese TEXT NOT NULL,
        mnemonic TEXT,
        tags TEXT,
        example_sentence TEXT,
        cefr_level TEXT,
        pos TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        genre_tags TEXT,
        sources TEXT,
        source_count INTEGER DEFAULT 1
    )""")


def _migration_1(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS senses (
        sense_id INTEGER PRIMARY KEY AUTOINCREMENT,
        vocab_id TEXT NOT NULL REFERENCES vocab(vocab_id) ON DELETE CASCADE,
        sense_index INTEGER NOT NULL DEFAULT 0,
        meaning TEXT NOT NULL,
        part_of_speech TEXT,
        example_sentence TEXT,
        source TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(vocab_id, sense_index)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_senses_vocab ON senses(vocab_id)")
    conn.execute("""INSERT OR IGNORE INTO senses(vocab_id, sense_index, meaning, part_of_speech, example_sentence)
        SELECT vocab_id, 0, japanese, pos, example_sentence
        FROM vocab WHERE trim(coalesce(japanese, '')) <> ''""")

    conn.execute("""CREATE TABLE IF NOT EXISTS categories (
        category_id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS vocabulary_categories (
        vocab_id TEXT NOT NULL REFERENCES vocab(vocab_id) ON DELETE CASCADE,
        category_id TEXT NOT NULL REFERENCES categories(category_id) ON DELETE CASCADE,
        PRIMARY KEY(vocab_id, category_id)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vocabulary_categories_category ON vocabulary_categories(category_id)")
    conn.execute("""INSERT OR IGNORE INTO categories(category_id, name)
        SELECT DISTINCT trim(genre_tags), trim(genre_tags)
        FROM vocab WHERE trim(coalesce(genre_tags, '')) <> ''""")
    conn.execute("""INSERT OR IGNORE INTO vocabulary_categories(vocab_id, category_id)
        SELECT vocab_id, trim(genre_tags) FROM vocab WHERE trim(coalesce(genre_tags, '')) <> ''""")


def _migration_2(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS study_sessions (
        session_id TEXT PRIMARY KEY,
        session_type TEXT NOT NULL CHECK(session_type IN ('vocabulary', 'overlap', 'mixed')),
        started_at_utc TEXT NOT NULL,
        ended_at_utc TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS study_events (
        event_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES study_sessions(session_id) ON DELETE CASCADE,
        event_type TEXT NOT NULL CHECK(event_type IN ('vocabulary_answer', 'overlap_activity')),
        vocab_id TEXT REFERENCES vocab(vocab_id) ON DELETE SET NULL,
        sense_id INTEGER REFERENCES senses(sense_id) ON DELETE SET NULL,
        direction TEXT CHECK(direction IN ('en_to_ja', 'ja_to_en')),
        rating TEXT CHECK(rating IN ('again', 'known')),
        duration_seconds REAL NOT NULL DEFAULT 0 CHECK(duration_seconds >= 0),
        occurred_at_utc TEXT NOT NULL,
        idempotency_key TEXT UNIQUE,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        CHECK(event_type <> 'vocabulary_answer' OR (vocab_id IS NOT NULL AND direction IS NOT NULL AND rating IS NOT NULL))
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_study_events_time ON study_events(occurred_at_utc)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_study_events_vocab ON study_events(vocab_id, direction)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_study_events_session ON study_events(session_id)")

    conn.execute("""CREATE TABLE IF NOT EXISTS materials (
        material_id TEXT PRIMARY KEY,
        material_type TEXT NOT NULL CHECK(material_type IN ('overlap', 'generated_text', 'external_text')),
        title TEXT NOT NULL,
        text_content TEXT NOT NULL DEFAULT '',
        json_path TEXT UNIQUE,
        audio_path TEXT,
        difficulty_level TEXT,
        source TEXT,
        status TEXT NOT NULL DEFAULT 'ready' CHECK(status IN ('draft', 'ready', 'archived')),
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at_utc TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS material_vocabulary (
        material_id TEXT NOT NULL,
        vocab_id TEXT NOT NULL REFERENCES vocab(vocab_id) ON DELETE CASCADE,
        sense_id INTEGER REFERENCES senses(sense_id) ON DELETE SET NULL,
        usage_text TEXT,
        usage_start INTEGER,
        usage_end INTEGER,
        PRIMARY KEY(material_id, vocab_id, sense_id)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_material_vocabulary_vocab ON material_vocabulary(vocab_id)")


def _migration_3(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE vocab ADD COLUMN archived_at_utc TEXT")
    conn.execute("ALTER TABLE senses ADD COLUMN difficulty_level TEXT")
    conn.execute("ALTER TABLE senses ADD COLUMN difficulty_evidence TEXT")
    conn.execute("ALTER TABLE senses ADD COLUMN difficulty_model TEXT")
    conn.execute("ALTER TABLE senses ADD COLUMN difficulty_assessed_at_utc TEXT")
    conn.execute("ALTER TABLE senses ADD COLUMN difficulty_manual INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE senses ADD COLUMN difficulty_version TEXT")
    conn.execute("""CREATE TABLE IF NOT EXISTS app_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS api_jobs (
        job_id TEXT PRIMARY KEY,
        job_type TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('queued','running','paused','failed','completed')),
        payload_json TEXT NOT NULL,
        result_json TEXT NOT NULL DEFAULT '{}',
        total_items INTEGER NOT NULL DEFAULT 0,
        completed_items INTEGER NOT NULL DEFAULT 0,
        model TEXT,
        error TEXT,
        created_at_utc TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS api_usage (
        usage_id TEXT PRIMARY KEY,
        job_id TEXT REFERENCES api_jobs(job_id) ON DELETE SET NULL,
        operation TEXT NOT NULL,
        model TEXT NOT NULL,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        audio_seconds REAL NOT NULL DEFAULT 0,
        estimated_usd REAL NOT NULL DEFAULT 0,
        rate_version TEXT NOT NULL,
        created_at_utc TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS import_batches (
        batch_id TEXT PRIMARY KEY,
        source_type TEXT NOT NULL,
        source_text TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('draft','processing','ready','completed','failed')),
        created_at_utc TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS candidates (
        candidate_id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL REFERENCES import_batches(batch_id) ON DELETE CASCADE,
        english TEXT NOT NULL,
        meaning TEXT NOT NULL DEFAULT '',
        part_of_speech TEXT,
        source TEXT,
        selected INTEGER NOT NULL DEFAULT 0,
        excluded_reason TEXT,
        matched_vocab_id TEXT REFERENCES vocab(vocab_id) ON DELETE SET NULL,
        similarity REAL,
        embedding_model TEXT,
        embedding_dimensions INTEGER,
        input_hash TEXT,
        created_vocab_id TEXT REFERENCES vocab(vocab_id) ON DELETE SET NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_batch ON candidates(batch_id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS embeddings (
        vocab_id TEXT NOT NULL REFERENCES vocab(vocab_id) ON DELETE CASCADE,
        sense_id INTEGER REFERENCES senses(sense_id) ON DELETE CASCADE,
        model TEXT NOT NULL,
        dimensions INTEGER NOT NULL,
        input_version TEXT NOT NULL,
        input_hash TEXT NOT NULL,
        vector_json TEXT NOT NULL,
        created_at_utc TEXT NOT NULL,
        PRIMARY KEY(vocab_id, sense_id, model, input_version)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_hash ON embeddings(input_hash, model, dimensions)")


def _migration_4(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE candidates ADD COLUMN embedding_json TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_api_jobs_status ON api_jobs(status,updated_at_utc)")


def _migration_5(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE materials ADD COLUMN content_json TEXT NOT NULL DEFAULT '{}'")
    conn.execute("""CREATE TABLE material_legacy_imports (
        source_name TEXT PRIMARY KEY,
        source_sha256 TEXT NOT NULL,
        material_id TEXT NOT NULL REFERENCES materials(material_id) ON DELETE CASCADE,
        imported_at_utc TEXT NOT NULL
    )""")
    conn.execute("CREATE INDEX idx_material_legacy_imports_material ON material_legacy_imports(material_id)")
    content_keys=('summary','summary_model','summary_prompt_version','summary_generated_at_utc','voice','style','model',
                  'word_count','character_count','audio_seconds','cost','spoken_text','blocks','transcript','words','version')
    for row in conn.execute('SELECT material_id,metadata_json FROM materials').fetchall():
        try:metadata=json.loads(row['metadata_json'] or '{}')
        except (TypeError,json.JSONDecodeError):continue
        if not isinstance(metadata,dict):continue
        content={key:metadata.pop(key) for key in content_keys if key in metadata}
        if content:
            conn.execute('UPDATE materials SET metadata_json=?,content_json=? WHERE material_id=?',
                         (json.dumps(metadata,ensure_ascii=False),json.dumps(content,ensure_ascii=False),row['material_id']))


MIGRATIONS = ((1, _migration_1), (2, _migration_2), (3, _migration_3), (4, _migration_4), (5, _migration_5))


def migrate_database(path: str | Path | None = None) -> tuple[int, Path | None]:
    """Back up an existing database, then apply each unapplied migration atomically."""
    db_path = Path(path) if path is not None else database_path()
    if path is None and not os.environ.get("ENGLISH_OVERLAP_DB") and os.environ.get("ENGLISH_OVERLAP_DATA_ROLE", "production") != "test":
        from .starter import restore_starter_database
        if not db_path.exists():
            print("Preparing the bundled vocabulary and materials (first start only)...")
            restore_starter_database(db_path, ROOT / "dataset" / "starter")
    existed = db_path.is_file()
    needs_migration = True
    if existed:
        with closing(sqlite3.connect(db_path)) as inspection:
            has_migrations = inspection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            current = inspection.execute("SELECT coalesce(max(version), 0) FROM schema_migrations").fetchone()[0] if has_migrations else 0
            needs_migration = current < MIGRATIONS[-1][0]
    backup_path = backup_database(db_path) if existed and needs_migration else None
    conn = connect(db_path)
    try:
        _create_legacy_vocab_if_missing(conn)
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at_utc TEXT NOT NULL
        )""")
        current = conn.execute("SELECT coalesce(max(version), 0) FROM schema_migrations").fetchone()[0]
        for version, apply in MIGRATIONS:
            if version <= current:
                continue
            try:
                conn.execute("BEGIN IMMEDIATE")
                apply(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at_utc) VALUES (?, ?)",
                    (version, datetime.now(timezone.utc).isoformat(timespec="seconds")),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0], backup_path
    finally:
        conn.close()


def create_study_session(session_type: str = "vocabulary", *, path: str | Path | None = None) -> str:
    session_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO study_sessions(session_id, session_type, started_at_utc) VALUES (?, ?, ?)",
            (session_id, session_type, now),
        )
    return session_id


def record_vocabulary_answer(
    *, session_id: str, vocab_id: str, sense_id: int | None, direction: str,
    rating: str, duration_seconds: float, idempotency_key: str,
    path: str | Path | None = None,
) -> bool:
    """Record an answer once; return False for a duplicate idempotency key."""
    event_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    with connect(path) as conn:
        cur = conn.execute("""INSERT OR IGNORE INTO study_events
            (event_id, session_id, event_type, vocab_id, sense_id, direction, rating,
             duration_seconds, occurred_at_utc, idempotency_key)
            VALUES (?, ?, 'vocabulary_answer', ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, session_id, vocab_id, sense_id, direction, rating,
             duration_seconds, now, idempotency_key))
        return cur.rowcount == 1


def list_vocabulary(*, query: str = "", category: str | None = None, direction: str = "en_to_ja",
                    limit: int = 100, include_archived: bool = False, path: str | Path | None = None) -> list[dict]:
    limit = max(1, min(int(limit), 500))
    clauses = ["(v.archived_at_utc IS NULL OR ? = 1)"]
    params: list[object] = [int(include_archived)]
    if query.strip():
        clauses.append("(v.english LIKE ? OR v.japanese LIKE ? OR EXISTS (SELECT 1 FROM senses s WHERE s.vocab_id=v.vocab_id AND s.meaning LIKE ?))")
        pattern = f"%{query.strip()}%"
        params.extend((pattern, pattern, pattern))
    if category:
        clauses.append("EXISTS (SELECT 1 FROM vocabulary_categories vc WHERE vc.vocab_id=v.vocab_id AND vc.category_id=?)")
        params.append(category)
    params.append(limit)
    with connect(path) as conn:
        rows = conn.execute(f"""SELECT v.vocab_id,v.english,v.japanese,v.pos,v.tags,v.sources,v.genre_tags,
            v.archived_at_utc, s.sense_id,s.meaning,s.part_of_speech,s.example_sentence,s.difficulty_level,
            EXISTS(SELECT 1 FROM study_events e WHERE e.vocab_id=v.vocab_id AND e.direction=?) AS studied
            FROM vocab v LEFT JOIN senses s ON s.vocab_id=v.vocab_id
            WHERE {' AND '.join(clauses)} ORDER BY v.english COLLATE NOCASE,v.vocab_id,s.sense_index LIMIT ?""",
            (direction, *params)).fetchall()
    return [dict(row) for row in rows]


def list_vocabulary_page(*, query: str = '', direction: str = 'en_to_ja', include_archived: bool = False,
                         page: int = 1, page_size: int = 50, sort_by: str = 'english', sort_direction: str = 'asc',
                         path: str | Path | None = None) -> dict:
    """Return a stable, allowlisted vocabulary page for the management table."""
    if page < 1:
        raise ValueError('page must be at least 1')
    if not 1 <= page_size <= 50:
        raise ValueError('page_size must be 1..50')
    sort_columns={'english':'v.english','japanese':'s.meaning','part_of_speech':'COALESCE(s.part_of_speech,v.pos)','tags':"COALESCE(NULLIF(v.tags,''),v.genre_tags)",'difficulty':'s.difficulty_level'}
    if sort_by not in sort_columns:
        raise ValueError('Unsupported vocabulary sort column')
    if sort_direction not in ('asc','desc'):
        raise ValueError('sort_direction must be asc or desc')
    clauses=['(v.archived_at_utc IS NULL OR ?=1)']
    params: list[object]=[int(include_archived)]
    if query.strip():
        pattern=f"%{query.strip()}%"
        clauses.append('(v.english LIKE ? OR v.japanese LIKE ? OR s.meaning LIKE ?)')
        params.extend((pattern,pattern,pattern))
    where=' AND '.join(clauses)
    order=f"{sort_columns[sort_by]} COLLATE NOCASE {sort_direction.upper()}, v.vocab_id COLLATE NOCASE ASC, s.sense_index ASC"
    with connect(path) as conn:
        total=conn.execute(f'SELECT count(*) FROM vocab v LEFT JOIN senses s ON s.vocab_id=v.vocab_id WHERE {where}',params).fetchone()[0]
        pages=(total+page_size-1)//page_size
        page=min(page,max(1,pages))
        rows=conn.execute(f"""SELECT v.vocab_id,v.english,v.japanese,v.pos,v.tags,v.sources,v.genre_tags,
            v.archived_at_utc,s.sense_id,s.meaning,s.part_of_speech,s.example_sentence,s.difficulty_level,
            EXISTS(SELECT 1 FROM study_events e WHERE e.vocab_id=v.vocab_id AND e.direction=?) AS studied
            FROM vocab v LEFT JOIN senses s ON s.vocab_id=v.vocab_id WHERE {where}
            ORDER BY {order} LIMIT ? OFFSET ?""",(direction,*params,page_size,(page-1)*page_size)).fetchall()
    return {'items':[dict(row) for row in rows],'total':total,'page':page,'page_size':page_size,'pages':pages}


def weak_vocabulary(*, direction: str, category: str | None = None, limit: int = 50,
                    include_unstudied: bool = True, mastery_status: str = 'all',
                    recent_attempts: int | None = None, max_recent_accuracy: float | None = None,
                    include_insufficient_history: bool = False, path: str | Path | None = None) -> list[dict]:
    from .vocabulary import select_weak_vocabulary
    if direction not in ('en_to_ja','ja_to_en'):
        raise ValueError('Unsupported learning direction')
    if recent_attempts is not None and not 1 <= recent_attempts <= 100:
        raise ValueError('recent_attempts must be 1..100')
    if max_recent_accuracy is not None and not 0 <= max_recent_accuracy <= 100:
        raise ValueError('max_recent_accuracy must be 0..100')
    if max_recent_accuracy is not None and recent_attempts is None:
        raise ValueError('recent_attempts is required for recent accuracy filtering')
    with connect(path) as conn:
        sql="""SELECT v.vocab_id,v.english,v.pos,s.sense_id,s.meaning,s.part_of_speech,s.difficulty_level
            FROM vocab v JOIN senses s ON s.vocab_id=v.vocab_id
            WHERE v.archived_at_utc IS NULL AND trim(s.meaning)<>''"""
        params=[]
        if category:
            sql += " AND EXISTS (SELECT 1 FROM vocabulary_categories vc WHERE vc.vocab_id=v.vocab_id AND vc.category_id=?)"
            params.append(category)
        sql += ' ORDER BY v.vocab_id,s.sense_index'
        items=[dict(row) for row in conn.execute(sql,params)]
        ids=[item['vocab_id'] for item in items]
        events_by_vocab={vocab_id:[] for vocab_id in ids}
        for offset in range(0,len(ids),500):
            batch=ids[offset:offset+500]
            placeholders=','.join('?' for _ in batch)
            for row in conn.execute(f"SELECT vocab_id,direction,rating,occurred_at_utc FROM study_events WHERE event_type='vocabulary_answer' AND vocab_id IN ({placeholders}) ORDER BY occurred_at_utc,rowid",batch):
                events_by_vocab[row['vocab_id']].append(dict(row))
    for item in items: item['events']=events_by_vocab[item['vocab_id']]
    # A history filter must see studied words even when normal study-set candidates
    # are configured to include only unstudied vocabulary.
    ranked=select_weak_vocabulary(items,direction,len(items),include_unstudied or recent_attempts is not None)
    if mastery_status not in ('all','unlearned','review','known'):
        raise ValueError('Unsupported mastery status')
    def matches(item):
        events=[event for event in item['events'] if event.get('direction')==direction]
        known=sum(event.get('rating')=='known' for event in events)
        if mastery_status=='unlearned' and events:return False
        if mastery_status=='review' and (not events or known == len(events)):return False
        if mastery_status=='known' and (not events or known != len(events)):return False
        if recent_attempts is not None:
            minimum=0 if include_insufficient_history else recent_attempts
            if len(events)<minimum:return False
            if not events:
                return include_insufficient_history
            recent=events[-recent_attempts:]
            if max_recent_accuracy is not None and sum(event.get('rating')=='known' for event in recent)*100/len(recent)>max_recent_accuracy:return False
        return True
    # Apply eligibility before the requested count so later matches are not hidden.
    return [item for item in ranked if matches(item)][:max(0,limit)]


def _due_review_schedule(conn: sqlite3.Connection, *, local_today, direction: str | None = None) -> dict[tuple[str, str], dict]:
    """Calculate the simple-interval-v1 due date from each vocabulary/direction's latest answer."""
    sql = """SELECT vocab_id,sense_id,direction,rating,occurred_at_utc FROM (
        SELECT vocab_id,sense_id,direction,rating,occurred_at_utc,
        ROW_NUMBER() OVER(PARTITION BY vocab_id,direction ORDER BY occurred_at_utc DESC,rowid DESC) AS rank
        FROM study_events WHERE event_type='vocabulary_answer'"""
    params=[]
    if direction is not None:
        sql += ' AND direction=?'
        params.append(direction)
    sql += ') WHERE rank=1'
    tokyo=timezone(timedelta(hours=9),'Asia/Tokyo')
    intervals={'again':1,'known':3}
    due={}
    for row in conn.execute(sql,params):
        learned_date=datetime.fromisoformat(row['occurred_at_utc']).astimezone(tokyo).date()
        due_date=learned_date+timedelta(days=intervals[row['rating']])
        if due_date<=local_today:
            item=dict(row)
            item.update({'due_date':due_date.isoformat(),'overdue_days':(local_today-due_date).days,'algorithm_version':'simple-interval-v1'})
            due[(row['vocab_id'],row['direction'])]=item
    return due


def study_set_history_summary(*, direction: str, category: str | None = None,
                              path: str | Path | None = None) -> dict:
    """Report directional history coverage without treating legacy rows as directional."""
    if direction not in ('en_to_ja','ja_to_en'):
        raise ValueError('Unsupported learning direction')
    with connect(path) as conn:
        clauses=["e.event_type='vocabulary_answer'",'e.direction=?','v.archived_at_utc IS NULL']
        params=[direction]
        if category:
            clauses.append('EXISTS (SELECT 1 FROM vocabulary_categories vc WHERE vc.vocab_id=v.vocab_id AND vc.category_id=?)')
            params.append(category)
        answer_count=conn.execute('SELECT count(DISTINCT e.vocab_id) FROM study_events e JOIN vocab v ON v.vocab_id=e.vocab_id WHERE '+' AND '.join(clauses),params).fetchone()[0]
        has_history=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='history'").fetchone()
        legacy_count=int(conn.execute('SELECT count(*) FROM history').fetchone()[0]) if has_history else 0
    return {'direction':direction,'category':category,'directional_answer_vocabulary_count':int(answer_count),
            'legacy_history_count_excluded':legacy_count}


def vocabulary_by_ids(vocab_ids: list[str], *, path: str | Path | None = None) -> list[dict]:
    if not vocab_ids:return []
    ids=list(dict.fromkeys(vocab_ids))[:500]
    with connect(path) as conn:
        return [dict(row) for row in conn.execute("SELECT v.vocab_id,v.english,s.sense_id,s.meaning,s.difficulty_level FROM vocab v JOIN senses s ON s.vocab_id=v.vocab_id WHERE v.archived_at_utc IS NULL AND v.vocab_id IN (%s) ORDER BY v.english COLLATE NOCASE,s.sense_index" % ','.join('?' for _ in ids),ids)]


def update_vocabulary(*, vocab_id: str, english: str, meaning: str, part_of_speech: str = "",
                      tags: str = "", sources: str = "", path: str | Path | None = None) -> None:
    if not vocab_id or not english.strip() or not meaning.strip():
        raise ValueError("English headword and Japanese meaning are required")
    with connect(path) as conn:
        cur = conn.execute("UPDATE vocab SET english=?,japanese=?,pos=?,tags=?,sources=?,updated_at=CURRENT_TIMESTAMP WHERE vocab_id=?",
                           (english.strip(), meaning.strip(), part_of_speech.strip(), tags.strip(), sources.strip(), vocab_id))
        if cur.rowcount != 1:
            raise LookupError("Vocabulary item not found")
        sense = conn.execute("SELECT sense_id FROM senses WHERE vocab_id=? ORDER BY sense_index LIMIT 1", (vocab_id,)).fetchone()
        if sense:
            conn.execute("UPDATE senses SET meaning=?,part_of_speech=? WHERE sense_id=?", (meaning.strip(), part_of_speech.strip(), sense['sense_id']))
        else:
            conn.execute("INSERT INTO senses(vocab_id,sense_index,meaning,part_of_speech) VALUES (?,0,?,?)",
                         (vocab_id, meaning.strip(), part_of_speech.strip()))


def set_vocabulary_archived(vocab_id: str, archived: bool, *, path: str | Path | None = None) -> None:
    with connect(path) as conn:
        cur = conn.execute("UPDATE vocab SET archived_at_utc=? WHERE vocab_id=?",
                           (datetime.now(timezone.utc).isoformat(timespec='seconds') if archived else None, vocab_id))
        if cur.rowcount != 1:
            raise LookupError("Vocabulary item not found")


def get_setting(key: str, default=None, *, path: str | Path | None = None):
    with connect(path) as conn:
        row = conn.execute("SELECT setting_value FROM app_settings WHERE setting_key=?", (key,)).fetchone()
    return json.loads(row['setting_value']) if row else default


def set_setting(key: str, value, *, path: str | Path | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with connect(path) as conn:
        conn.execute("INSERT INTO app_settings(setting_key,setting_value,updated_at_utc) VALUES (?,?,?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at_utc=excluded.updated_at_utc",
                     (key, json.dumps(value, ensure_ascii=False), now))


def set_learning_goals(*, overlap_hours: float | None, vocabulary_count: int | None,
                       path: str | Path | None = None) -> None:
    if overlap_hours is not None:
        if isinstance(overlap_hours, bool) or not isinstance(overlap_hours, (int, float)) or not math.isfinite(overlap_hours) or not 0.1 <= overlap_hours <= 10000:
            raise ValueError('オーバーラッピング目標は0.1〜10000時間で指定してください。')
        overlap_hours = float(overlap_hours)
    if vocabulary_count is not None:
        if isinstance(vocabulary_count, bool) or not isinstance(vocabulary_count, int) or not 1 <= vocabulary_count <= 1000000:
            raise ValueError('語彙数の目標は1〜1000000語の整数で指定してください。')
    set_setting('learning_goals', {'overlap_hours': overlap_hours, 'vocabulary_count': vocabulary_count}, path=path)


def learning_goals_status(*, path: str | Path | None = None) -> dict:
    goals = get_setting('learning_goals', {'overlap_hours': None, 'vocabulary_count': None}, path=path)
    with connect(path) as conn:
        overlap_seconds = float(conn.execute("SELECT coalesce(sum(duration_seconds),0) FROM study_events WHERE event_type='overlap_activity'").fetchone()[0])
        vocabulary_count = int(conn.execute("SELECT count(DISTINCT vocab_id) FROM study_events WHERE event_type='vocabulary_answer' AND vocab_id IS NOT NULL").fetchone()[0])
    return {'goals': goals, 'overlap_seconds': overlap_seconds, 'learned_vocabulary_count': vocabulary_count}


def fetch_vocabulary_question(direction: str, *, category: str | None = None, exclude: set[str] | None = None,
                              include_unstudied: bool = True, mastery_status: str = 'all', difficulty: str | None = None,
                              recent_attempts: int | None = None, max_recent_accuracy: float | None = None,
                              include_insufficient_history: bool = False, all_attempts_incorrect: bool = False,
                              last_attempt_incorrect: bool = False,
                              path: str | Path | None = None) -> dict | None:
    items=list_practice_questions(direction, category=category, exclude=exclude,
        include_unstudied=include_unstudied, mastery_status=mastery_status, difficulty=difficulty,
        recent_attempts=recent_attempts, max_recent_accuracy=max_recent_accuracy,
        include_insufficient_history=include_insufficient_history,
        all_attempts_incorrect=all_attempts_incorrect, last_attempt_incorrect=last_attempt_incorrect, limit=1, path=path)
    return items[0] if items else None


def list_practice_questions(direction: str, *, category: str | None = None, exclude: set[str] | None = None,
                            include_unstudied: bool = True, mastery_status: str = 'all', difficulty: str | None = None,
                            recent_attempts: int | None = None, max_recent_accuracy: float | None = None,
                            include_insufficient_history: bool = False, all_attempts_incorrect: bool = False,
                            last_attempt_incorrect: bool = False, due_only: bool = False, as_of: datetime | None = None,
                            limit: int = 50, path: str | Path | None = None) -> list[dict]:
    if not 1 <= limit <= 1000:
        raise ValueError('limit must be 1..1000')
    if direction not in ('en_to_ja', 'ja_to_en'):
        raise ValueError('Unsupported learning direction')
    excluded = sorted(exclude or ())
    exclusion_sql = ''
    params: list[object] = []
    if excluded:
        exclusion_sql = f" AND v.vocab_id NOT IN ({','.join('?' for _ in excluded)})"
        params.extend(excluded)
    category_sql = ''
    if category:
        category_sql = " AND EXISTS (SELECT 1 FROM vocabulary_categories vc WHERE vc.vocab_id=v.vocab_id AND vc.category_id=?)"
        params.append(category)
    if difficulty:
        category_sql += ' AND s.difficulty_level=?'
        params.append(difficulty)
    if recent_attempts is not None and not due_only:
        if not 1 <= recent_attempts <= 100:
            raise ValueError('recent_attempts must be 1..100')
        recent = "SELECT rating FROM study_events e WHERE e.event_type='vocabulary_answer' AND e.vocab_id=v.vocab_id AND e.direction=? ORDER BY e.occurred_at_utc DESC,e.rowid DESC LIMIT ?"
        min_history = 1 if include_insufficient_history else recent_attempts
        category_sql += f" AND (SELECT COUNT(*) FROM ({recent}))>=?"
        params.extend((direction, recent_attempts, min_history))
        if max_recent_accuracy is not None:
            if not 0 <= max_recent_accuracy <= 100:
                raise ValueError('max_recent_accuracy must be 0..100')
            category_sql += f" AND (SELECT AVG(CASE WHEN rating='known' THEN 100.0 ELSE 0.0 END) FROM ({recent}))<=?"
            params.extend((direction, recent_attempts, max_recent_accuracy))
    elif max_recent_accuracy is not None and not due_only:
        raise ValueError('recent_attempts is required for recent accuracy filtering')
    if all_attempts_incorrect and not due_only:
        category_sql += " AND EXISTS(SELECT 1 FROM study_events e WHERE e.event_type='vocabulary_answer' AND e.vocab_id=v.vocab_id AND e.direction=?) AND NOT EXISTS(SELECT 1 FROM study_events e WHERE e.event_type='vocabulary_answer' AND e.vocab_id=v.vocab_id AND e.direction=? AND e.rating<>'again')"
        params.extend((direction, direction))
    if last_attempt_incorrect and not due_only:
        category_sql += " AND (SELECT e.rating FROM study_events e WHERE e.event_type='vocabulary_answer' AND e.vocab_id=v.vocab_id AND e.direction=? ORDER BY e.occurred_at_utc DESC,e.rowid DESC LIMIT 1)='again'"
        params.append(direction)
    if mastery_status not in ('all','unlearned','review','known'):
        raise ValueError('Unsupported mastery status')
    has_events = "EXISTS(SELECT 1 FROM study_events e WHERE e.vocab_id=v.vocab_id AND e.direction=?)"
    if not due_only and not include_unstudied:
        category_sql += f' AND {has_events}'
        params.append(direction)
    if not due_only and mastery_status == 'unlearned':
        category_sql += f' AND NOT {has_events}'
        params.append(direction)
    elif not due_only and mastery_status == 'review':
        category_sql += f" AND {has_events} AND EXISTS(SELECT 1 FROM study_events e WHERE e.vocab_id=v.vocab_id AND e.direction=? AND e.rating='again')"
        params.extend((direction,direction))
    elif not due_only and mastery_status == 'known':
        category_sql += f" AND {has_events} AND NOT EXISTS(SELECT 1 FROM study_events e WHERE e.vocab_id=v.vocab_id AND e.direction=? AND e.rating='again')"
        params.extend((direction,direction))
    with connect(path) as conn:
        tokyo=timezone(timedelta(hours=9),'Asia/Tokyo')
        local_today=(as_of or datetime.now(timezone.utc)).astimezone(tokyo).date()
        due_schedule=_due_review_schedule(conn,local_today=local_today,direction=direction) if due_only else {}
        rows = conn.execute(f"""SELECT v.vocab_id,v.english,v.pos,s.sense_id,s.meaning,s.part_of_speech
            FROM vocab v JOIN senses s ON s.vocab_id=v.vocab_id
            WHERE v.archived_at_utc IS NULL AND trim(s.meaning)<>'' {exclusion_sql} {category_sql}
            ORDER BY CASE
              WHEN NOT EXISTS(SELECT 1 FROM study_events e WHERE e.vocab_id=v.vocab_id AND e.direction=?) THEN 1
              WHEN (SELECT e.rating FROM study_events e WHERE e.vocab_id=v.vocab_id AND e.direction=? ORDER BY e.occurred_at_utc DESC,e.rowid DESC LIMIT 1)='again' THEN 0
              ELSE 2 END,
              v.vocab_id,s.sense_index""", (*params, direction, direction)).fetchall()
        if due_only:
            due_by_vocab={vocab_id:item for (vocab_id,_),item in due_schedule.items()}
            rows=[row for row in rows if row['vocab_id'] in due_by_vocab]
            rows.sort(key=lambda row:(due_by_vocab[row['vocab_id']]['due_date'],row['vocab_id']))
        selected=[]
        seen=set()
        for row in rows:
            if row['vocab_id'] in seen:
                continue
            seen.add(row['vocab_id'])
            selected.append(dict(row))
            if len(selected)>=limit:
                break
        if selected:
            ids=[item['vocab_id'] for item in selected]
            history={vocab_id:[] for vocab_id in ids}
            for offset in range(0,len(ids),500):
                batch=ids[offset:offset+500]
                placeholders=','.join('?' for _ in batch)
                for event in conn.execute(f"""SELECT vocab_id,rating FROM study_events
                    WHERE event_type='vocabulary_answer' AND direction=? AND vocab_id IN ({placeholders})
                    ORDER BY occurred_at_utc,rowid""",(direction,*batch)):
                    history[event['vocab_id']].append(event['rating'])
            for item in selected:
                item['history']=history[item['vocab_id']]
    return selected


def vocabulary_categories(*, path: str | Path | None = None) -> list[dict]:
    with connect(path) as conn:
        return [dict(row) for row in conn.execute("SELECT category_id,name FROM categories ORDER BY name COLLATE NOCASE")]


def record_overlap_activity(*, session_id: str, material_id: str, duration_seconds: float,
                            idempotency_key: str, path: str | Path | None = None) -> bool:
    if duration_seconds < 0:
        raise ValueError('Duration cannot be negative')
    event_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with connect(path) as conn:
        cur = conn.execute("""INSERT OR IGNORE INTO study_events
            (event_id,session_id,event_type,duration_seconds,occurred_at_utc,idempotency_key,metadata_json)
            VALUES (?,?,'overlap_activity',?,?,?,?)""",
            (event_id, session_id, duration_seconds, now, idempotency_key, json.dumps({'material_id': material_id})))
        return cur.rowcount == 1


def create_api_job(job_type: str, payload: dict, total_items: int, model: str | None = None,
                   *, path: str | Path | None = None) -> str:
    job_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with connect(path) as conn:
        conn.execute("INSERT INTO api_jobs(job_id,job_type,status,payload_json,total_items,model,created_at_utc,updated_at_utc) VALUES (?,?,'queued',?,?,?,?,?)",
                     (job_id, job_type, json.dumps(payload, ensure_ascii=False), max(0, int(total_items)), model, now, now))
    return job_id


def update_api_job(job_id: str, *, status: str, completed_items: int | None = None,
                   result: dict | None = None, error: str | None = None, path: str | Path | None = None) -> None:
    if status not in ('queued', 'running', 'paused', 'failed', 'completed'):
        raise ValueError('Invalid job status')
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with connect(path) as conn:
        conn.execute("""UPDATE api_jobs SET status=?,completed_items=coalesce(?,completed_items),
            result_json=coalesce(?,result_json),error=?,updated_at_utc=? WHERE job_id=?""",
            (status, completed_items, json.dumps(result, ensure_ascii=False) if result is not None else None,
             error, now, job_id))


def get_api_job(job_id: str, *, path: str | Path | None = None) -> dict | None:
    with connect(path) as conn:
        row=conn.execute('SELECT * FROM api_jobs WHERE job_id=?',(job_id,)).fetchone()
    if not row:return None
    item=dict(row);item['payload']=json.loads(item.pop('payload_json'));item['result']=json.loads(item.pop('result_json'))
    return item


def latest_api_job(job_type: str, *, path: str | Path | None = None) -> dict | None:
    with connect(path) as conn:
        row=conn.execute('SELECT job_id FROM api_jobs WHERE job_type=? ORDER BY created_at_utc DESC LIMIT 1',(job_type,)).fetchone()
    return get_api_job(row['job_id'],path=path) if row else None


def api_usage_spent_today(operation: str, *, path: str | Path | None = None, now: datetime | None = None) -> float:
    tokyo=timezone(timedelta(hours=9),'Asia/Tokyo')
    today=(now or datetime.now(timezone.utc)).astimezone(tokyo).date()
    with connect(path) as conn:
        rows=conn.execute('SELECT estimated_usd,created_at_utc FROM api_usage WHERE operation=?',(operation,)).fetchall()
    return sum(float(row['estimated_usd'] or 0) for row in rows
               if datetime.fromisoformat(row['created_at_utc']).astimezone(tokyo).date()==today)


def senses_for_difficulty(sense_ids: list[int] | None = None, *, limit: int = 100, path: str | Path | None = None) -> list[dict]:
    with connect(path) as conn:
        if sense_ids:
            ids=list(dict.fromkeys(int(x) for x in sense_ids))[:100]
            rows=conn.execute("SELECT s.sense_id,s.vocab_id,v.english,s.meaning,s.difficulty_manual,s.difficulty_level FROM senses s JOIN vocab v ON v.vocab_id=s.vocab_id WHERE s.sense_id IN (%s) AND v.archived_at_utc IS NULL ORDER BY v.english COLLATE NOCASE" % ','.join('?' for _ in ids),ids).fetchall() if ids else []
        else:
            rows=conn.execute("SELECT s.sense_id,s.vocab_id,v.english,s.meaning,s.difficulty_manual,s.difficulty_level FROM senses s JOIN vocab v ON v.vocab_id=s.vocab_id WHERE v.archived_at_utc IS NULL AND s.difficulty_level IS NULL AND s.difficulty_manual=0 AND trim(s.meaning)<>'' ORDER BY v.vocab_id,s.sense_index LIMIT ?",(max(1,min(int(limit),100)),)).fetchall()
    return [dict(row) for row in rows]


def count_pending_difficulty(*, path: str | Path | None = None) -> int:
    with connect(path) as conn:
        return int(conn.execute("SELECT count(*) FROM senses s JOIN vocab v ON v.vocab_id=s.vocab_id WHERE v.archived_at_utc IS NULL AND s.difficulty_level IS NULL AND s.difficulty_manual=0 AND trim(s.meaning)<>''").fetchone()[0])


def add_api_usage(*, operation: str, model: str, input_tokens: int = 0, output_tokens: int = 0,
                  audio_seconds: float = 0, estimated_usd: float = 0, job_id: str | None = None,
                  rate_version: str = '2026-10-24-v1', path: str | Path | None = None) -> str:
    usage_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with connect(path) as conn:
        conn.execute("INSERT INTO api_usage VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (usage_id, job_id, operation, model, input_tokens, output_tokens, audio_seconds, estimated_usd, rate_version, now))
    return usage_id


def vocabulary_answer(vocab_id: str, sense_id: int, direction: str, rating: str, duration: float,
                      idempotency_key: str, *, path: str | Path | None = None) -> bool:
    if direction not in ('en_to_ja', 'ja_to_en') or rating not in ('again', 'known'):
        raise ValueError('Invalid answer direction or rating')
    if duration < 0:
        raise ValueError('Answer duration cannot be negative')
    with connect(path) as conn:
        session = conn.execute("SELECT session_id FROM study_sessions WHERE session_type='vocabulary' ORDER BY started_at_utc DESC LIMIT 1").fetchone()
    session_id = session['session_id'] if session else create_study_session(path=path)
    return record_vocabulary_answer(session_id=session_id, vocab_id=vocab_id, sense_id=sense_id,
                                    direction=direction, rating=rating, duration_seconds=duration,
                                    idempotency_key=idempotency_key, path=path)


def review_and_statistics(*, path: str | Path | None = None, now: datetime | None = None, days: int | None = None) -> dict:
    tokyo = timezone(timedelta(hours=9), 'Asia/Tokyo')
    local_today = (now or datetime.now(timezone.utc)).astimezone(tokyo).date()
    period_start=local_today-timedelta(days=max(1,int(days))-1) if days is not None else None
    with connect(path) as conn:
        events = conn.execute("SELECT vocab_id,direction,rating,duration_seconds,occurred_at_utc FROM study_events WHERE event_type='vocabulary_answer' ORDER BY occurred_at_utc,rowid").fetchall()
        vocabulary_rows=conn.execute("SELECT vocab_id,english,japanese,archived_at_utc FROM vocab ORDER BY english COLLATE NOCASE,vocab_id").fetchall()
        total_vocabularies=len(vocabulary_rows)
        archived_vocabularies=sum(row['archived_at_utc'] is not None for row in vocabulary_rows)
        sense_count=conn.execute('SELECT count(*) FROM senses').fetchone()[0]
        due = list(_due_review_schedule(conn,local_today=local_today).values())
        overlap_events=conn.execute("SELECT duration_seconds,occurred_at_utc FROM study_events WHERE event_type='overlap_activity' ORDER BY occurred_at_utc,rowid").fetchall()
        daily: dict[str, dict] = {}
        performance={row['vocab_id']:{'vocab_id':row['vocab_id'],'english':row['english'],'japanese':row['japanese'],'archived':row['archived_at_utc'] is not None,'attempts':0,'known':0,'again':0} for row in vocabulary_rows}
        active_days: set[str] = set()
        total_known = total = vocabulary_activity = overlap_activity = 0.0
        for event in events:
            item=performance.get(event['vocab_id'])
            if item:
                item['attempts']+=1
                item[event['rating']]+=1
            local_day = datetime.fromisoformat(event['occurred_at_utc']).astimezone(tokyo).date().isoformat()
            if period_start and (local_day < period_start.isoformat() or local_day > local_today.isoformat()):
                continue
            day = daily.setdefault(local_day, {'answers': 0, 'known': 0, 'again': 0, 'active_seconds': 0.0,'vocabulary_active_seconds':0.0,'overlap_active_seconds':0.0})
            day['answers'] += 1
            day[event['rating']] += 1
            day['active_seconds'] += event['duration_seconds']
            day['vocabulary_active_seconds'] += event['duration_seconds']
            total += 1
            total_known += event['rating'] == 'known'
            vocabulary_activity += event['duration_seconds']
            active_days.add(local_day)
        for event in overlap_events:
            local_day=datetime.fromisoformat(event['occurred_at_utc']).astimezone(tokyo).date().isoformat()
            if period_start and (local_day < period_start.isoformat() or local_day > local_today.isoformat()):
                continue
            day=daily.setdefault(local_day,{'answers':0,'known':0,'again':0,'active_seconds':0.0,'vocabulary_active_seconds':0.0,'overlap_active_seconds':0.0})
            day['active_seconds']+=event['duration_seconds']
            day['overlap_active_seconds']+=event['duration_seconds']
            overlap_activity+=event['duration_seconds']
            active_days.add(local_day)
        legacy_count = conn.execute("SELECT count(*) FROM history").fetchone()[0] if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='history'").fetchone() else 0
        new_count=conn.execute("SELECT count(*) FROM vocab v WHERE v.archived_at_utc IS NULL AND NOT EXISTS(SELECT 1 FROM study_events e WHERE e.event_type='vocabulary_answer' AND e.vocab_id=v.vocab_id)").fetchone()[0]
        due_labels=[]
        for item in due:
            row=conn.execute("SELECT v.english,s.meaning FROM vocab v LEFT JOIN senses s ON s.sense_id=? WHERE v.vocab_id=?",(item['sense_id'],item['vocab_id'])).fetchone()
            if row:due_labels.append({**item,'english':row['english'],'meaning':row['meaning']})
    for value in daily.values():
        value['self_report_known_rate'] = value['known'] / value['answers'] if value['answers'] else None
    performance_rows=list(performance.values())
    for item in performance_rows:
        item['known_rate']=item['known']/item['attempts'] if item['attempts'] else None
    all_attempts=int(sum(item['attempts'] for item in performance_rows))
    all_known=int(sum(item['known'] for item in performance_rows))
    all_again=int(sum(item['again'] for item in performance_rows))
    database_stats={'vocabulary_count':total_vocabularies,'active_vocabulary_count':total_vocabularies-archived_vocabularies,'archived_vocabulary_count':archived_vocabularies,'sense_count':sense_count,'attempt_count':all_attempts,'known_count':all_known,'again_count':all_again,'accuracy':all_known/all_attempts if all_attempts else None,'unseen_vocabulary_count':new_count}
    return {'algorithm_version': 'simple-interval-v1', 'daily': daily, 'known_rate': total_known / total if total else None,
            'vocabulary_active_seconds':vocabulary_activity,'overlap_active_seconds':overlap_activity,
            'active_seconds': vocabulary_activity+overlap_activity, 'study_days': len(active_days), 'new_vocabulary_count':new_count,'due_count': len(due_labels), 'due_items': due_labels,
            'period_start_tokyo':period_start.isoformat() if period_start else None,'period_end_tokyo':local_today.isoformat(),
            'legacy_history_count_excluded': legacy_count, 'today_tokyo': local_today.isoformat(),
            'database_stats':database_stats,'vocabulary_performance':performance_rows}


def create_import_batch(source_type: str, source_text: str, *, path: str | Path | None = None) -> str:
    if source_type not in ('english_text','vocabulary_list'):
        raise ValueError('Unsupported candidate source')
    batch_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with connect(path) as conn:
        conn.execute("INSERT INTO import_batches(batch_id,source_type,source_text,status,created_at_utc) VALUES (?,?,?,'draft',?)",
                     (batch_id, source_type, source_text, now))
    return batch_id


def add_candidates(batch_id: str, candidates: list[dict], *, path: str | Path | None = None) -> list[str]:
    from .vocabulary import normalize_headword
    ids=[]
    with connect(path) as conn:
        existing={normalize_headword(row['english']):row['vocab_id'] for row in conn.execute('SELECT vocab_id,english FROM vocab')}
        seen=set()
        for item in candidates:
            english=str(item.get('english','')).strip()
            meaning=str(item.get('meaning','')).strip()
            if not english:
                continue
            key=normalize_headword(english)
            matched=existing.get(key)
            reason='exact_match' if matched else ('duplicate_candidate' if key in seen else None)
            seen.add(key)
            candidate_id=uuid.uuid4().hex
            conn.execute("INSERT INTO candidates(candidate_id,batch_id,english,meaning,part_of_speech,source,selected,excluded_reason,matched_vocab_id,similarity) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (candidate_id,batch_id,english,meaning,str(item.get('part_of_speech','')),str(item.get('source','')),int(bool(item.get('selected'))),reason,matched,1.0 if matched else None))
            ids.append(candidate_id)
        conn.execute("UPDATE import_batches SET status='ready' WHERE batch_id=?",(batch_id,))
    return ids


def list_candidates(batch_id: str, *, path: str | Path | None = None) -> list[dict]:
    with connect(path) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM candidates WHERE batch_id=? ORDER BY english COLLATE NOCASE,candidate_id",(batch_id,))]


def update_candidate_assessment(candidate_id: str, assessment: dict, *, path: str | Path | None = None) -> None:
    with connect(path) as conn:
        conn.execute("""UPDATE candidates SET excluded_reason=?,matched_vocab_id=?,similarity=?,embedding_model=?,
            embedding_dimensions=?,input_hash=?,embedding_json=? WHERE candidate_id=?""",
            (assessment.get('reason'),assessment.get('matched_vocab_id'),assessment.get('similarity'),assessment.get('model'),
             len(assessment.get('candidate_embedding') or []) or None,assessment.get('input_hash'),
             json.dumps(assessment['candidate_embedding']) if assessment.get('candidate_embedding') else None,candidate_id))


def complete_candidate_similarity_job(job_id: str, assessments: list[dict], *, model: str,
                                      input_tokens: int, estimated_usd: float, rate_version: str,
                                      result: dict, record_usage: bool = True,
                                      path: str | Path | None = None) -> None:
    """Persist a candidate batch, its usage, and job completion atomically."""
    now=datetime.now(timezone.utc).isoformat(timespec='seconds')
    with connect(path) as conn:
        conn.executemany("""UPDATE candidates SET excluded_reason=?,matched_vocab_id=?,similarity=?,embedding_model=?,
            embedding_dimensions=?,input_hash=?,embedding_json=? WHERE candidate_id=?""",
            [(item.get('reason'),item.get('matched_vocab_id'),item.get('similarity'),item.get('model'),
              len(item.get('candidate_embedding') or []) or None,item.get('input_hash'),
              json.dumps(item['candidate_embedding']) if item.get('candidate_embedding') else None,item['candidate_id'])
             for item in assessments])
        if record_usage:
            conn.execute("INSERT INTO api_usage VALUES (?,?,?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex,job_id,'candidate_similarity',model,int(input_tokens),0,0,float(estimated_usd),rate_version,now))
        conn.execute("""UPDATE api_jobs SET status='completed',completed_items=?,result_json=?,error=NULL,updated_at_utc=? WHERE job_id=?""",
            (len(assessments),json.dumps(result,ensure_ascii=False),now,job_id))


def select_candidates(batch_id: str, candidate_ids: list[str], *, path: str | Path | None = None) -> list[str]:
    from .vocabulary import normalize_headword
    created=[]
    with connect(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        selected = conn.execute("SELECT * FROM candidates WHERE batch_id=? AND candidate_id IN (%s)" % ','.join('?' for _ in candidate_ids), (batch_id,*candidate_ids)).fetchall() if candidate_ids else []
        existing={normalize_headword(row['english']):row['vocab_id'] for row in conn.execute('SELECT vocab_id,english FROM vocab')}
        for candidate in selected:
            if candidate['created_vocab_id'] or candidate['excluded_reason']:
                continue
            key=normalize_headword(candidate['english'])
            if key in existing:
                conn.execute("UPDATE candidates SET excluded_reason='exact_match',matched_vocab_id=? WHERE candidate_id=?",(existing[key],candidate['candidate_id']))
                continue
            if not candidate['meaning'].strip():
                conn.execute("UPDATE candidates SET excluded_reason='meaning_required' WHERE candidate_id=?",(candidate['candidate_id'],))
                continue
            vocab_id=uuid.uuid4().hex
            vocabulary_columns = {row['name'] for row in conn.execute('PRAGMA table_info(vocab)')}
            if 'sources' in vocabulary_columns:
                conn.execute("INSERT INTO vocab(vocab_id,english,japanese,pos,sources) VALUES (?,?,?,?,?)",
                             (vocab_id,candidate['english'],candidate['meaning'],candidate['part_of_speech'],candidate['source']))
            else:
                conn.execute("INSERT INTO vocab(vocab_id,english,japanese,pos) VALUES (?,?,?,?)",
                             (vocab_id,candidate['english'],candidate['meaning'],candidate['part_of_speech']))
            conn.execute("INSERT INTO senses(vocab_id,sense_index,meaning,part_of_speech,source) VALUES (?,0,?,?,?)",
                         (vocab_id,candidate['meaning'],candidate['part_of_speech'],candidate['source']))
            conn.execute("UPDATE candidates SET created_vocab_id=?,excluded_reason=NULL WHERE candidate_id=?",(vocab_id,candidate['candidate_id']))
            if candidate['embedding_json'] and candidate['embedding_model'] and candidate['embedding_dimensions']:
                sense_id=conn.execute('SELECT sense_id FROM senses WHERE vocab_id=?',(vocab_id,)).fetchone()['sense_id']
                conn.execute("INSERT INTO embeddings(vocab_id,sense_id,model,dimensions,input_version,input_hash,vector_json,created_at_utc) VALUES (?,?,?,?,?,?,?,?)",
                             (vocab_id,sense_id,candidate['embedding_model'],candidate['embedding_dimensions'],'english-meaning-v1',candidate['input_hash'],candidate['embedding_json'],datetime.now(timezone.utc).isoformat(timespec='seconds')))
            existing[key]=vocab_id
            created.append(vocab_id)
        conn.execute("UPDATE import_batches SET status='completed' WHERE batch_id=?",(batch_id,))
    return created


def update_difficulty(sense_id: int, level: str | None, evidence: str = '', model: str = '', *, manual: bool = False,
                      path: str | Path | None = None) -> None:
    if level is not None and level not in ('A1','A2','B1','B2','C1','C2'):
        raise ValueError('CEFR level must be A1-C2 or blank')
    now=datetime.now(timezone.utc).isoformat(timespec='seconds')
    with connect(path) as conn:
        if not manual:
            row=conn.execute('SELECT difficulty_manual FROM senses WHERE sense_id=?',(sense_id,)).fetchone()
            if row and row['difficulty_manual']:
                return
        cur=conn.execute("UPDATE senses SET difficulty_level=?,difficulty_evidence=?,difficulty_model=?,difficulty_assessed_at_utc=?,difficulty_manual=?,difficulty_version='cefr-prompt-v1' WHERE sense_id=?",
                         (level,evidence,model,now,int(manual),sense_id))
        if cur.rowcount!=1: raise LookupError('Sense not found')


def create_material(*, title: str, text_content: str, source: str = '', difficulty_level: str | None = None,
                    metadata: dict | None = None, path: str | Path | None = None) -> str:
    material_id=uuid.uuid4().hex
    now=datetime.now(timezone.utc).isoformat(timespec='seconds')
    with connect(path) as conn:
        conn.execute("INSERT INTO materials(material_id,material_type,title,text_content,difficulty_level,source,metadata_json,created_at_utc,content_json) VALUES (?,'generated_text',?,?,?,?,?,?, '{}')",
                     (material_id,title,text_content,difficulty_level,source,json.dumps(metadata or {},ensure_ascii=False),now))
    return material_id


def imported_material_source_names(*, path: str | Path | None = None) -> set[str]:
    with connect(path) as conn:
        return {row[0] for row in conn.execute('SELECT source_name FROM material_legacy_imports')}


def material_for_legacy_source(source_name: str, *, path: str | Path | None = None) -> dict | None:
    with connect(path) as conn:
        row=conn.execute('SELECT m.* FROM materials m JOIN material_legacy_imports i ON i.material_id=m.material_id WHERE i.source_name=?',(source_name,)).fetchone()
        return dict(row) if row else None


def import_legacy_material(item: dict, *, path: str | Path | None = None) -> dict:
    """Import one legacy subtitle JSON once; subsequent changes to that file are ignored."""
    filename=item.get('file'); data=item.get('data'); digest=item.get('sha256')
    if not isinstance(filename,str) or Path(filename).name!=filename or not filename.startswith('english_overlap_') or Path(filename).suffix!='.json':
        raise ValueError('Invalid legacy material filename')
    if not isinstance(data,dict) or not isinstance(digest,str) or len(digest)!=64:
        raise ValueError('Invalid legacy material payload')
    text_content=data.get('text')
    if not isinstance(text_content,str) or not text_content.strip():
        raise ValueError('Legacy material has no article text')
    title=str(data.get('title') or '').strip()
    if not title:
        title=next((line.strip()[2:].strip() for line in text_content.splitlines() if line.strip().startswith('# ')), '')
    if not title:title=str(data.get('summary') or text_content.splitlines()[0] or filename).strip()
    title=title[:160] or filename
    content={key:value for key,value in data.items() if key not in ('title','text','created_at','audio_file','subtitle_file')}
    audio=data.get('audio_file')
    if not isinstance(audio,str) or Path(audio).name!=audio or not audio.startswith('english_overlap_') or Path(audio).suffix not in ('.mp3','.wav'):
        audio=None
    created=data.get('created_at')
    try:
        parsed=datetime.fromisoformat(str(created).replace('Z','+00:00'))
        if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone.utc)
        created=parsed.astimezone(timezone.utc).isoformat(timespec='seconds')
    except (TypeError,ValueError):
        created=datetime.now(timezone.utc).isoformat(timespec='seconds')
    now=datetime.now(timezone.utc).isoformat(timespec='seconds')
    with connect(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        existing=conn.execute('SELECT material_id FROM material_legacy_imports WHERE source_name=?',(filename,)).fetchone()
        if existing:
            conn.rollback()
            return {'imported':False,'already_imported':True,'material_id':existing['material_id']}
        row=conn.execute('SELECT * FROM materials WHERE json_path=?',(filename,)).fetchone()
        if row:
            material_id=row['material_id']
            try:metadata=json.loads(row['metadata_json'] or '{}')
            except (TypeError,json.JSONDecodeError):metadata={}
            if not isinstance(metadata,dict):metadata={}
            for key in ('summary','summary_model','summary_prompt_version','summary_generated_at_utc','voice','style','model','word_count','character_count','audio_seconds','cost','imported_from_saved_file'):
                metadata.pop(key,None)
            conn.execute('UPDATE materials SET title=?,text_content=?,audio_path=?,json_path=NULL,metadata_json=?,content_json=? WHERE material_id=?',
                         (title,text_content,audio,json.dumps(metadata,ensure_ascii=False),json.dumps(content,ensure_ascii=False),material_id))
        else:
            material_id=uuid.uuid4().hex
            conn.execute("""INSERT INTO materials(material_id,material_type,title,text_content,audio_path,source,status,metadata_json,created_at_utc,content_json)
                VALUES (?,'overlap',?,?,?,?,?,?,?,?)""",
                (material_id,title,text_content,audio,'legacy_saved_file','ready','{}',created,json.dumps(content,ensure_ascii=False)))
        conn.execute('INSERT INTO material_legacy_imports(source_name,source_sha256,material_id,imported_at_utc) VALUES (?,?,?,?)',
                     (filename,digest,material_id,now))
    return {'imported':True,'already_imported':False,'material_id':material_id}


def attach_material_vocabulary(material_id: str, usages: list[dict], *, path: str | Path | None = None) -> None:
    with connect(path) as conn:
        for usage in usages:
            conn.execute("INSERT OR IGNORE INTO material_vocabulary(material_id,vocab_id,sense_id,usage_text,usage_start,usage_end) VALUES (?,?,?,?,?,?)",
                         (material_id,usage['vocab_id'],usage.get('sense_id'),usage.get('usage_text'),usage.get('usage_start'),usage.get('usage_end')))


def list_materials(*, query: str = '', path: str | Path | None = None) -> list[dict]:
    with connect(path) as conn:
        pattern=f"%{query.strip()}%"
        return [dict(row) for row in conn.execute("SELECT m.*, (SELECT count(*) FROM material_vocabulary mv WHERE mv.material_id=m.material_id) AS vocabulary_count FROM materials m WHERE (?='' OR m.title LIKE ? OR m.text_content LIKE ?) ORDER BY created_at_utc DESC",(query.strip(),pattern,pattern))]


def get_material(material_id: str, *, path: str | Path | None = None) -> dict | None:
    with connect(path) as conn:
        row=conn.execute('SELECT * FROM materials WHERE material_id=?',(material_id,)).fetchone()
        return dict(row) if row else None


def material_content(material: dict) -> dict:
    try:content=json.loads(material.get('content_json') or '{}')
    except (TypeError,json.JSONDecodeError):content={}
    return content if isinstance(content,dict) else {}


def update_material_summary(material_id: str, title: str, summary: str, *, model: str, prompt_version: str,
                            generated_at_utc: str, path: str | Path | None = None) -> None:
    if not title.strip() or not summary.strip():raise ValueError('Material title and summary are required')
    with connect(path) as conn:
        row=conn.execute('SELECT content_json FROM materials WHERE material_id=?',(material_id,)).fetchone()
        if row is None:raise LookupError('Material not found')
        try:content=json.loads(row['content_json'] or '{}')
        except (TypeError,json.JSONDecodeError):raise ValueError('Material content is invalid JSON') from None
        if not isinstance(content,dict):raise ValueError('Material content must be a JSON object')
        content.update({'summary':summary,'summary_model':model,'summary_prompt_version':prompt_version,
                        'summary_generated_at_utc':generated_at_utc})
        conn.execute('UPDATE materials SET title=?,content_json=? WHERE material_id=?',
                     (title.strip(),json.dumps(content,ensure_ascii=False),material_id))


def update_material(material_id: str, title: str, text_content: str, *, path: str | Path | None = None) -> None:
    if not title.strip() or not text_content.strip():raise ValueError('Material title and text are required')
    with connect(path) as conn:
        row=conn.execute('SELECT title,text_content,content_json FROM materials WHERE material_id=?',(material_id,)).fetchone()
        if row is None:raise LookupError('Material not found')
        try:content=json.loads(row['content_json'] or '{}')
        except (TypeError,json.JSONDecodeError):content={}
        if not isinstance(content,dict):content={}
        changed=row['title']!=title.strip() or row['text_content']!=text_content.strip()
        if changed:
            for key in ('summary','summary_model','summary_prompt_version','summary_generated_at_utc'):
                content.pop(key,None)
        body_changed=row['text_content']!=text_content.strip()
        if body_changed:
            content.update({'spoken_text':text_content.strip(),'blocks':[],'transcript':[],'words':[],'audio_file':None,'audio_seconds':None,
                            'word_count':len(re.findall(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*",text_content.strip())),
                            'character_count':len(text_content.strip())})
        cur=conn.execute("UPDATE materials SET title=?,text_content=?,audio_path=CASE WHEN ? THEN NULL ELSE audio_path END,content_json=? WHERE material_id=?",
                          (title.strip(),text_content.strip(),int(body_changed),json.dumps(content,ensure_ascii=False),material_id))
        if cur.rowcount!=1:raise LookupError('Material not found')


def store_material_generation(material_id: str, *, text_content: str, audio_path: str, content: dict,
                               path: str | Path | None = None) -> None:
    if not isinstance(content,dict):raise ValueError('Generated material content must be an object')
    if not isinstance(audio_path,str) or Path(audio_path).name!=audio_path or Path(audio_path).suffix not in ('.mp3','.wav'):
        raise ValueError('Invalid audio path')
    with connect(path) as conn:
        row=conn.execute('SELECT title,text_content,content_json FROM materials WHERE material_id=?',(material_id,)).fetchone()
        if row is None:raise LookupError('Material not found')
        try:existing=json.loads(row['content_json'] or '{}')
        except (TypeError,json.JSONDecodeError):existing={}
        if not isinstance(existing,dict):existing={}
        if row['text_content']!=text_content:
            for key in ('summary','summary_model','summary_prompt_version','summary_generated_at_utc'):
                existing.pop(key,None)
            first_line=text_content.strip().splitlines()[0] if text_content.strip() else 'Overlap practice'
            title=first_line[:120]
        else:title=row['title']
        existing.update(content)
        conn.execute("UPDATE materials SET material_type='overlap',title=?,text_content=?,audio_path=?,json_path=NULL,status='ready',content_json=? WHERE material_id=?",
                     (title,text_content,audio_path,json.dumps(existing,ensure_ascii=False),material_id))


def archive_material(material_id: str, archived: bool = True, *, path: str | Path | None = None) -> None:
    status='archived' if archived else 'ready'
    with connect(path) as conn:
        cur=conn.execute("UPDATE materials SET status=? WHERE material_id=?",(status,material_id))
        if cur.rowcount!=1:raise LookupError('Material not found')


def delete_material(material_id: str, *, path: str | Path | None = None) -> dict:
    with connect(path) as conn:
        row=conn.execute('SELECT * FROM materials WHERE material_id=?',(material_id,)).fetchone()
        if row is None:raise LookupError('Material not found')
        material=dict(row)
        conn.execute('DELETE FROM material_vocabulary WHERE material_id=?',(material_id,))
        conn.execute('DELETE FROM materials WHERE material_id=?',(material_id,))
        candidates=list(dict.fromkeys(value for value in (material.get('audio_path'),) if value))
        unshared=[];shared=[]
        for value in candidates:
            reference=conn.execute('SELECT 1 FROM materials WHERE audio_path=? LIMIT 1',(value,)).fetchone()
            (shared if reference else unshared).append(value)
    return {'material':material,'artifact_paths':unshared,'shared_artifacts':shared}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Manage the English Overlap learning database")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="Back up and apply pending schema migrations")
    backup_parser = commands.add_parser("backup", help="Create a consistent SQLite backup")
    backup_parser.add_argument("--output", type=Path)
    restore_parser = commands.add_parser("restore", help="Restore a verified SQLite backup")
    restore_parser.add_argument("backup", type=Path)
    restore_parser.add_argument("--to", type=Path, default=database_path())
    args = parser.parse_args(argv)

    if args.command == "migrate":
        version, backup_path = migrate_database()
        print(f"Database schema version: {version}")
        print(f"Pre-migration backup: {backup_path or 'not needed'}")
    elif args.command == "backup":
        result = backup_database(database_path(), args.output)
        print(result)
    elif args.command == "restore":
        restore_database(args.backup, args.to)
        print(f"Restored {args.backup} to {args.to}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
