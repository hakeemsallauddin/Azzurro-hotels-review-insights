"""One-time copy of the shipped review snapshot into the Turso database.

Usage (credentials come from the environment, never from files):
    TURSO_DATABASE_URL=libsql://... TURSO_AUTH_TOKEN=... \
        .venv/bin/python scripts/migrate_to_turso.py

Reads data/reviews-public.sqlite3 and writes every table into Turso in
batches, preserving ids. Safe to re-run: tables are cleared first.
"""
import os, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "reviews-public.sqlite3"
TABLES = ["reviews", "scraper_runs", "scraper_state", "property_source_state", "action_tasks"]
BATCH = 250

def main():
    if not os.getenv("TURSO_DATABASE_URL"):
        sys.exit("TURSO_DATABASE_URL is not set")
    from backend.db import connect, init_db
    init_db()  # creates the schema in Turso
    source = sqlite3.connect(SOURCE)
    source.row_factory = sqlite3.Row
    with connect() as target:
        for table in TABLES:
            columns = [row[1] for row in source.execute(f"PRAGMA table_info({table})")]
            rows = source.execute(f"SELECT * FROM {table}").fetchall()
            target.execute(f"DELETE FROM {table}")
            placeholders = ",".join("?" * len(columns))
            sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
            for start in range(0, len(rows), BATCH):
                chunk = [tuple(row[col] for col in columns) for row in rows[start:start + BATCH]]
                target.executemany(sql, chunk)
            count = target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table}: copied {len(rows)}, in Turso now {count}")
    print("Migration complete.")

if __name__ == "__main__":
    main()
