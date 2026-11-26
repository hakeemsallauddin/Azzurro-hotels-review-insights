"""SQLite schema and connection helpers for the review warehouse."""
from __future__ import annotations
import os, shutil, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = ROOT / "data" / "reviews.sqlite3"
_PUBLIC_DB = ROOT / "data" / "reviews-public.sqlite3"
# One original working database: data/reviews.sqlite3. The API and the scraper
# both read and write this single file, so backfilled reviews are stored in the
# same database the dashboard serves. A fresh clone ships only the snapshot
# (reviews-public.sqlite3); on first run it is copied once to seed the working
# database, and from then on only the working database is used.
DB_PATH = Path(os.getenv("AZZURRO_DB", _DEFAULT_DB))
TURSO_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")
if not TURSO_URL and not DB_PATH.exists() and _PUBLIC_DB.exists() and DB_PATH != _PUBLIC_DB:
    # First run with a fresh working database (new clone, or a persistent
    # disk mounted elsewhere via AZZURRO_DB): seed it once from the shipped
    # snapshot, then only the working database is used.
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_PUBLIC_DB, DB_PATH)
PROPERTIES = {
    "olympic-paddington": ("Olympic Hotel Paddington", "https://www.booking.com/hotel/au/olympic-paddington.html"),
    "venus-potts-point-sydney": ("Potts Point", "https://www.booking.com/hotel/au/venus-potts-point-sydney.html"),
    "venus-surry-hills": ("Central Sydney", "https://www.booking.com/hotel/au/venus-surry-hills.html"),
    "chateau-de-venus": ("Darling Harbour", "https://www.booking.com/hotel/au/chateau-de-venus.html"),
}


# --- Optional hosted database: Turso (libSQL) -------------------------------
# When TURSO_DATABASE_URL is set, the one original working database lives in
# Turso instead of a local file (used for free hosting with no persistent
# disk). The classes below give the libsql client the same surface the rest of
# the codebase uses from sqlite3: connection.execute/executemany/executescript,
# cursor.fetchall/fetchone/lastrowid, and rows readable by index or column
# name (including dict(row)).

class _TursoRow:
    __slots__ = ("_values", "_columns", "_index")
    def __init__(self, values, columns):
        self._values = tuple(values)
        self._columns = list(columns)
        self._index = {name: i for i, name in enumerate(self._columns)}
    def __getitem__(self, key):
        if isinstance(key, str):
            return self._values[self._index[key]]
        return self._values[key]
    def __iter__(self):
        return iter(self._values)
    def __len__(self):
        return len(self._values)
    def keys(self):
        return list(self._columns)

class _TursoCursor:
    def __init__(self, result=None):
        if result is not None and result.columns:
            self._rows = [_TursoRow(row, result.columns) for row in result.rows]
        elif result is not None:
            self._rows = [_TursoRow(row, []) for row in result.rows]
        else:
            self._rows = []
        self._pos = 0
        self.lastrowid = getattr(result, "last_insert_rowid", None) if result is not None else None
        self.rowcount = getattr(result, "rows_affected", 0) if result is not None else 0
    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row
    def fetchall(self):
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rows
    def __iter__(self):
        return iter(self.fetchall())

class _TursoConnection:
    def __init__(self, client):
        self._client = client
    def execute(self, sql, params=()):
        return _TursoCursor(self._client.execute(sql, list(params)))
    def executemany(self, sql, seq_of_params):
        import libsql_client
        statements = [libsql_client.Statement(sql, list(params)) for params in seq_of_params]
        if not statements:
            return _TursoCursor()
        results = self._client.batch(statements)
        return _TursoCursor(results[-1] if results else None)
    def executescript(self, script):
        import libsql_client
        statements = [part.strip() for part in script.split(";") if part.strip()]
        if statements:
            self._client.batch([libsql_client.Statement(part) for part in statements])
        return _TursoCursor()
    def commit(self):
        pass
    def rollback(self):
        pass
    def close(self):
        pass  # the client is shared process-wide; never close it per query
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False

import threading
_turso_client = None
_turso_client_lock = threading.Lock()

def _shared_turso_client():
    # One client per process: creating a libsql client per query made the
    # hosted API slow (a fresh connection setup for every single statement).
    global _turso_client
    if _turso_client is None:
        with _turso_client_lock:
            if _turso_client is None:
                import libsql_client
                _turso_client = libsql_client.create_client_sync(url=TURSO_URL, auth_token=TURSO_TOKEN)
    return _turso_client

def connect():
    if TURSO_URL:
        return _TursoConnection(_shared_turso_client())
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db

