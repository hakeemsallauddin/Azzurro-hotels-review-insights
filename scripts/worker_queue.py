"""Queue helper for the external collection worker.

The hosted dashboard queues collection runs (scraper_runs rows with
status 'queued') because Booking.com blocks collection from the hosted
server itself. The external worker polls this helper, performs the
collection in a browser session Booking.com serves, syncs the results
with scripts/sync_to_turso.py, and finalizes the run here so the
dashboard shows the real outcome.

Usage:
  python scripts/worker_queue.py next
      -> {"run": {"id": N, "mode": "incremental"|"full", "started_at": ...}} or {"run": null}
  python scripts/worker_queue.py start <run_id>
      -> marks a queued run as 'running' (worker has picked it up)
  python scripts/worker_queue.py progress <run_id> <pages> <new> <dupes>
      -> updates counters on a still-running (full) run
  python scripts/worker_queue.py complete <run_id> <new> <dupes> <pages>
      -> marks the run completed and refreshes every property's
         collection state (latest attempt, last success, source date)

Credentials: TURSO_DATABASE_URL / TURSO_AUTH_TOKEN or local .turso-env.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


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
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    return {"type": "text", "value": str(value)}


def dec(cell):
    kind = cell["type"]
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
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
    payload = json.loads(urllib.request.urlopen(req, timeout=180).read())
    out = []
    for item in payload["results"]:
        if item["type"] == "error":
            raise RuntimeError(item["error"]["message"])
        if item["response"].get("type") != "execute":
            continue
        result = item["response"]["result"]
        cols = [c["name"] for c in result["cols"]]
        out.append([dict(zip(cols, (dec(c) for c in row))) for row in result["rows"]])
    return out


def query(sql, args=()):
    return pipeline([(sql, args)])[0]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_sydney_iso() -> str:
    return datetime.now(ZoneInfo("Australia/Sydney")).isoformat(timespec="seconds")


def cmd_next() -> None:
    rows = query(
        "SELECT id, mode, started_at, status, pages, new_reviews, duplicates_skipped "
        "FROM scraper_runs WHERE status IN ('queued','running') ORDER BY id LIMIT 1"
    )
    print(json.dumps({"run": rows[0] if rows else None}))


def cmd_start(run_id: int) -> None:
    query("UPDATE scraper_runs SET status='running' WHERE id=? AND status='queued'", (run_id,))
    print(json.dumps({"run_id": run_id, "status": "running"}))


def cmd_progress(run_id: int, pages: int, new: int, dupes: int) -> None:
    query(
        "UPDATE scraper_runs SET pages=?, new_reviews=?, duplicates_skipped=? WHERE id=?",
        (pages, new, dupes, run_id),
    )
    print(json.dumps({"run_id": run_id, "status": "running", "pages": pages, "new": new, "dupes": dupes}))


def cmd_complete(run_id: int, new: int, dupes: int, pages: int) -> None:
    run = query("SELECT mode, started_at FROM scraper_runs WHERE id=?", (run_id,))[0]
    finished = now_utc()
    observed = now_sydney_iso()
    query(
        "UPDATE scraper_runs SET status='completed', finished_at=?, new_reviews=?, "
        "duplicates_skipped=?, pages=?, errors='' WHERE id=?",
        (finished, new, dupes, pages, run_id),
    )
    counts = {
        r["property_slug"]: r["n"]
        for r in query("SELECT property_slug, COUNT(*) n FROM reviews GROUP BY property_slug")
    }
    sources = query("SELECT property_slug, booking_total_reviews FROM property_source_state")
    statements = []
    for source in sources:
        slug = source["property_slug"]
        stored = counts.get(slug, 0)
        expected = source["booking_total_reviews"]
        backfill = (
            "complete" if expected is not None and stored >= expected else "partially_collected"
        )
        statements.append(
            (
                "UPDATE property_source_state SET latest_run_id=?, latest_run_mode=?, "
                "latest_run_started_at=?, latest_run_finished_at=?, latest_run_status='completed', "
                "latest_run_pages=?, latest_run_cards=?, last_success_at=?, last_error=NULL, "
                "source_observed_at=?, source_method='External collection worker (browser session)', "
                "backfill_status=? WHERE property_slug=?",
                (
                    run_id,
                    run["mode"],
                    run["started_at"],
                    finished,
                    pages,
                    stored,
                    finished,
                    observed,
                    backfill,
                    slug,
                ),
            )
        )
    if statements:
        pipeline(statements)
    print(
        json.dumps(
            {"run_id": run_id, "status": "completed", "new": new, "dupes": dupes, "pages": pages}
        )
    )


def main() -> None:
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    command = args[0]
    if command == "next":
        cmd_next()
    elif command == "start":
        cmd_start(int(args[1]))
    elif command == "progress":
        cmd_progress(int(args[1]), int(args[2]), int(args[3]), int(args[4]))
    elif command == "complete":
        cmd_complete(int(args[1]), int(args[2]), int(args[3]), int(args[4]))
    else:
        raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    main()
