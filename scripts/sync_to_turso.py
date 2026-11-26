"""Sync newly collected reviews from the working backfill database into Turso.

The Booking.com collection runs externally (browser-based extraction into
~/workspace/azzurro-hotels-dashboard/data/reviews.db). This script pushes any
reviews that are not yet in the hosted Turso database, using the same
content-hash key the repo's scraper uses (sha256 of
slug|reviewer|date|title|positive|negative), records the collection run in
scraper_runs, and refreshes property_source_state — so the hosted
dashboard's Automation page reflects the real, external collection.

Credentials come from the environment or the gitignored .turso-env file
next to the repo root. Usage:
    .venv/bin/python scripts/sync_to_turso.py [--dry-run]
"""
import base64, hashlib, json, os, sqlite3, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE_DB = Path.home() / "workspace" / "azzurro-hotels-dashboard" / "data" / "reviews.db"
PROGRESS = Path.home() / "workspace" / "azzurro-hotels-dashboard" / "data" / "import" / "progress.json"
BATCH = 100

def load_env():
    env_file = ROOT / ".turso-env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())
    url = os.environ["TURSO_DATABASE_URL"].rstrip("/")
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    return url + "/v2/pipeline", os.environ["TURSO_AUTH_TOKEN"]

ENDPOINT, TOKEN = load_env()

def encode(value):
    if value is None: return {"type": "null"}
    if isinstance(value, bool): return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int): return {"type": "integer", "value": str(value)}
    if isinstance(value, float): return {"type": "float", "value": value}
    if isinstance(value, bytes): return {"type": "blob", "value": base64.b64encode(value).decode()}
    return {"type": "text", "value": str(value)}

def decode(cell):
    kind = cell["type"]
    if kind == "null": return None
    if kind == "integer": return int(cell["value"])
    if kind == "float": return float(cell["value"])
    if kind == "blob": return base64.b64decode(cell["value"])
    return cell["value"]

def pipeline(statements):
    body = {"requests": [
        {"type": "execute", "stmt": {"sql": sql, "args": [encode(a) for a in args]}}
        for sql, args in statements
    ] + [{"type": "close"}]}
    request = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read())
    out = []
    for item in payload["results"]:
        if item["type"] == "error":
            raise RuntimeError(item["error"]["message"])
        if item["response"].get("type") != "execute":
            continue
        result = item["response"]["result"]
        rows = [tuple(decode(c) for c in raw) for raw in result["rows"]]
        out.append({"rows": rows, "affected": result.get("rows_affected", 0),
                    "last_id": result.get("last_insert_rowid")})
    return out

def execute(sql, args=()):
    return pipeline([(sql, args)])[0]

def content_hash(slug, name, date, title, pos, neg):
    fields = [str(v or "") for v in (slug, name, date, title, pos, neg)]
    return hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()

