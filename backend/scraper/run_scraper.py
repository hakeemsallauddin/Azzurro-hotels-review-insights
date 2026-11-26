"""Resumable Booking.com review collector. Use only where collection is permitted."""
from __future__ import annotations
import argparse, asyncio, hashlib, json, logging, os, random, re, time
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from backend.db import PROPERTIES, connect, init_db
from backend.analytics.classify import classify, classify_issue_topics, classify_praise_topics

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("azzurro.scraper")
VERIFICATION_RE = re.compile(r"verify\s+(?:that\s+)?(?:you(?:'|’)re|you are)\s+not\s+a\s+robot|human\s+verification|captcha|security\s+check|unusual\s+traffic|checking\s+your\s+browser", re.I)

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def slugify(value): return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
def norm_date(value):
    if not value: return None
    value = str(value).strip()
    value = re.sub(r"^(?:reviewed|posted|date)\s*:\s*", "", value, flags=re.I).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", value): return value[:10]
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%B %Y", "%B %d, %Y", "%d %b %Y"):
        try: return datetime.strptime(value, fmt).date().isoformat()
        except ValueError: pass
    return None
def review_hash(r, slug):
    fields = [str(value or "") for value in (slug, r.get("reviewer_name"), r.get("review_date"), r.get("title"), r.get("positive_text"), r.get("negative_text"))]
    return hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()

def update_property_source_state(slug, **fields):
    allowed={"booking_total_reviews","booking_overall_score","source_observed_at","source_method","latest_run_id","latest_run_mode","latest_run_started_at","latest_run_finished_at","latest_run_status","latest_run_pages","latest_run_cards","last_success_at","last_full_run_at","last_full_pages","last_full_cards","backfill_status","last_error"}
    fields={key:value for key,value in fields.items() if key in allowed}
    if not fields: return
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO property_source_state(property_slug) VALUES(?)",(slug,))
        db.execute("UPDATE property_source_state SET "+", ".join(f"{key}=?" for key in fields)+" WHERE property_slug=?",[*fields.values(),slug])

def listing_score_from_text(text):
    text=re.sub(r"\s+"," ",text or " ").strip()
    patterns=(r"(?:scored|rated)\s+(\d{1,2}(?:[.,]\d+)?)",r"^\s*(\d{1,2}(?:[.,]\d+)?)\s+(?:exceptional|wonderful|very good|good|pleasant|fair|poor|bad)\b")
    for pattern in patterns:
        match=re.search(pattern,text or "",re.I|re.M)
        if match:
            try:
                score=float(match.group(1).replace(",","."))
                if 0<=score<=10: return score
            except ValueError: pass
    return None

async def extract_listing_score(page, body):
    for selector in ("[data-testid='review-score-right-component']","[data-testid='review-score-component']"):
        try:
            text=await page.locator(selector).first.inner_text(timeout=900)
            score=listing_score_from_text(text)
            if score is not None: return score
        except Exception: pass
    return listing_score_from_text(body)

def is_verification_response(response, body):
    return bool((response and response.status in (202,403,429)) or VERIFICATION_RE.search(body or ""))

async def wait_for_manual_verification(page, name, timeout_seconds):
    """Wait for a user-completed site check; never attempt to solve or bypass it."""
    print(f"Booking.com verification appeared for {name}. Complete the check in the visible browser; collection will resume automatically (timeout {timeout_seconds}s).", flush=True)
    deadline=time.monotonic()+timeout_seconds
    while time.monotonic()<deadline:
        try:
            body=await page.locator("body").inner_text(timeout=4000)
        except Exception:
            body=""
        if not VERIFICATION_RE.search(body):
            try:
                response=await page.reload(wait_until="domcontentloaded",timeout=60000)
                body=await page.locator("body").inner_text(timeout=4000)
                if not is_verification_response(response,body):
                    return True
            except Exception as error:
                LOG.info("Waiting for Booking.com verification to clear (%s)",type(error).__name__)
        await page.wait_for_timeout(1500)
    return False

