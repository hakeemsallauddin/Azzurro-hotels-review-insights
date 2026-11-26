"""Push reviews collected by the external collection worker into the hosted
(Turso) database.

The hosted web service cannot collect from Booking.com itself (datacenter
IPs receive a human-verification wall), so collection happens in a browser
session Booking.com serves, into a local SQLite database. This script copies
every review from that local database that the hosted database does not
already hold, so the hosted dataset only ever gains genuine Booking.com
reviews and never exceeds Booking.com's own totals.

Identity rule: (property_slug, reviewer name normalised to its first line,
review_date). Hosted rows glue the country onto the reviewer name
("Justine\nAustralia"), so content hashes alone do not match across the two
captures; the normalised identity does.

Credentials come from TURSO_DATABASE_URL / TURSO_AUTH_TOKEN in the
environment, or from a local .turso-env file (gitignored, never committed).

Usage:
  python scripts/sync_to_turso.py [source_sqlite_path]   # sync a whole source DB
  python scripts/sync_to_turso.py --from-json batch.json # sync one extracted batch
Prints a JSON summary: {"inserted": N, "already_present": M, "turso_total": T}
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.analytics.classify import (  # noqa: E402
    classify,
    classify_issue_topics,
    classify_praise_topics,
)

DEFAULT_SOURCE = Path.home() / "workspace" / "azzurro-hotels-dashboard" / "data" / "reviews.db"


def load_env() -> tuple[str, str]:
    env_file = Path(__file__).resolve().parents[1] / ".turso-env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())
    return os.environ["TURSO_DATABASE_URL"].rstrip("/"), os.environ["TURSO_AUTH_TOKEN"]


BASE, TOKEN = load_env()


def enc(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, bytes):
        return {"type": "blob", "value": base64.b64encode(value).decode()}
    return {"type": "text", "value": str(value)}


def dec(cell):
    kind = cell["type"]
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
    if kind == "blob":
        return base64.b64decode(cell["value"])
    return cell["value"]


def pipeline(statements):
    body = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": [enc(a) for a in args]}}
            for sql, args in statements
        ]
        + [{"type": "close"}]
    }
    req = urllib.request.Request(
        BASE + "/v2/pipeline",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    payload = json.loads(urllib.request.urlopen(req, timeout=300).read())
    out = []
    for item in payload["results"]:
        if item["type"] == "error":
            raise RuntimeError(item["error"]["message"])
        if item["response"].get("type") != "execute":
            continue
        result = item["response"]["result"]
        out.append([tuple(dec(c) for c in row) for row in result["rows"]])
    return out


def query(sql, args=()):
    return pipeline([(sql, args)])[0]


def identity(slug, name, date):
    return (slug, " ".join((name or "").split("\n")[0].split()).lower(), date)


def word_set(*texts) -> set:
    import re

    words = set()
    for text in texts:
        words.update(re.findall(r"[a-z']+", (text or "").lower()))
    return words


def text_overlap(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(len(a | b), 1)


def review_hash(slug, name, date, title, positive, negative) -> str:
    import hashlib

    fields = [str(v or "") for v in (slug, name, date, title, positive, negative)]
    return hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "--from-json":
        # Incremental mode: sync only the reviews in this freshly extracted
        # batch file (a JSON list of review objects), nothing else.
        batch = json.loads(Path(args[1]).read_text())
        source_rows = []
        for item in batch:
            row = dict(item)
            for key in (
                "review_id", "property_name", "reviewer_name", "reviewer_country",
                "rating", "review_date", "stay_date", "room_type", "nights_stayed",
                "traveller_type", "title", "positive_text", "negative_text",
                "hotel_reply", "scraped_at",
            ):
                row.setdefault(key, None)
            if not row["scraped_at"]:
                from datetime import datetime, timezone

                row["scraped_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            row["dedup_hash"] = review_hash(
                row.get("property_slug"),
                row.get("reviewer_name"),
                row.get("review_date"),
                row.get("title"),
                row.get("positive_text"),
                row.get("negative_text"),
            )
            source_rows.append(row)
    else:
        source_path = Path(args[0]) if args else DEFAULT_SOURCE
        source = sqlite3.connect(source_path)
        source.row_factory = sqlite3.Row
        source_rows = source.execute("SELECT * FROM reviews").fetchall()

    hosted_ids = set()
    # Word sets per (property, date, rating) for the variant check below:
    # some hosted rows store the reviewer name as a single initial while
    # the dialog gives the full name, so the identity check alone can miss
    # that a candidate is the same review in a different name form.
    hosted_texts = {}
    offset = 0
    while True:
        page = query(
            "SELECT property_slug, reviewer_name, review_date, rating, positive_text, "
            "negative_text FROM reviews ORDER BY id LIMIT 1500 OFFSET ?",
            (offset,),
        )
        if not page:
            break
        for slug, name, date, rating, positive, negative in page:
            hosted_ids.add(identity(slug, name, date))
            key = (slug, date, rating)
            hosted_texts.setdefault(key, []).append(word_set(positive, negative))
        offset += len(page)

    before = query("SELECT COUNT(*) FROM reviews")[0][0]
    missing = []
    skipped_variants = 0
    for row in source_rows:
        if identity(row["property_slug"], row["reviewer_name"], row["review_date"]) in hosted_ids:
            continue
        candidates = hosted_texts.get(
            (row["property_slug"], row["review_date"], row["rating"]), []
        )
        words = word_set(row.get("positive_text"), row.get("negative_text"))
        if any(text_overlap(words, other) > 0.6 for other in candidates):
            skipped_variants += 1
            continue
        missing.append(row)

    # Insert with the exact column set and classification the repo's own
    # scraper uses (backend/scraper/run_scraper.py save_review), so synced
    # rows are indistinguishable from natively collected ones. Source rows
    # carry no Booking.com review_id, so the key is the content hash, the
    # same fallback the scraper uses for ID-less reviews.
    insert_sql = (
        "INSERT OR IGNORE INTO reviews(review_id,review_key,property_slug,property_name,"
        "reviewer_name,reviewer_country,rating,review_date,stay_date,room_type,nights_stayed,"
        "traveller_type,title,positive_text,negative_text,hotel_reply,scraped_at,sentiment,"
        "topics,issue_topics,praise_topics) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    statements = []
    for row in missing:
        key = row["dedup_hash"]
        sentiment, topics = classify(row["rating"], row["positive_text"], row["negative_text"])
        issue_topics = classify_issue_topics(sentiment, row["negative_text"])
        praise_topics = classify_praise_topics(sentiment, row["positive_text"])
        statements.append(
            (
                insert_sql,
                (
                    row["review_id"] or key,
                    key,
                    row["property_slug"],
                    row["property_name"],
                    row["reviewer_name"] or "",
                    row["reviewer_country"] or "",
                    row["rating"],
                    row["review_date"],
                    row["stay_date"],
                    row["room_type"],
                    row["nights_stayed"],
                    row["traveller_type"],
                    row["title"],
                    row["positive_text"] or "",
                    row["negative_text"] or "",
                    row["hotel_reply"] or "",
                    row["scraped_at"],
                    sentiment,
                    json.dumps(topics),
                    json.dumps(issue_topics),
                    json.dumps(praise_topics),
                ),
            )
        )
    for i in range(0, len(statements), 100):
        pipeline(statements[i : i + 100])

    after = query("SELECT COUNT(*) FROM reviews")[0][0]
    print(
        json.dumps(
            {
                "inserted": after - before,
                "already_present": len(source_rows) - len(missing),
                "skipped_name_variants": skipped_variants,
                "turso_total": after,
            }
        )
    )


if __name__ == "__main__":
    main()