def main():
    dry_run = "--dry-run" in sys.argv
    from backend.analytics.classify import classify, classify_issue_topics, classify_praise_topics
    from backend.db import PROPERTIES

    # What is already in Turso. Identity = (property, reviewer, date): the
    # hosted rows glue country onto the name ("Justine\nAustralia"), so the
    # name is normalised to its first line before comparing.
    def identity(slug, name, date):
        first_line = (name or "").split("\n")[0]
        return (slug, " ".join(first_line.split()).lower(), date)
    present = set()
    stored_keys = set()
    offset = 0
    while True:
        rows = execute("SELECT property_slug,reviewer_name,review_date,review_key "
                       "FROM reviews ORDER BY id LIMIT 1000 OFFSET ?", (offset,))["rows"]
        if not rows: break
        for slug, name, date, key in rows:
            present.add(identity(slug, name, date))
            stored_keys.add(key)
        offset += len(rows)
    print(f"Turso currently holds {offset} reviews")

    source = sqlite3.connect(SOURCE_DB)
    source.row_factory = sqlite3.Row
    source_rows = source.execute("SELECT * FROM reviews ORDER BY scraped_at").fetchall()
    new_rows, duplicates = [], 0
    for r in source_rows:
        if identity(r["property_slug"], r["reviewer_name"], r["review_date"]) in present or r["dedup_hash"] in stored_keys:
            duplicates += 1
            continue
        sentiment, topics = classify(r["rating"], r["positive_text"], r["negative_text"])
        new_rows.append((
            r["dedup_hash"], r["dedup_hash"], r["property_slug"], r["property_name"],
            r["reviewer_name"] or "", r["reviewer_country"] or "", r["rating"], r["review_date"],
            r["stay_date"], r["room_type"], r["nights_stayed"], r["traveller_type"], r["title"],
            r["positive_text"] or "", r["negative_text"] or "", r["hotel_reply"] or "",
            r["scraped_at"], sentiment, json.dumps(topics),
            json.dumps(classify_issue_topics(sentiment, r["negative_text"])),
            json.dumps(classify_praise_topics(sentiment, r["positive_text"]))))
        present.add(identity(r["property_slug"], r["reviewer_name"], r["review_date"]))
    print(f"source: {len(source_rows)} collected, {duplicates} already in Turso, {len(new_rows)} new")
    if dry_run:
        print("dry run — nothing written")
        return

    count_before = execute("SELECT COUNT(*) FROM reviews")["rows"][0][0]
    insert_sql = ("INSERT OR IGNORE INTO reviews(review_id,review_key,property_slug,property_name,reviewer_name,"
                  "reviewer_country,rating,review_date,stay_date,room_type,nights_stayed,traveller_type,title,"
                  "positive_text,negative_text,hotel_reply,scraped_at,sentiment,topics,issue_topics,praise_topics) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    for start in range(0, len(new_rows), BATCH):
        pipeline([(insert_sql, row) for row in new_rows[start:start + BATCH]])
    count_after = execute("SELECT COUNT(*) FROM reviews")["rows"][0][0]
    inserted = count_after - count_before
    print(f"inserted {inserted} reviews into Turso")

    # Record the external collection run honestly: window = when the reviews
    # were actually collected; pages = dialog pages the backfill has covered.
    started = min(r["scraped_at"] for r in source_rows)
    finished = max(r["scraped_at"] for r in source_rows)
    pages = 0
    header_totals = {}
    if PROGRESS.exists():
        progress = json.loads(PROGRESS.read_text())
        for slug, info in progress.get("bookingcom_totals", {}).items():
            pages += info.get("extracted_pages", 0) or 0
            if info.get("header_total"):
                header_totals[slug] = info["header_total"]
    run = execute("INSERT INTO scraper_runs(mode,property_slug,started_at,finished_at,status,new_reviews,duplicates_skipped,pages,errors) "
                  "VALUES(?,?,?,?,?,?,?,?,?)",
                  ("incremental", None, started, finished, "completed", inserted, duplicates, pages, ""))
    run_id = run["last_id"]
    observed_at = datetime.fromtimestamp(PROGRESS.stat().st_mtime, timezone.utc).isoformat(timespec="seconds") if PROGRESS.exists() else finished
    for slug in PROPERTIES:
        execute("INSERT OR IGNORE INTO property_source_state(property_slug) VALUES(?)", (slug,))
        if slug in header_totals:
            execute("UPDATE property_source_state SET latest_run_id=?,latest_run_mode=?,latest_run_started_at=?,latest_run_finished_at=?,"
                    "latest_run_status=?,latest_run_pages=?,last_success_at=?,last_error=NULL,booking_total_reviews=?,source_observed_at=?,source_method=? "
                    "WHERE property_slug=?",
                    (run_id, "incremental", started, finished, "completed", pages, finished,
                     header_totals[slug], observed_at, "External browser collection (dialog + listing header)", slug))
        else:
            execute("UPDATE property_source_state SET latest_run_id=?,latest_run_mode=?,latest_run_started_at=?,latest_run_finished_at=?,"
                    "latest_run_status=?,latest_run_pages=?,last_success_at=?,last_error=NULL WHERE property_slug=?",
                    (run_id, "incremental", started, finished, "completed", pages, finished, slug))
    total = execute("SELECT COUNT(*) FROM reviews")["rows"][0][0]
    print(f"run #{run_id} recorded; Turso now holds {total} reviews")

if __name__ == "__main__":
    main()