def flatten_reviews(obj):
    """Conservatively find review-like objects in changing JSON/XHR payloads."""
    found=[]
    def walk(x):
        if isinstance(x, dict):
            keys={str(k).lower() for k in x}
            if keys.intersection({"reviewid","review_id","reviewscore","reviewername","reviewtitle"}): found.append(x)
            for v in x.values(): walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
    walk(obj)
    return found

def from_payload(obj):
    def get(*keys):
        for key in keys:
            if obj.get(key) is not None: return obj[key]
        return ""
    def s(x):
        if isinstance(x, dict): return x.get("text", x.get("value", ""))
        return str(x or "").strip()
    score=get("reviewScore","review_score","rating","score")
    try: score=float(score)
    except (ValueError,TypeError): score=None
    return {"review_id":s(get("reviewId","review_id","id")), "reviewer_name":s(get("reviewerName","reviewer_name","author")),
      "reviewer_country":s(get("reviewerCountry","reviewer_country","country")), "rating":score,
      "review_date":norm_date(s(get("reviewDate","review_date","date"))), "stay_date":s(get("checkinDate","stayDate","stay_date")),
      "room_type":s(get("roomType","room_type")), "nights_stayed":None, "traveller_type":s(get("travellerType","traveller_type","groupName")),
      "title":s(get("reviewTitle","title")), "positive_text":s(get("pros","positive","positiveText")),
      "negative_text":s(get("cons","negative","negativeText")), "hotel_reply":s(get("hotelReply","response"))}

