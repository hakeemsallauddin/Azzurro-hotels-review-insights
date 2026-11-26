# Azzurro Hotels project audit and readiness report

Audit date: 26 November 2026 (local environment date). This report describes the code and data inspected in the existing project. It does not claim a public deployment or complete historical collection.

## Executive summary

The local project contains a React/Vite dashboard, FastAPI API, Playwright collector, SQLite warehouse, four configured Booking.com properties, deterministic sentiment/topic tagging, stored operations actions, and collection/impact reporting. The local SQLite database contains 9,178 real collected rows and no database duplicates under either uniqueness key. The latest recorded sync (#21) completed successfully, finding 40 already stored reviews across four pages and adding none.

Collection is still partial against the dated source snapshot: 9,178 rows versus 9,264 listing reviews, a gap of 86. That snapshot is not a live Booking.com count and a matching count alone would not establish that every source review was captured. The app must not claim full coverage. Two earlier full runs are in the run table, but the older per-property state did not retain their backfill fields; this audit updates Automation & Impact to surface the recorded full-run evidence without presenting the aggregate run page count as a property count.

The backend configured for port 8000 could not be started because the port is already occupied. A health request from this shell timed out. I did not terminate the unknown process. Consequently, production-database HTTP/API and live-browser end-to-end checks remain incomplete; direct route tests against an isolated test database, Python compilation, and the production frontend build passed.

## Architecture and source layout

```text
azzurro-hotels/
├── .gitignore
├── README.md
├── PROJECT_AUDIT_AND_DEPLOYMENT_REPORT.md
├── requirements.txt
├── backend/
│   ├── __init__.py
│   ├── db.py
│   ├── run_api.py
│   ├── analytics/
│   │   ├── __init__.py
│   │   └── classify.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── main.py
│   └── scraper/
│       ├── __init__.py
│       └── run_scraper.py
├── data/
│   ├── .gitkeep
│   ├── booking-source-snapshot.json
│   ├── reviews.sqlite3 (local only; ignored by Git)
│   ├── reviews.sqlite3-wal / reviews.sqlite3-shm (local only; ignored)
│   └── booking-state.json (local browser session; ignored)
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   ├── postcss.config.js
│   ├── tailwind.config.js
│   ├── vite.config.js
│   └── src/
│       ├── App.jsx
│       ├── Automation.jsx
│       ├── Operations.jsx
│       ├── enhanced.css
│       ├── main.jsx
│       └── styles.css
└── tests/
    └── test_project.py
```

The tree omits generated `node_modules`, `.venv`, Playwright browser binaries, Python caches and Vite `dist`. There was no Git repository or remote before this audit. A local Git repository and baseline commit were created; there is no remote and nothing was pushed. Because there was no prior Git history, historical create-versus-edit attribution for files from earlier work cannot be reconstructed. The files changed or added during this audit are listed below.

## Requirement-to-evidence checklist

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Four property collection | PASS | `backend/db.py` configures the four required Booking.com URLs and slugs. |
| Public review extraction | PARTIAL | `backend/scraper/run_scraper.py` listens for review JSON and parses visible cards; Booking page changes and access restrictions can prevent extraction. |
| Historical backfill | PARTIAL | 9,178 stored versus a dated snapshot of 9,264; 86 gap. Last recorded full runs did not close that gap. |
| Incremental sync | PASS (latest recorded run) | Run #21: 26 Nov 2026 08:27:32–08:28:47 UTC; completed, 4 pages, 0 new, 40 duplicates, no errors. |
| Duplicate prevention | PASS for database constraints | Unique constraints on `(property_slug, review_id)` and `review_key`; read-only audit found 0 repeated keys and 0 repeated property/source-ID pairs. |
| Fake review removal | NOT CLAIMED | Public review text alone does not establish authenticity. The app does not label or delete reviews as fake. |
| Rating/date/property fields | PARTIAL | Columns and parsers exist; the database audit found 0 null ratings and 0 null review dates among its 9,178 rows. This does not prove every source card or metadata field was captured. |
| Review feed and pagination | PASS in implementation; live HTTP unverified | `/api/reviews` supports pages up to 100, text search, sort, date/property/sentiment/topic filters and total counts; frontend uses server paging. |
| Current/previous week ratings | PASS in implementation; covered by API fixture test | Weekly windows are Monday-based in Sydney time and use stored review ratings. |
| Property rating breakdown | PASS in implementation | `/api/properties` returns actual stored counts, rating averages, weekly comparisons and issue/praise topics for all four configured properties. |
| Date/property filters | PASS in implementation; covered by API fixture test | Shared SQL filter builder is used by overview/trends/topics/reviews; property breakdown accepts both filters. |
| Positive/negative trends | PASS in implementation | `/api/trends` returns counts and rating averages per day/week; sentiment derives from stored ratings/text. |
| Eight operational topics | PASS for configured taxonomy | Cleanliness, check-in experience, staff behaviour, noise, facilities, location, room condition and value for money are configured and tested. |
| Dynamic insight calculations | PASS in implementation | Overview/operations endpoints derive topic counts and percentages from distinct real database review IDs; percentage denominators are explicit. Keyword classification can miss context, negation, sarcasm and multilingual text. |
| Recurring issues and praise | PASS in implementation | `/api/operations` returns topic counts, property spread and stored excerpts for selected rolling date range. |
| Actions and assignment/status | PARTIAL | Persistent actions have create/list/update APIs and frontend controls; live HTTP interaction was not verified because the API could not be reached. |
| Business impact | PARTIAL | Equal-length pre/post windows are implemented, with pending states where data is absent; descriptive association is not causal evidence. Live HTTP check unavailable. |
| Scraper error/verification handling | PARTIAL | Collector records access failures and waits for user-completed verification in visible mode; no CAPTCHA or access control is bypassed. Booking may still restrict collection. |
| Collection monitor/backfill | PARTIAL | Snapshot coverage and successful-run freshness are separate. Historical per-property backfill metadata was absent; UI now surfaces the actual completed full-run record while the 86-row gap remains partial. |
| README / setup docs | PASS with local-only deployment notes | README documents architecture, local commands, collection constraints, dedupe, classification, API, tests and hosted persistence requirements. |
| Automated backend regression tests | PASS | 6 `unittest` tests pass using temporary SQLite databases. They do not touch `data/reviews.sqlite3`. |
| Python compilation | PASS | `python -m compileall -q backend tests`. |
| Production frontend build | PASS with warning | `npm run build` succeeds. Vite warns `chart-vendor` is 550.73 kB minified; `react-vendor` is an empty chunk. |
| Live API verification | BLOCKED | Starting the API on 127.0.0.1:8000 returned Windows error 10048 (port already in use). A request to `/api/health` timed out. I did not stop the existing listener. |
| GitHub readiness | PARTIAL / prepared locally | Local repository initialized with a clean baseline commit; all 28 source/document files are included. No remote configured and no push performed. Local DB, WAL/SHM and browser state are excluded. |
| Public deployment | NOT DEPLOYED | No hosting account/configuration was supplied. Persistent worker/storage is required; no deployment manifest exists. No paid service was started. |

## Database and collection findings

Database path: `data/reviews.sqlite3` relative to this repository. The original 9,178 rows were checked read-only. Tables: `reviews`, `scraper_runs`, `scraper_state`, `property_source_state`, and `action_tasks`. Review date range: 25 Nov 2023 through 25 Nov 2026; mean review rating 7.637/10. The reviewed table has uniqueness indexes for review key and property/source ID plus indexes for date, property/date, rating, sentiment and reviewer.

| Property | Stored rows | Dated listing snapshot | Difference |
|---|---:|---:|---:|
| Olympic Hotel Paddington | 127 | 129 | 2 |
| Potts Point | 2,359 | 2,385 | 26 |
| Central Sydney | 2,434 | 2,445 | 11 |
| Darling Harbour | 4,258 | 4,305 | 47 |
| **Total** | **9,178** | **9,264** | **86** |

The source snapshot records Booking scores 6.4, 6.2, 6.6 and 6.6, respectively, and was updated during the latest run on 26 Nov 2026. It is a point-in-time observation, not a live total. Runs #15 and #16 were full runs marked completed in `scraper_runs`: #15 (all properties) reported 8,038 new rows, 72 duplicates and 813 pages; #16 (Darling Harbour) reported 1,130 new rows, 3,175 duplicates and 431 pages. The currently stored totals remain short of the snapshot. No full backfill was started during this audit because another scrape may encounter a verification gate and the user should complete such checks in the visible browser.

The latest incremental run is successful; runs #17 and #18 reported Booking verification with no reviews collected, and #19/#20 recorded false incomplete-coverage warnings because the lifetime listing total was compared with the ten-card incremental page. The scraper was corrected so only a requested full backfill is compared with that lifetime total. The database run table still retains historical errors; it was not edited to erase them.

## Implemented behavior and important functions

- `backend/db.py`: `connect()` enables SQLite WAL and foreign keys; `init_db()` creates schema/indexes, ensures old classification fields are backfilled, and imports dated source snapshot metadata. This audit fixed the migration check so it remembers missing columns before adding them and recalculates sentiment and all topic fields for legacy rows.
- `backend/analytics/classify.py`: `classify`, `classify_issue_topics`, and `classify_praise_topics` provide deterministic rating/text sentiment and multi-label topic detection. Complaints use negative text; praise uses positive text.
- `backend/scraper/run_scraper.py`: `collect_property`, `save_review`, `review_hash`, `from_payload`, `flatten_reviews`, `wait_for_manual_verification`, and `run` implement JSON/DOM extraction, pagination, incremental duplicate stopping, immediate row commits, run recording and user-mediated verification. No fake-review heuristic is used.
- `backend/api/main.py`: endpoints cover health, overview, properties, trends, topics, reviews, scrape status/trigger, operations, actions and automation. Overview includes the compact operational takeaways (negative issue share, friction point, praise driver, property leader/laggard and week-over-week movement). The automation route now falls back to the actual completed full run when legacy per-property full-backfill state is empty.
- `frontend/src/App.jsx`: review dashboard, property/date/sentiment/topic/search/sort/page controls, review feed and linked takeaways.
- `frontend/src/Operations.jsx`: recurring issue/praise summaries with review evidence and stored action tracking.
- `frontend/src/Automation.jsx`: scrape freshness, snapshot coverage, backfill state, run history and action impact. The full-backfill row identifies whether evidence came from a property run or an all-properties run.
- `frontend/src/styles.css` and `frontend/src/enhanced.css`: app and compact highlighted operational insight styling.

## Files changed or added during this audit

- Modified `.gitignore`: ignore SQLite WAL/SHM sidecars and `.env.*` while retaining the safe `.env.example` exception.
- Modified `backend/db.py`: repair legacy classification migration and backfill sentiment/topic columns.
- Modified `backend/api/main.py`: attach the latest successful full-run evidence from run history when per-property legacy metadata is absent.
- Modified `frontend/src/Automation.jsx`: show the real full-run scope and avoid presenting aggregate all-properties pages as property-level page counts.
- Modified `README.md`: add isolated test commands and honest local/hosted deployment requirements.
- Added `tests/test_project.py`: six isolated tests for topic coverage/classification, insert/dedupe behavior, API filtering and analytics, full-run evidence fallback, legacy schema migration, and scraper finalizer database queries.
- Added this report.

Earlier work present in the audited source includes the visible-browser verification wait, full-only listing coverage check, overview takeaways, verification status handling and compact insight styling. Since no Git history existed before initialization, there is no prior diff from which to independently reconstruct the exact earlier edit set.

## Dependencies and Git status

No dependency was added or removed. Python dependencies remain in `requirements.txt`; frontend dependencies and lockfile are already present. No TypeScript is used. No imports were removed; the audit added `asyncio` and standard-library test imports in the test module.

A local Git repository was initialized on `main` with a baseline commit containing 28 source and documentation files. The following remain ignored: `.venv`, `node_modules`, generated build output, SQLite database and sidecars, Booking browser state, environment files and caches. There is no Git remote and no push. Review the committed files and configure the intended remote before publishing. Do not add the browser-state JSON or SQLite database to a public repository.

## Errors and unresolved work

- Resolved: legacy schema migration skipped classification backfill after adding the columns; fixed and covered by a legacy database test.
- Resolved: incremental crawls were incorrectly reported incomplete when they visited only the newest page; the lifetime listing comparison now applies only to full backfills.
- Resolved: the Automation page hid recorded older full-run evidence when `property_source_state` was introduced later; it now surfaces the actual scope and timestamp.
- Not resolved here: port 8000 is occupied (Windows 10048); the health request timed out from this shell. Identify the owning process in the user's terminal, stop/restart it only if it is the old Azzurro API, then restart with `AUTO_SCRAPE=false` before verifying the changed API/UI. No unknown process was terminated.
- Not resolved: 86-row snapshot gap. A fresh permitted full backfill and per-property comparison is required. If Booking shows a verification check, the operator must complete it in the visible browser. A scrape cannot prove that inaccessible or unlisted records were collected.
- Not resolved: live browser interaction, viewport testing, frontend console/network verification, action creation/update over HTTP, and full scraper run were not performed in this audit.
- Not resolved: chart bundle warning and empty React vendor chunk. Build is successful; consider code splitting charts if performance requirements demand it.
- Not resolved: public deployment. Use persistent storage and a persistent Playwright-capable worker; a serverless ephemeral filesystem will not preserve the SQLite warehouse. A multi-instance deployment should use PostgreSQL and a single scheduled worker.

## Follow-up after the initial audit

During a full run (#22, started 26 Nov 2026 at 09:22:17 UTC), Olympic Hotel Paddington scanned 13 pages/129 candidate cards, then its per-property finalizer failed with `NameError: name 'scalar' is not defined`. This was a code defect after page collection, not a Booking verification response. The collector saves each review as it is read, so a finalizer error does not roll back already committed review rows. Potts Point was still actively scanning when checked. The run process had already imported the old Python module; the fix below applies to new scraper processes, not the running process.

Fixed `backend/scraper/run_scraper.py` by adding `db_scalar()` using the existing SQLite connection helper and calling it from the full-backfill finalizer. Added a regression test for that query. The suite now passes all six tests, and Python compilation passes. Let the active run finish; a subsequent full run is needed to verify the corrected per-property finalizer and update backfill state without this false failure. The current run’s review rows remain saved; the historical failed status is retained in run history.

## Suggested next local verification

First identify the process that owns port 8000 from PowerShell. If it is an old Azzurro API instance, stop that specific process and restart the backend from the project root:

```powershell
cd "C:\Users\salla\Documents\Codex\2026-11-25\usi\outputs\azzurro-hotels"
$env:AUTO_SCRAPE = "false"
$env:BOOKING_HEADLESS = "false"
$env:BOOKING_STORAGE_STATE = "data/booking-state.json"
.\.venv\Scripts\python.exe -m backend.run_api
```

Keep the frontend running in a second terminal from `frontend` with `npm run dev`. Confirm `/api/health` reports 9,178 reviews, refresh the browser, and inspect Automation & Impact for the historical full-run evidence and partial 86-row snapshot gap. Start a full scrape only when ready to complete any legitimate Booking verification in the visible browser.

After reviewing the local commit and selecting a GitHub remote, the user can publish with their intended remote URL, for example:

```powershell
git remote add origin <your-repository-url>
git diff --check
git push -u origin main
```

No GitHub push, public deployment or paid service was performed.
