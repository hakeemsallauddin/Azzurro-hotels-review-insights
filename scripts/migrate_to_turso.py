"""One-time copy of the shipped review snapshot into the Turso database.

Talks to Turso over its HTTP pipeline API (the same data the app reads),
so it works from networks where the libsql WebSocket transport is blocked.

Usage (credentials come from the environment, never from files):
    TURSO_DATABASE_URL=https://<db-host> TURSO_AUTH_TOKEN=... \
        .venv/bin/python scripts/migrate_to_turso.py

Reads data/reviews-public.sqlite3, recreates its schema in Turso, and
copies every table in batches, preserving ids. Safe to re-run: tables
are cleared before copying.
"""
import base64, json, os, sqlite3, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "data" / "reviews-public.sqlite3"
TABLES = ["reviews", "scraper_runs", "scraper_state", "property_source_state", "action_tasks"]
BATCH = 100

BASE = os.environ["TURSO_DATABASE_URL"].rstrip("/")
if BASE.startswith("libsql://"):
    BASE = "https://" + BASE[len("libsql://"):]
ENDPOINT = BASE + "/v2/pipeline"
TOKEN = os.environ["TURSO_AUTH_TOKEN"]

def encode(value):
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

def decode(cell):
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
    body = {"requests": [
        {"type": "execute", "stmt": {"sql": sql, "args": [encode(a) for a in args]}}
        for sql, args in statements
    ] + [{"type": "close"}]}
    request = urllib.request.Request(
        ENDPOINT, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read())
    results = []
    for item in payload["results"]:
        if item["type"] == "error":
            raise RuntimeError(item["error"]["message"])
        if item["response"].get("type") != "execute":
            continue
        result = item["response"]["result"]
        rows = [tuple(decode(cell) for cell in raw) for raw in result["rows"]]
        results.append(rows)
    return results

def execute(sql, args=()):
    return pipeline([(sql, args)])[0]

def main():
    source = sqlite3.connect(SOURCE)
    # Recreate the schema exactly as shipped in the snapshot.
    schema = source.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type DESC"
    ).fetchall()
    idempotent = []
    for (statement,) in schema:
        statement = (statement
                     .replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
                     .replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ", 1)
                     .replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1))
        idempotent.append((statement, ()))
    pipeline(idempotent)
    print(f"schema applied: {len(schema)} statements")
    for table in TABLES:
        columns = [row[1] for row in source.execute(f"PRAGMA table_info({table})")]
        rows = source.execute(f"SELECT * FROM {table}").fetchall()
        execute(f"DELETE FROM {table}")
        placeholders = ",".join("?" * len(columns))
        sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
        for start in range(0, len(rows), BATCH):
            pipeline([(sql, tuple(row)) for row in rows[start:start + BATCH]])
        count = execute(f"SELECT COUNT(*) FROM {table}")[0][0]
        print(f"{table}: copied {len(rows)}, in Turso now {count}", flush=True)
    print("Migration complete.")

if __name__ == "__main__":
    main()