async def collect_property(page, slug, name, url, mode, max_pages, counters, run_id, pause_on_challenge=False, verification_timeout_seconds=300):
    seen_payload=set(); pages=0; consecutive_old=0; observed_cards=0; expected_total=None; overall_score=None; card_errors=0
    run_started=now(); warning_start=len(counters.get("warnings",[]))
    update_property_source_state(slug,latest_run_id=run_id,latest_run_mode=mode,latest_run_started_at=run_started,latest_run_finished_at=None,latest_run_status="running",latest_run_pages=0,latest_run_cards=0,last_error=None,**({"backfill_status":"in_progress"} if mode=="full" else {}))
    def finish_state(status,error=None):
        finished=now(); fields={"latest_run_finished_at":finished,"latest_run_status":status,"latest_run_pages":pages,"latest_run_cards":observed_cards,"last_error":error}
        if status=="completed": fields["last_success_at"]=finished
        if mode=="full":
            fields.update(last_full_run_at=finished,last_full_pages=pages,last_full_cards=observed_cards)
            if status in {"blocked","failed"}: fields["backfill_status"]="blocked_by_access_restriction" if status=="blocked" else "failed"
            elif expected_total is None: fields["backfill_status"]="source_total_unknown"
            elif status=="completed" and scalar("SELECT COUNT(*) FROM reviews WHERE property_slug=?",(slug,))>=expected_total: fields["backfill_status"]="complete"
            else: fields["backfill_status"]="partially_collected"
        update_property_source_state(slug,**fields)
    async def watch_response(response):
        if "json" not in response.headers.get("content-type", "").lower(): return
        try: payload=await response.json()
        except Exception: return
        for raw in flatten_reviews(payload):
            row=from_payload(raw)
            if row["review_id"] and row["review_id"] not in seen_payload:
                seen_payload.add(row["review_id"])
                await save_review(row, slug, name, counters)
    page.on("response", watch_response)
    try:
        response=await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        body=(await page.locator("body").inner_text(timeout=3000))
        body_lower=body.lower()
        total_match=re.search(r"(?:Guest reviews\s*\(|Guest reviews\s*)([\d,]+)\)?", body, re.I) or re.search(r"([\d,]+)\s+reviews\b",body,re.I)
        expected_total=int(total_match.group(1).replace(",","")) if total_match else None
        overall_score=await extract_listing_score(page,body)
        source_fields={"source_method":"booking_page_dom"}
        if expected_total is not None: source_fields["booking_total_reviews"]=expected_total
        if overall_score is not None: source_fields["booking_overall_score"]=overall_score
        if expected_total is not None or overall_score is not None: source_fields["source_observed_at"]=now()
        update_property_source_state(slug,**source_fields)
        challenge=is_verification_response(response,body)
        if challenge and pause_on_challenge:
            update_property_source_state(slug,latest_run_status="waiting_for_verification",last_error="Waiting for manual Booking.com verification in the visible browser")
            challenge_cleared=await wait_for_manual_verification(page,name,verification_timeout_seconds)
            if challenge_cleared:
                response=await page.goto(url,wait_until="domcontentloaded",timeout=60000)
                body=await page.locator("body").inner_text(timeout=5000)
                body_lower=body.lower()
                challenge=is_verification_response(response,body)
            else:
                challenge=True
        if challenge:
            message="Booking.com verification was not cleared; no reviews collected" if pause_on_challenge else "Booking.com verification appeared in a headless run; no reviews collected. Use a visible browser for manual verification."
            counters.setdefault("warnings",[]).append(f"{slug}: {message}")
            finish_state("blocked",message)
            return 0
        for label in ("Accept", "Accept all", "I agree", "Dismiss"):
            try: await page.get_by_role("button", name=re.compile(label, re.I)).click(timeout=1200); break
            except Exception: pass
        # Booking's header hydrates after domcontentloaded and replaces its tab
        # nodes. Clicking a broad [data-testid*=review] selector during that
        # replacement often succeeds without ever opening the review list.
        await page.wait_for_timeout(1800)
        opened_reviews = False
        for selector in ("[data-testid='fr-read-all-reviews']",
                         "[data-testid='Property-Header-Nav-Tab-Trigger-reviews']"):
            try:
                control = page.locator(selector).first
                await control.wait_for(state="visible", timeout=5000)
                await control.scroll_into_view_if_needed(timeout=3000)
                await control.click(timeout=6000)
                try:
                    await page.wait_for_selector("[data-testid='review-card']", state="attached", timeout=10000)
                    opened_reviews = True
                    break
                except PlaywrightTimeout:
                    # The nav tab can reveal the review summary first; fetch a
                    # fresh locator because Booking replaces these nodes.
                    if selector.endswith("fr-read-all-reviews']"):
                        continue
            except Exception as e:
                LOG.debug("Review-list control %s did not open: %s", selector, e)
        if not opened_reviews:
            error=f"Booking page loaded but no review cards became available; check for verification or a changed review page"
            counters.setdefault("warnings", []).append(f"{slug}: {error}")
            finish_state("blocked",error)
            return 0
        try: await page.get_by_role("button", name=re.compile("newest", re.I)).click(timeout=3000)
        except Exception: pass
        await page.wait_for_timeout(800)
        for page_no in range(max_pages or 10000):
            pages+=1
            await page.wait_for_timeout(random.randint(1300, 2800))
            cards=page.locator("[data-testid='review-card'], [data-testid='reviewCard'], [data-testid^='reviewCard_'], [data-review-id], li.review_item")
            count=await cards.count()
            observed_cards+=count
            update_property_source_state(slug,latest_run_pages=pages,latest_run_cards=observed_cards)
            LOG.info("%s review page %d: %d candidate cards", slug, pages, count)
            valid_cards=0
            page_new_before=counters["new"]
            for i in range(count):
                card=cards.nth(i)
                try:
                    text=await card.inner_text(timeout=6000)
                    attrs=await card.evaluate("el => ({id: el.getAttribute('data-review-id') || '', date: el.querySelector('[data-testid=review-date] time')?.getAttribute('datetime') || el.querySelector('[data-testid=review-date]')?.innerText || el.querySelector('time')?.getAttribute('datetime') || el.querySelector('time')?.innerText || '', rating: el.querySelector('[data-testid=review-score]')?.innerText || el.querySelector('[aria-label*=\"/10\"], [data-testid*=rating]')?.getAttribute('aria-label') || '', title: el.querySelector('[data-testid=review-title]')?.innerText || el.querySelector('[data-testid*=title]')?.innerText || '', reviewer: el.querySelector('[data-testid=review-avatar]')?.innerText || el.querySelector('[data-testid*=reviewer-name], .reviewer_name')?.innerText || '', country: el.querySelector('[data-testid*=reviewer-country], [data-testid*=country-name]')?.innerText || '', stay: el.querySelector('[data-testid=review-stay-date]')?.innerText || el.querySelector('[data-testid*=stay-date]')?.innerText || '', room: el.querySelector('[data-testid=review-room-name]')?.innerText || el.querySelector('[data-testid*=room-type]')?.innerText || '', traveller: el.querySelector('[data-testid=review-traveler-type]')?.innerText || el.querySelector('[data-testid*=traveller-type], [data-testid*=group-name]')?.innerText || '', reply: el.querySelector('[data-testid=review-partner-reply]')?.innerText || el.querySelector('[data-testid*=hotel-response], [data-testid*=owner-response]')?.innerText || ''})")
                    positive=""; negative=""
                    for sel in ("[data-testid='review-positive-text']","[data-testid*='review-positive']"):
                        if await card.locator(sel).count(): positive=await card.locator(sel).first.inner_text(); break
                    for sel in ("[data-testid='review-negative-text']","[data-testid*='review-negative']"):
                        if await card.locator(sel).count(): negative=await card.locator(sel).first.inner_text(); break
                    rating_match=re.search(r"\d+(?:\.\d+)?", attrs["rating"])
                    nights_match=re.search(r"(\d+)\s+nights?",text,re.I)
                    review_date=norm_date(attrs["date"])
                    if not any((attrs["id"], attrs["reviewer"].strip(), attrs["title"].strip(), review_date, positive, negative)):
                        continue
                    valid_cards+=1
                    row={"review_id":attrs["id"],"reviewer_name":attrs["reviewer"].strip(),"reviewer_country":attrs["country"].strip(),"rating":float(rating_match.group()) if rating_match else None,
                      "review_date":review_date,"stay_date":attrs["stay"].strip() or None,"room_type":attrs["room"].strip() or None,"nights_stayed":int(nights_match.group(1)) if nights_match else None,"traveller_type":attrs["traveller"].strip() or None,
                      "title":attrs["title"],"positive_text":positive,"negative_text":negative,"hotel_reply":attrs["reply"].strip()}
                    save_result=await save_review(row,slug,name,counters)
                    if i < 2:
                        LOG.info("%s card %d parsed fields: reviewer=%s title=%s date=%s text=%s rating=%s; save=%s",
                                 slug, i + 1, bool(row["reviewer_name"]), bool(row["title"]), bool(row["review_date"]),
                                 bool(row["positive_text"] or row["negative_text"]), row["rating"] is not None, save_result)
                    if save_result=="new": consecutive_old=0
                    elif save_result=="stored": consecutive_old+=1
                except Exception as e:
                    card_errors+=1
                    LOG.warning("Could not process review card %d (%s)", i + 1, type(e).__name__, exc_info=(i == 0))
            with connect() as db:
                db.execute("UPDATE scraper_runs SET pages=?,new_reviews=?,duplicates_skipped=? WHERE id=?",(counters["pages"]+pages,counters["new"],counters["duplicates"],run_id))
            if count and not valid_cards and counters["new"]==page_new_before:
                counters.setdefault("warnings",[]).append(f"{slug}: page {pages} had page elements but no recognizable review records; pagination stopped")
                break
            if mode=="incremental" and consecutive_old>=5: break
            if count==0:
                counters.setdefault("warnings", []).append(f"{slug}: review list became empty after page {pages}; pagination stopped")
                break
            next_btn=page.locator("[data-testid*='review'] button[aria-label*='Next'], [data-testid*='review'] a[aria-label*='Next'], button[aria-label*='Next'], button:has-text('Next'), a[aria-label*='Next']").last
            try:
                if not await next_btn.is_visible(timeout=1200) or not await next_btn.is_enabled(): break
                old_first=(await cards.first.inner_text(timeout=1000))[:120] if count else None
                old_url=page.url
                await next_btn.click(timeout=5000)
                await page.wait_for_timeout(1200)
                new_count=await cards.count()
                new_first=(await cards.first.inner_text(timeout=1000))[:120] if new_count else None
                if page.url==old_url and old_first==new_first and counters["new"]==page_new_before:
                    counters.setdefault("warnings",[]).append(f"{slug}: pagination did not advance after page {pages}; stopped")
                    break
            except Exception as e:
                counters.setdefault("warnings", []).append(f"{slug}: pagination failed after page {pages} ({type(e).__name__})")
                break
        # Incremental sync intentionally scans only the newest page(s) and may
        # stop once it reaches already-stored reviews. Compare against the
        # listing's lifetime total only during a requested full backfill.
        if mode == "full" and expected_total is not None and observed_cards < expected_total:
            counters.setdefault("warnings", []).append(
                f"{slug}: Booking lists {expected_total} reviews, but only {observed_cards} review cards were visited across {pages} pages"
            )
        if card_errors:
            counters.setdefault("warnings", []).append(f"{slug}: {card_errors} review cards timed out or could not be parsed")
        property_warnings=counters.get("warnings",[])[warning_start:]
        final_status="completed_with_errors" if property_warnings else "completed"
        finish_state(final_status,"; ".join(property_warnings) if property_warnings else None)
        return pages
    finally: page.remove_listener("response", watch_response)

