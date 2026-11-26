# Azzurro Hotels — Booking.com Review Insights

Operations dashboard for collecting and understanding guest reviews across Olympic Hotel Paddington, Potts Point, Central Sydney, and Darling Harbour. The application stores collected reviews in SQLite (Turso when hosted) and provides a searchable review feed, property and date filters, weekly rating comparisons, positive and negative trends, operational topic insights, corrective action tracking, and collection monitoring.

## 1. Source code

The complete source repository is [Azzurro-hotels-review-insights](https://github.com/hakeemsallauddin/Azzurro-hotels-review-insights). It contains the Python/FastAPI backend, Playwright scraper, React/Vite dashboard, tests, documentation, a small real-review sample (`data/sample_reviews.csv`), and the full collected dataset: `data/reviews-public.sqlite3` holds all 9,180 collected reviews and seeds the working database on first run. Only the generated working database (`data/reviews.sqlite3`) and the Booking.com browser session state are local-only and are not committed.

## 2. Setup, usage, architecture, and limitations

### Setup and installation

Install Python 3.10+, Node.js 20+, and npm. From the project root, create the Python environment, install the backend dependencies, and install Playwright Chromium:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` in that terminal, then activate again. Start the API in the first terminal:

```powershell
$env:AUTO_SCRAPE = "false"
python -m backend.run_api
```

In a second terminal, install and start the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open <http://127.0.0.1:5173>. The API runs at <http://127.0.0.1:8000> and its interactive documentation is at <http://127.0.0.1:8000/docs>. Keep both terminals open. The default database is `data/reviews.sqlite3`; use `AZZURRO_DB` to change its location. A fresh clone does not contain `reviews.sqlite3` (it is local-only), so on first run it is seeded automatically by copying the shipped snapshot `data/reviews-public.sqlite3`. From then on there is a single working database: the scraper stores backfilled reviews in `data/reviews.sqlite3` and the dashboard serves that same file, so new reviews appear without any extra step. `AUTO_SCRAPE=false` disables automatic background scraping; otherwise the API starts incremental collection and repeats every 12 hours by default (`SCRAPE_INTERVAL_HOURS` changes the interval).

For production, build the frontend once (`cd frontend && npm run build`); the API then serves the built dashboard itself from the same port, so a single process hosts the whole application — this is how the public demo below runs.

### Running the scraper

Run commands from the repository root with the virtual environment active. An incremental run is appropriate for routine updates; a full run traverses all review pages accessible to the current session:

```powershell
python -m backend.scraper.run_scraper
python -m backend.scraper.run_scraper --mode full
python -m backend.scraper.run_scraper --mode incremental --property venus-potts-point-sydney
```

The dashboard's **Refresh reviews** button also starts an incremental run. If Booking.com presents a human verification page, use a visible browser session and complete the check yourself; the collector waits and resumes, but does not bypass the check:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.playwright"
$env:BOOKING_HEADLESS = "false"
$env:BOOKING_STORAGE_STATE = "data/booking-state.json"
python -m playwright install chromium
python -m backend.scraper.run_scraper --mode full
```

Do not share `data/booking-state.json`, which may contain session cookies. Review run outcomes in the dashboard or at `GET /api/scrape/status`. A run starting or exiting successfully does not prove that every source review was accessible.

### Architecture and collection method

```mermaid
flowchart LR
    B[Booking.com property pages] -->|HTML, review cards, page JSON| S[Python + Playwright scraper]
    S -->|deduplicated reviews and run history| DB[(SQLite / Turso database)]
    DB --> API[Python + FastAPI REST API]
    API --> UI[React dashboard + Vite]
    UI --> V1[Review Insights]
    UI --> V2[Operations & Actions]
    UI --> V3[Automation & Impact]
    API --> CL[Analytics and keyword classification]
    CL --> API
```

**Stack:** Python, Playwright, FastAPI, SQLite, React, Vite, JavaScript, and CSS. The scraper commits rows as it progresses and uses unique source IDs, with a deterministic content hash fallback, to avoid duplicate inserts. It collects review records exposed in page JSON responses or rendered review cards and follows available pagination.

Collection completeness depends on the content Booking.com exposes to the current session. The source site may change its page structure, restrict automated access, or show verification; inaccessible reviews cannot be collected by this application. The dashboard compares unique stored reviews with the latest observed listing total when available and reports gaps and run errors. It does not claim completeness from a matching count alone. The dated `data/booking-source-snapshot.json` is historical context, not a live total. The shipped snapshot `data/reviews-public.sqlite3` contains the 9,180 collected rows; the working database is generated from it on first run (see Setup).

### Insights and known limitations

Ratings drive sentiment labels: 8+ is positive, below 6 is negative, and 6–7.9 is neutral, with a small word-based check for strong text polarity in the middle band. Curated keyword dictionaries tag topics including cleanliness, check-in, staff, noise, facilities, location, room condition, and value for money. Negative issue mentions use negative comment text; praise uses positive comment text. These transparent rules can miss context, negation, sarcasm, and multilingual expressions or assign false matches. Insights are descriptive operational signals, not causal findings or formal staff assessments. The system does not automatically label reviews fake; authenticity cannot be reliably determined from the public page alone.

Business Impact compares equal-length review windows before and after a tracked action. It describes observed changes and cannot prove that the action caused them. Booking listing totals can change, some score-only reviews may have no accessible public review card, and collection may be interrupted by site restrictions.

### Tests

From the project root, run backend tests and the Python syntax check; build the frontend from its directory:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q backend tests
cd frontend
npm run build
```

## 3. Working application or demo

The local application is available at <http://127.0.0.1:5173> after completing the setup above and starting both services.

**Public demo: <https://azzurro-hotels-review-insights.onrender.com>** — the full dashboard (Review Insights, Operations & Actions, Automation & Impact) running this exact code. It is hosted on Render's free tier with the review database in a Turso (libSQL) cloud database, so the data persists while the service sleeps when idle (the first load after idle can take about a minute). The hosted instance runs with `AUTO_SCRAPE=false`: Booking.com serves a human-verification wall to datacenter IPs, so the web service cannot collect by itself. Instead, its collection buttons (Refresh reviews, Run incremental sync, Start full backfill) queue a run in the shared database, and an external collection worker — which collects through a browser session Booking.com serves — executes queued runs and writes the results back (`scripts/worker_queue.py`, `scripts/sync_to_turso.py`). On a local (SQLite) deployment, the same buttons run the scraper in-process as before. To run the API against Turso yourself, set `TURSO_DATABASE_URL` (the `https://` form) and `TURSO_AUTH_TOKEN`; without them it uses the local SQLite file. `scripts/migrate_to_turso.py` copies a local database into Turso.

For a self-hosted deployment, any host that can run the Python API works; keep the SQLite database on durable storage (or use Turso as above) and run collection from a single worker.

## 4. Sample review data

[`data/sample_reviews.csv`](data/sample_reviews.csv) contains four actual collected review records — one per property — with reviewer names and Booking review IDs omitted. The complete collected dataset ships in the repository as [`data/reviews-public.sqlite3`](data/reviews-public.sqlite3): 9,180 real reviews (Olympic Hotel Paddington 127, Potts Point 2,361, Central Sydney 2,434, Darling Harbour 4,258), including score-only ratings that have no public review text. On first run the application copies this snapshot to the working database `data/reviews.sqlite3`; the scraper then adds newly published reviews to that same file.

## Security

Do not commit Booking credentials, browser cookies, session state, or environment secrets. `.gitignore` excludes `data/reviews.sqlite3` and its journal files, `data/booking-state.json`, `.env` files, virtual environments, `frontend/node_modules/`, frontend build output, and Playwright browser files. Do not force-add these local files.