def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS reviews (
          id INTEGER PRIMARY KEY,
          review_id TEXT NOT NULL,
          review_key TEXT NOT NULL UNIQUE,
          property_slug TEXT NOT NULL,
          property_name TEXT NOT NULL,
          reviewer_name TEXT NOT NULL DEFAULT '', reviewer_country TEXT NOT NULL DEFAULT '',
          rating REAL, review_date TEXT, stay_date TEXT, room_type TEXT,
          nights_stayed INTEGER, traveller_type TEXT, title TEXT,
          positive_text TEXT NOT NULL DEFAULT '', negative_text TEXT NOT NULL DEFAULT '',
          hotel_reply TEXT, scraped_at TEXT NOT NULL,
          sentiment TEXT NOT NULL DEFAULT 'neutral', topics TEXT NOT NULL DEFAULT '[]',
          issue_topics TEXT NOT NULL DEFAULT '[]', praise_topics TEXT NOT NULL DEFAULT '[]',
          UNIQUE(property_slug, review_id)
        );
        CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(review_date DESC);
        CREATE INDEX IF NOT EXISTS idx_reviews_property_date ON reviews(property_slug, review_date DESC);
        CREATE INDEX IF NOT EXISTS idx_reviews_rating ON reviews(rating);
        CREATE INDEX IF NOT EXISTS idx_reviews_sentiment ON reviews(sentiment);
        CREATE INDEX IF NOT EXISTS idx_reviews_reviewer ON reviews(reviewer_name);
        CREATE TABLE IF NOT EXISTS scraper_runs (
          id INTEGER PRIMARY KEY, mode TEXT NOT NULL, property_slug TEXT,
          started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
          new_reviews INTEGER NOT NULL DEFAULT 0, duplicates_skipped INTEGER NOT NULL DEFAULT 0,
          pages INTEGER NOT NULL DEFAULT 0, errors TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS scraper_state (
          property_slug TEXT PRIMARY KEY, last_review_date TEXT, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS property_source_state (
          property_slug TEXT PRIMARY KEY,
          booking_total_reviews INTEGER,
          booking_overall_score REAL,
          source_observed_at TEXT,
          source_method TEXT,
          latest_run_id INTEGER,
          latest_run_mode TEXT,
          latest_run_started_at TEXT,
          latest_run_finished_at TEXT,
          latest_run_status TEXT,
          latest_run_pages INTEGER,
          latest_run_cards INTEGER,
          last_success_at TEXT,
          last_full_run_at TEXT,
          last_full_pages INTEGER,
          last_full_cards INTEGER,
          backfill_status TEXT,
          last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS action_tasks (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          details TEXT NOT NULL DEFAULT '',
          topic TEXT NOT NULL,
          property_slug TEXT NOT NULL DEFAULT 'all',
          department TEXT NOT NULL,
          priority TEXT NOT NULL DEFAULT 'medium',
          status TEXT NOT NULL DEFAULT 'open',
          owner TEXT NOT NULL DEFAULT '',
          due_date TEXT,
          completion_note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_actions_status_due ON action_tasks(status, due_date);
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(reviews)").fetchall()}
        classification_backfill_needed = not {"issue_topics", "praise_topics"}.issubset(columns)
        if "issue_topics" not in columns:
            db.execute("ALTER TABLE reviews ADD COLUMN issue_topics TEXT NOT NULL DEFAULT '[]'")
        if "praise_topics" not in columns:
            db.execute("ALTER TABLE reviews ADD COLUMN praise_topics TEXT NOT NULL DEFAULT '[]'")
        if classification_backfill_needed:
            from backend.analytics.classify import classify, classify_issue_topics, classify_praise_topics
            for row in db.execute("SELECT id,rating,positive_text,negative_text FROM reviews").fetchall():
                sentiment, topics = classify(row["rating"], row["positive_text"], row["negative_text"])
                issues = classify_issue_topics(sentiment, row["negative_text"])
                praise = classify_praise_topics(sentiment, row["positive_text"])
                db.execute("UPDATE reviews SET sentiment=?,topics=?,issue_topics=?,praise_topics=? WHERE id=?", (sentiment,__import__('json').dumps(topics),__import__('json').dumps(issues),__import__('json').dumps(praise),row["id"]))
        snapshot_path=ROOT / "data" / "booking-source-snapshot.json"
        if snapshot_path.exists():
            import json
            for item in json.loads(snapshot_path.read_text(encoding="utf-8")):
                db.execute("""INSERT INTO property_source_state(property_slug,booking_total_reviews,booking_overall_score,source_observed_at,source_method)
                    VALUES(?,?,?,?,?) ON CONFLICT(property_slug) DO UPDATE SET
                    booking_total_reviews=COALESCE(property_source_state.booking_total_reviews,excluded.booking_total_reviews),
                    booking_overall_score=COALESCE(property_source_state.booking_overall_score,excluded.booking_overall_score),
                    source_observed_at=COALESCE(property_source_state.source_observed_at,excluded.source_observed_at),
                    source_method=COALESCE(property_source_state.source_method,excluded.source_method)""",
                    (item["property_slug"],item["booking_total_reviews"],item["booking_overall_score"],item["source_observed_at"],item["source_method"]))