async def save_review(r, slug, name, counters):
    if not any((r.get("review_id"),r.get("reviewer_name"),r.get("review_date"),r.get("title"),r.get("positive_text"),r.get("negative_text"))): return "invalid"
    r["property_slug"]=slug; r["property_name"]=name; r["scraped_at"]=now()
    key=f"{slug}:{r['review_id']}" if r.get("review_id") else review_hash(r,slug)
    sentiment,topics=classify(r.get("rating"),r.get("positive_text"),r.get("negative_text"))
    issue_topics=classify_issue_topics(sentiment,r.get("negative_text"))
    praise_topics=classify_praise_topics(sentiment,r.get("positive_text"))
    with connect() as db:
        cur=db.execute("""INSERT OR IGNORE INTO reviews(review_id,review_key,property_slug,property_name,reviewer_name,reviewer_country,rating,review_date,stay_date,room_type,nights_stayed,traveller_type,title,positive_text,negative_text,hotel_reply,scraped_at,sentiment,topics,issue_topics,praise_topics) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (r.get("review_id") or key,key,slug,name,r.get("reviewer_name") or "",r.get("reviewer_country") or "",r.get("rating"),r.get("review_date"),r.get("stay_date"),r.get("room_type"),r.get("nights_stayed"),r.get("traveller_type"),r.get("title"),r.get("positive_text") or "",r.get("negative_text") or "",r.get("hotel_reply") or "",r["scraped_at"],sentiment,json.dumps(topics),json.dumps(issue_topics),json.dumps(praise_topics)))
        if cur.rowcount:
            counters["new"]+=1
            counters.setdefault("run_keys",set()).add(key)
            return "new"
        counters["duplicates"]+=1
        is_stored=key in counters.get("initial_keys",set()) or (slug,r.get("review_id")) in counters.get("initial_ids",set())
        return "stored" if is_stored else "same_run"

async def run(mode="incremental", property_slug=None, max_pages=None):
    init_db(); errors=[]; counters={"new":0,"duplicates":0,"pages":0,"warnings":[]}; started=now()
    with connect() as db:
        existing=db.execute("SELECT property_slug,review_id,review_key FROM reviews").fetchall()
        counters["initial_ids"]={(r["property_slug"],r["review_id"]) for r in existing}
        counters["initial_keys"]={r["review_key"] for r in existing}
        cur=db.execute("INSERT INTO scraper_runs(mode,property_slug,started_at,status) VALUES(?,?,?,?)",(mode,property_slug,started,"running")); run_id=cur.lastrowid
    targets={k:v for k,v in PROPERTIES.items() if not property_slug or k==property_slug}
    if property_slug and property_slug not in PROPERTIES: raise SystemExit(f"Unknown property slug: {property_slug}")
    try:
        async with async_playwright() as p:
            headless=os.getenv("BOOKING_HEADLESS","true").lower() not in {"0","false","no"}
            verification_timeout_seconds=max(30,min(1800,int(os.getenv("BOOKING_VERIFICATION_TIMEOUT_SECONDS","300"))))
            browser=await p.chromium.launch(headless=headless)
            state_path=os.getenv("BOOKING_STORAGE_STATE")
            context=await browser.new_context(locale="en-AU", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",storage_state=state_path if state_path and Path(state_path).exists() else None)
            for slug,(name,url) in targets.items():
                page=await context.new_page()
                for attempt in range(3):
                    try: counters["pages"]+=await collect_property(page,slug,name,url,mode,max_pages,counters,run_id,pause_on_challenge=not headless,verification_timeout_seconds=verification_timeout_seconds); break
                    except (PlaywrightTimeout, Exception) as e:
                        if attempt==2:
                            errors.append(f"{slug}: {type(e).__name__}: {e}"); LOG.exception("Property failed: %s",slug)
                            finish=now(); update_property_source_state(slug,latest_run_id=run_id,latest_run_mode=mode,latest_run_finished_at=finish,latest_run_status="failed",last_error=f"{type(e).__name__}: {e}",**({"backfill_status":"failed","last_full_run_at":finish} if mode=="full" else {}))
                        else: await asyncio.sleep(2**(attempt+1)+random.random())
                await page.close()
                if not headless and state_path:
                    await context.storage_state(path=state_path)
            await browser.close()
        if not counters["new"] and not counters["duplicates"] and not counters["warnings"]:
            counters["warnings"].append("No reviews were saved or confirmed as duplicates; verify that Booking exposed its review list before treating this run as successful")
        status="completed" if not errors and not counters["warnings"] else "completed_with_errors"
    except Exception as e: errors.append(str(e)); status="failed"
    with connect() as db:
        db.execute("UPDATE scraper_runs SET finished_at=?,status=?,new_reviews=?,duplicates_skipped=?,pages=?,errors=? WHERE id=?",(now(),status,counters["new"],counters["duplicates"],counters["pages"],"\n".join(errors+counters["warnings"]),run_id))
        db.execute("INSERT INTO scraper_state(property_slug,last_review_date,updated_at) VALUES(?,?,?) ON CONFLICT(property_slug) DO UPDATE SET last_review_date=excluded.last_review_date, updated_at=excluded.updated_at",(property_slug or "all",None,now()))
    LOG.info("Run %s: %d new, %d duplicates, %d pages; %s",run_id,counters["new"],counters["duplicates"],counters["pages"],status)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--mode",choices=["full","incremental"],default="incremental"); parser.add_argument("--property",dest="property_slug"); parser.add_argument("--max-pages",type=int); args=parser.parse_args()
    try: asyncio.run(run(args.mode,args.property_slug,args.max_pages))
    except KeyboardInterrupt:
        with connect() as db:
            db.execute("UPDATE scraper_runs SET finished_at=?,status='interrupted',errors=CASE WHEN errors='' THEN 'Interrupted by operator' ELSE errors || char(10) || 'Interrupted by operator' END WHERE status='running'",(now(),))
        LOG.warning("Scrape interrupted; completed review batches remain saved.")
if __name__=="__main__": main()
