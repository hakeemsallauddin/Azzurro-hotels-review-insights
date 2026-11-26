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
if not DB_PATH.exists() and _PUBLIC_DB.exists() and DB_PATH != _PUBLIC_DB:
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

def connect():
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
