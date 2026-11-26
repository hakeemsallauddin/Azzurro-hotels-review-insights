# Azzurro Hotels — Booking.com Review Insights

Operations dashboard and local review warehouse for the four Booking.com property pages in the brief. The repository contains **no seeded or fabricated reviews**. An empty dashboard is expected until live reviews are successfully collected.

## Requirements

- Python 3.10 or newer
- Node.js 20 or newer and npm
- Chromium installed through Playwright
- A network connection and a Booking.com page session that is permitted to access the property review pages

## Run locally

From this repository directory:

### Windows (PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m backend.scraper.run_scraper --mode full
python -m backend.run_api
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. On macOS/Linux, use `python3 -m venv .venv`, `source .venv/bin/activate`, and the same remaining commands. The API is at http://127.0.0.1:8000 and interactive docs at http://127.0.0.1:8000/docs.

For routine updates run `python -m backend.scraper.run_scraper` (incremental mode). Useful options:

```sh
python -m backend.scraper.run_scraper --mode full
python -m backend.scraper.run_scraper --mode incremental --property venus-potts-point-sydney
python -m backend.scraper.run_scraper --mode full --property chateau-de-venus --max-pages 3
```

If Booking displays a human verification page, a headless scheduled run records that limitation and stops instead of saving page controls as reviews. For manual verification, run the CLI in a visible browser. Complete the check yourself; the scraper waits and resumes automatically, so do not press Enter:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.playwright"
$env:AUTO_SCRAPE = "false"
$env:BOOKING_HEADLESS = "false"
$env:BOOKING_STORAGE_STATE = "data/booking-state.json"
$env:BOOKING_VERIFICATION_TIMEOUT_SECONDS = "300"
python -m playwright install chromium
python -m backend.scraper.run_scraper --mode full
```

To use the dashboard's **Refresh reviews** button for manual verification, set the same environment variables in the PowerShell window used to start the API, restart the API, and then click Refresh. The API passes these settings to the scraper process. The visible browser must remain open while you complete the check. The wait is limited to 5 minutes by default (configurable up to 30 minutes); no challenge is solved or bypassed automatically.

The local browser state file is ignored by Git. Do not share or commit it; it may contain session cookies.

The database is created at `data/reviews.sqlite3`; set `AZZURRO_DB` to use a different path. When the API starts, it performs an incremental scrape in the background and repeats every 12 hours by default. Set `AUTO_SCRAPE=false` to disable scheduled collection or `SCRAPE_INTERVAL_HOURS=6` to change the interval. The UI's Refresh reviews button can start an additional incremental scrape. `GET /api/scrape/status` reports the most recent run. The dashboard also reloads API data every 60 seconds so new database rows appear without a page reload.

## Architecture

- `backend/scraper/`: Playwright collector with per-property browser sessions, retry/backoff, delays, response JSON inspection and DOM-card fallback. Each review is committed immediately, so an interrupted full run retains collected rows and can be rerun.
- `backend/db.py`: SQLite schema, unique constraints and indexes for review date, property/date, rating and sentiment.
- `backend/analytics/`: deterministic rating/text sentiment and operational keyword topic tagging.
- `backend/api/`: FastAPI overview, property summary, trend, topic and server-paginated review endpoints, plus scrape trigger/status.
- `frontend/`: React/Vite operations workspace with separate Review Insights, Operations & Actions, and Automation & Impact views. The review feed is server-paginated and topic filters link insights back to individual reviews.
- `backend/api/`: FastAPI analytics plus persistent action tracking and collection health summaries.

## Collection, identity and completeness

Targets: Olympic Hotel Paddington, Potts Point, Central Sydney and Darling Harbour. The collector listens for JSON responses containing review-like objects while the page loads, and also parses visible review cards and follows the page's next control. Booking.com changes its frontend and may serve an anti-bot verification page or restrict automated collection. The collector does not bypass a challenge. Inspect `scraper_runs.errors`, logs, and per-property review counts to confirm the actual result; a successful process start is not proof that every review was accessible.

The database enforces uniqueness on `(property_slug, review_id)` and a second unique `review_key`. The native Booking review ID is preferred. When absent, `review_key` is SHA-256 over property slug, reviewer name, review date, title, positive text and negative text. The fallback is deterministic but can merge genuinely repeated identical text or fail to detect edits; source IDs are more reliable. On incremental runs, pagination stops after five consecutive duplicate cards. Full mode continues until no next page is exposed (or `--max-pages` is reached). Actual coverage depends on what Booking exposes to the session; no unsupported claim that all reviews were collected is made.

Duplicate prevention is automatic at insert time. The collector does not label or delete a review as fake: the public page does not expose a reliable authenticity signal, and text heuristics would risk deleting genuine guest feedback. Suspected spam or policy-violating content needs a human/source verification process before removal.

Automation & Impact separates the mean of collected review scores from Booking.com's property-level score. The tracked source snapshot in `data/booking-source-snapshot.json` records the listing totals and scores visible in the supplied Booking/dashboard screenshots on 26 Nov 2026; it is dated and is not treated as a current live feed. When a later scrape can read the Booking property page, the collector refreshes the listing total and official score from the page DOM. Coverage is calculated from stored unique rows versus that observed listing total. The dashboard reports the source observation date, missing-row gap, latest scrape error and full-backfill progress separately. It does not call a crawl complete merely because the process exited; a full crawl must reach the observed total without page or collection errors. If Booking blocks access, the status remains partial/blocked and needs a permitted visible browser session to resume.

Run exports only after a scrape has populated the database. This repo deliberately does not contain `sample_reviews.json` or CSV with invented rows. To inspect the full dataset, use `/api/reviews` with `page` and `page_size` (up to 100), or query SQLite. The API returns `total_count` and `total_pages` so clients can traverse all records.

## Classification methodology and limits

Ratings of 8+ are positive, below 6 negative and 6–7.9 neutral. For the middle band, a small transparent positive/negative word count may move sentiment when polarity is strong. Review text is never translated or sent to a paid service. Eight curated keyword dictionaries assign multiple operational topics. General topic tags cover both positive and negative comment text; negative issue insights are tagged only from the negative comment and positive praise only from the positive comment. Recurring issue cards include actual stored review excerpts and can open the matching feed. This remains keyword matching: context, sarcasm, multilingual text, and negation can still produce misses or false positives. Treat these summaries as operational signals for review, not formal staff-performance measurements.

The Collection Monitor reports freshness from each property's latest successful run, separately from a more recent blocked attempt; a fresh previous sync does not erase the failed attempt, which remains visible in the run history and property status. Business Impact compares the selected topic's negative-review mentions per 100 reviews, negative rate, and mean rating in equal-length windows before and after an action's completion date. It waits for a full post-action window with review data and is descriptive, not proof that an action caused any change.

Weekly insights are generated from records in the selected period. They are descriptive shares, not causal conclusions. Unknown dates and missing ratings remain missing instead of being inferred from dashboard examples.

## API

- `GET /api/overview`
- `GET /api/properties`
- `GET /api/trends?interval=week|day`
- `GET /api/topics`
- `GET /api/reviews?page=1&page_size=25&sort=newest|oldest|highest|lowest&q=...&property=...&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&sentiment=...&topic=...`
- `POST /api/scrape/trigger?mode=incremental|full`, `GET /api/scrape/status`
- `GET /api/operations?property=all&days=30` for recurring negative-topic signals and stored action tasks
- `GET|POST /api/actions`, `PATCH /api/actions/{id}` for persistent action tracking
- `GET /api/automation` for property collection history and adjacent 30-day portfolio comparisons
- `GET /api/health`

Date and property filters are supported on analytics and review endpoints. Sentiment and topic are supported on the review feed.

## Security and operations

No credentials, browser cookies, API keys, or Booking session storage are committed. `.gitignore` excludes the SQLite database, exports, environments and browser cache. The API binds to loopback by default; configure `CORS_ORIGINS` explicitly before exposing it beyond localhost. Back up `data/reviews.sqlite3` before migrations or operational maintenance.

## Tests and deployment readiness

Run the isolated backend regression tests and syntax check from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q backend tests
```

The tests use a temporary SQLite database and never seed or clear `data/reviews.sqlite3`. Build the frontend from its directory with `npm run build`.

This project is currently configured and verified as a local application, not a public deployment. The API launches Playwright as a child process and writes to SQLite, so a public deployment needs a persistent worker plus durable storage. Do not deploy the current SQLite database to an ephemeral serverless filesystem. A practical hosted setup is a persistent container/VM for the API and scraper with a mounted durable volume; for multiple API/worker replicas, migrate to PostgreSQL and move scheduled scraping to a single worker. Configure `CORS_ORIGINS`, the database path/connection, and any browser storage on the host. No deployment manifest or hosted service is included in this repository.
