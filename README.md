# Azzurro Hotels — Booking.com Review Insights

A local operations dashboard for guest feedback across four Azzurro Hotels properties. It collects reviews visible on the public Booking.com property pages, stores them in SQLite, and provides searchable review browsing, rating trends, operational topic insights, corrective action tracking, and collection health monitoring.

## Submission contents

This repository includes the complete application source, installation and run instructions, architecture and collection notes, known limitations, and a small real-review sample at [`data/sample_reviews.csv`](data/sample_reviews.csv). The CSV contains one review captured from each property, with reviewer names and Booking review IDs omitted.

The full local review database is intentionally not included in GitHub. At the time this README was prepared, the local SQLite database contained 9,180 unique stored rows. That count is a local observation, not a claim that every review currently listed by Booking.com has been collected. The committed sample CSV is only an illustrative subset; it is not a substitute for the full database.

## Properties

| Dashboard property | Booking.com page |
| --- | --- |
| Olympic Hotel Paddington | [olympic-paddington](https://www.booking.com/hotel/au/olympic-paddington.html) |
| Potts Point | [venus-potts-point-sydney](https://www.booking.com/hotel/au/venus-potts-point-sydney.html) |
| Central Sydney | [venus-surry-hills](https://www.booking.com/hotel/au/venus-surry-hills.html) |
| Darling Harbour | [chateau-de-venus](https://www.booking.com/hotel/au/chateau-de-venus.html) |

## Requirements

- Python 3.10 or later
- Node.js 20 or later and npm
- Internet access to collect reviews
- Chromium installed through Playwright (the setup command below installs it)

No Booking.com API key or paid AI service is required. Booking.com may show a verification or anti-bot page; the collector does not bypass it.

## Setup and run locally

### 1. Set up the backend

In PowerShell, from the project root:

```powershell
cd "C:\path\to\azzurro-hotels"
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

If PowerShell blocks activating the virtual environment, run this in that terminal first:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

Start the API in this terminal:

```powershell
$env:AUTO_SCRAPE = "false"
python -m backend.run_api
```

The API is available at <http://127.0.0.1:8000>, interactive API documentation at <http://127.0.0.1:8000/docs>, and health check at <http://127.0.0.1:8000/api/health>.

### 2. Set up and start the frontend

Open a second PowerShell terminal:

```powershell
cd "C:\path\to\azzurro-hotels\frontend"
npm install
npm run dev
```

Open <http://127.0.0.1:5173>. Keep both terminals running. Vite forwards `/api` requests to the backend on port 8000. If the frontend reports `ECONNREFUSED 127.0.0.1:8000`, start or restart the backend terminal.

The API creates its local database at `data/reviews.sqlite3` by default. To use another path, set `AZZURRO_DB` before starting the API. The API can also start incremental collection automatically; set `AUTO_SCRAPE=false` as above to disable this behavior. When enabled, its interval defaults to 12 hours and can be changed with `SCRAPE_INTERVAL_HOURS`.

### 3. Collect reviews

From the repository root, with the virtual environment active:

```powershell
# Incremental update (default)
python -m backend.scraper.run_scraper

# Full accessible-page backfill
python -m backend.scraper.run_scraper --mode full

# Limit a run to one property
python -m backend.scraper.run_scraper --mode incremental --property venus-potts-point-sydney

# Bound a run while diagnosing source changes
python -m backend.scraper.run_scraper --mode full --property chateau-de-venus --max-pages 3
```

The dashboard's **Refresh reviews** control can also trigger an incremental run through the API. Collection is resumable: saved review rows remain in SQLite if a run stops, and duplicate rows are skipped on later runs.

If you need to complete a Booking.com verification yourself, use a visible browser session in the terminal where you run the scraper:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.playwright"
$env:BOOKING_HEADLESS = "false"
$env:BOOKING_STORAGE_STATE = "data/booking-state.json"
python -m backend.scraper.run_scraper --mode full
```

Complete any prompt in the opened browser. Keep the browser open while the scraper waits. Do not share `data/booking-state.json`: it can contain session cookies. You can set `BOOKING_VERIFICATION_TIMEOUT_SECONDS` to change the wait (up to the configured maximum). A headless or unattended run may stop when a verification page appears; check the collection run history and per-property status rather than treating process startup as proof of a successful collection.

## Dashboard features

- **Review Insights:** current and previous week rating comparison, period filters, property performance, positive and negative trends, operational topics, key takeaways, and a review feed with pagination, search, sorting, sentiment and topic filters.
- **Operations & Actions:** recurring negative topic signals, review evidence, and persistent corrective tasks that can be assigned and tracked.
- **Automation & Impact:** per-property collection coverage and backfill status, scrape history and errors, source listing totals/scores when observed, freshness, and before/after descriptive comparisons for completed actions.
- Date and property filters narrow the review feed and associated analytics. API-backed screens refresh periodically; the Review Insights dashboard polls for newly stored rows.

## Architecture

```text
Booking.com property pages
          │
          ▼
Playwright collector (backend/scraper/run_scraper.py)
          │ parsed reviews, listing metadata, run results
          ▼
SQLite database (data/reviews.sqlite3)
          │
          ├── FastAPI analytics and operations API (backend/api/main.py)
          └── React + Vite operations dashboard (frontend/src/)
```

- `backend/scraper/` loads property review pages, inspects review-related JSON responses and visible review cards, follows available pagination, retries temporary failures, and records scrape results.
- `backend/db.py` initializes the SQLite schema, indexes and uniqueness constraints. Each saved review has a stable source identity where available.
- `backend/analytics/classify.py` computes sentiment and operational topic tags using transparent local rules.
- `backend/api/main.py` exposes review, analytics, collection status, and corrective action endpoints.
- `frontend/src/App.jsx`, `Operations.jsx`, and `Automation.jsx` implement the three dashboard workspaces; shared styling is in the CSS files in `frontend/src/`.

## Review collection method and data quality

Booking.com API access is not assumed. The collector uses Playwright to load the four public property pages and reads review-like records exposed in page network JSON and rendered review cards. It follows the page's available next-page control and stores the review date, rating, property, title, positive/negative comment text and other available fields. It also records relevant listing totals/scores when those are visible. The public listing snapshot in [`data/booking-source-snapshot.json`](data/booking-source-snapshot.json) is dated source context, not a live feed.

Duplicate protection uses a unique `(property_slug, review_id)` constraint when a Booking review ID is available. A deterministic content hash is used as a fallback identity when it is not. This can merge genuinely identical reviews or miss edits when source identifiers are unavailable. Each completed page is committed promptly so interruptions retain collected rows.

Coverage is measured against the latest observed Booking.com listing total where available. Listing totals can change, some reviews may not be exposed in accessible page responses, and Booking.com can change its page structure or restrict automated access. Therefore **stored count is not proof of complete collection**. The monitor shows accessible/observed coverage and run errors; a full backfill is only marked complete when the available scope has been traversed without collection errors. Some historical reviews may be score-only or otherwise inaccessible as public review cards.

The collector does not declare reviews “fake” or delete them based on text heuristics. Public review pages do not provide a dependable authenticity signal; suspected spam requires source or human verification. Review text is public page content, but the sample export omits reviewer names and review IDs. The local session state and complete database are excluded from this repository.

## Insights and classification methodology

Sentiment uses ratings as the main signal: ratings of 8 or higher are positive, below 6 are negative, and 6–7.9 are neutral. For the middle band, a small local positive/negative word check may adjust a label when the text polarity is strong. A review without a usable rating is not given an invented score.

Keyword dictionaries assign operational topics such as cleanliness, check-in, staff, noise, facilities, location, room condition, and value for money. Reviews may receive multiple tags. Issue analysis uses negative comment text; praise analysis uses positive comment text. Shares are descriptive counts over the selected, collected reviews, not causal claims. Keyword rules can miss multilingual phrasing, sarcasm, negation, context, and synonyms, or assign a topic incorrectly. Treat the results as leads for staff review rather than definitive measurements.

Business Impact compares the same-length windows before and after an action's completion date using available review volume, negative rate, topic mentions, and mean rating. It describes a change over time; it cannot establish that the action caused the change.

## API endpoints

- `GET /api/health`
- `GET /api/overview`
- `GET /api/properties`
- `GET /api/trends?interval=week|day`
- `GET /api/topics`
- `GET /api/reviews?page=1&page_size=25&sort=newest|oldest|highest|lowest&q=...&property=...&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&sentiment=...&topic=...`
- `POST /api/scrape/trigger?mode=incremental|full`, `GET /api/scrape/status`
- `GET /api/operations?property=all&days=30`
- `GET /api/actions`, `POST /api/actions`, `PATCH /api/actions/{id}`
- `GET /api/automation`

Most analytics and review routes accept date and property filters; the review feed also accepts sentiment and topic. Review results are paginated and return total counts so a client can browse beyond the first page.

## Tests and production status

Run the backend regression tests and Python syntax check from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q backend tests
```

Build the frontend:

```powershell
cd frontend
npm run build
```

The project has been configured and exercised as a local application. This repository does **not** include a hosted demo or deployment configuration. A production deployment needs a persistent API/worker host, durable storage, environment-specific CORS configuration, and a supported process for any human verification. Do not deploy SQLite on an ephemeral serverless filesystem. For multiple API/worker instances, use PostgreSQL and a single scheduled collection worker. Public availability of a deployment also depends on source-site terms and access restrictions.

## Security and files to keep local

Never commit Booking credentials or browser cookies/session state. The `.gitignore` excludes the database, database journal files, session state, environment secrets, virtual environments, browser binaries/cache, frontend dependencies and build output. Do not force-add these files. In particular, keep these local:

- `data/reviews.sqlite3` and its `-wal` / `-shm` files
- `data/booking-state.json`
- `.env` files containing secrets
- `.venv/`, `frontend/node_modules/`, `frontend/dist/`, and `.playwright/`

The included `data/sample_reviews.csv` is a small real-data sample from the local collection, with reviewer names and source review IDs removed. It is not the complete review database. Back up the local database before migrations or maintenance.

## Repository layout

```text
backend/
  analytics/       sentiment and operational topic rules
  api/             FastAPI routes and application lifecycle
  scraper/         Playwright collector and CLI
  db.py            SQLite schema and persistence
  run_api.py       API entry point
data/
  booking-source-snapshot.json   dated observed listing context
  sample_reviews.csv              small anonymized real-review sample
  reviews.sqlite3                generated local database (not committed)
frontend/
  src/             React dashboard views and styles
  package.json     frontend scripts and dependencies
tests/             backend regression tests
README.md
requirements.txt
PROJECT_AUDIT_AND_DEPLOYMENT_REPORT.md
```
