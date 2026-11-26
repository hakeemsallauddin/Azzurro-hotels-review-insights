from __future__ import annotations
import asyncio, json, os, subprocess, sys, threading
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Literal
from uuid import uuid4
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from backend.db import connect, init_db, PROPERTIES
from backend.analytics.classify import TOPICS

_scrape_lock=threading.Lock(); _scrape_process=None

def _start_scrape_process(mode="incremental"):
    global _scrape_process
    with _scrape_lock:
        if _scrape_process and _scrape_process.poll() is None: return False
        root=Path(__file__).resolve().parents[2]
        _scrape_process=subprocess.Popen([sys.executable,"-m","backend.scraper.run_scraper","--mode",mode],cwd=root,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        return True

async def _scheduled_scrapes():
    interval=max(1,int(os.getenv("SCRAPE_INTERVAL_HOURS","12")))*3600
    while True:
        if os.getenv("AUTO_SCRAPE","true").lower() not in {"0","false","no"}:
            await asyncio.to_thread(_start_scrape_process)
        await asyncio.sleep(interval)

@asynccontextmanager
async def lifespan(_app):
    init_db()
    task=asyncio.create_task(_scheduled_scrapes())
    try: yield
    finally:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass

app=FastAPI(title="Azzurro Hotels Review Insights API", version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=os.getenv("CORS_ORIGINS","http://localhost:5173").split(","),allow_methods=["*"],allow_headers=["*"])
init_db()

class ActionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    details: str = Field(default="", max_length=2000)
    topic: str = Field(min_length=2, max_length=80)
    property_slug: str = Field(default="all", max_length=80)
    department: str = Field(min_length=2, max_length=80)
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    owner: str = Field(default="", max_length=120)
    due_date: str | None = None

class ActionUpdate(BaseModel):
    status: Literal["open", "in_progress", "completed"] | None = None
    owner: str | None = Field(default=None, max_length=120)
    due_date: str | None = None
    completion_note: str | None = Field(default=None, max_length=2000)

def where(property=None,start_date=None,end_date=None):
    parts=[]; params=[]
    if property and property!="all": parts.append("property_slug=?"); params.append(property)
    if start_date: parts.append("review_date>=?"); params.append(start_date)
    if end_date: parts.append("review_date<=?"); params.append(end_date)
    return (" WHERE "+" AND ".join(parts) if parts else "",params)
def rows(query,params=()):
    with connect() as db: return [dict(r) for r in db.execute(query,params).fetchall()]
def scalar(query,params=()):
    with connect() as db: return db.execute(query,params).fetchone()[0]
def filters(property=None,start_date=None,end_date=None): return where(property,start_date,end_date)
def property_today(): return datetime.now(ZoneInfo("Australia/Sydney")).date()

@app.get("/api/health")
def health(): return {"status":"ok","review_count":scalar("SELECT COUNT(*) FROM reviews"),"database":str(__import__('backend.db',fromlist=['DB_PATH']).DB_PATH)}

@app.get("/api/properties")
def properties(property:str|None=None,start_date:str|None=None,end_date:str|None=None):
    result=[]; today=property_today(); this_start=today-timedelta(days=today.weekday()); next_start=this_start+timedelta(days=7); prev_start=this_start-timedelta(days=7)
    if property and property!="all" and property not in PROPERTIES: raise HTTPException(400,"Unknown property")
    for slug,(name,url) in PROPERTIES.items():
        if property and property!="all" and slug!=property: continue
        base=" WHERE property_slug=?"; p=[slug]
        if start_date: base+=" AND review_date>=?"; p.append(start_date)
        if end_date: base+=" AND review_date<=?"; p.append(end_date)
        stats=rows("SELECT COUNT(*) count,AVG(rating) avg FROM reviews"+base,p)[0]
        stored_count=scalar("SELECT COUNT(*) FROM reviews WHERE property_slug=?",(slug,))
        this=scalar("SELECT AVG(rating) FROM reviews WHERE property_slug=? AND review_date>=? AND review_date<?",(slug,this_start.isoformat(),next_start.isoformat()))
        prev=scalar("SELECT AVG(rating) FROM reviews WHERE property_slug=? AND review_date>=? AND review_date<?",(slug,prev_start.isoformat(),this_start.isoformat()))
        complaint_where=" WHERE property_slug=? AND sentiment='negative'"; complaint_params=[slug]
        if start_date: complaint_where+=" AND review_date>=?"; complaint_params.append(start_date)
        if end_date: complaint_where+=" AND review_date<=?"; complaint_params.append(end_date)
        complaints=rows("SELECT value topic,COUNT(*) n FROM reviews,json_each(reviews.issue_topics)"+complaint_where+" GROUP BY value ORDER BY n DESC LIMIT 1",complaint_params)
        praise_where=" WHERE property_slug=? AND sentiment='positive'"; praise_params=[slug]
        if start_date: praise_where+=" AND review_date>=?"; praise_params.append(start_date)
        if end_date: praise_where+=" AND review_date<=?"; praise_params.append(end_date)
        praises=rows("SELECT value topic,COUNT(*) n FROM reviews,json_each(reviews.praise_topics)"+praise_where+" GROUP BY value ORDER BY n DESC LIMIT 1",praise_params)
        negative_count=scalar("SELECT COUNT(*) FROM reviews WHERE property_slug=? AND sentiment='negative'"+ (" AND review_date>=?" if start_date else "")+(" AND review_date<=?" if end_date else ""),[slug,*([start_date] if start_date else []),*([end_date] if end_date else [])])
        positive_count=scalar("SELECT COUNT(*) FROM reviews WHERE property_slug=? AND sentiment='positive'"+ (" AND review_date>=?" if start_date else "")+(" AND review_date<=?" if end_date else ""),[slug,*([start_date] if start_date else []),*([end_date] if end_date else [])])
        source=rows("SELECT booking_total_reviews,booking_overall_score,source_observed_at,source_method FROM property_source_state WHERE property_slug=?",(slug,))
        source=source[0] if source else {}
        top_issue=complaints[0] if complaints else None; top_praise=praises[0] if praises else None
        result.append({"property":slug,"name":name,"url":url,"review_count":stats["count"],"stored_review_count":stored_count,"average_rating":round(stats["avg"],2) if stats["avg"] is not None else None,"booking_total_reviews":source.get("booking_total_reviews"),"booking_overall_score":source.get("booking_overall_score"),"source_observed_at":source.get("source_observed_at"),"source_method":source.get("source_method"),"this_week_avg":round(this,2) if this is not None else None,"previous_week_avg":round(prev,2) if prev is not None else None,"wow_delta":round(this-prev,2) if this is not None and prev is not None else None,"top_complaint":top_issue["topic"] if top_issue else None,"top_complaint_count":top_issue["n"] if top_issue else 0,"top_complaint_share":round(top_issue["n"]/negative_count*100,1) if top_issue and negative_count else None,"top_praise":top_praise["topic"] if top_praise else None,"top_praise_count":top_praise["n"] if top_praise else 0,"top_praise_share":round(top_praise["n"]/positive_count*100,1) if top_praise and positive_count else None})
    return result

@app.get("/api/overview")
def overview(property:str|None=None,start_date:str|None=None,end_date:str|None=None):
    today=property_today(); monday=today-timedelta(days=today.weekday()); next_monday=monday+timedelta(days=7); prev=monday-timedelta(days=7)
    w,p=filters(property,start_date,end_date)
    allstats=rows("SELECT COUNT(*) total,AVG(rating) avg,SUM(sentiment='positive') positive,SUM(sentiment='negative') negative FROM reviews"+w,p)[0]
    # Current and prior week obey the selected property, while date picker scopes the main totals.
    prop_sql=" AND property_slug=?" if property and property!="all" else ""; prop_params=[property] if prop_sql else []
    current=scalar("SELECT AVG(rating) FROM reviews WHERE review_date>=? AND review_date<?"+prop_sql,[monday.isoformat(),next_monday.isoformat(),*prop_params]); previous=scalar("SELECT AVG(rating) FROM reviews WHERE review_date>=? AND review_date<?"+prop_sql,[prev.isoformat(),monday.isoformat(),*prop_params])
    sentiment=rows("SELECT sentiment,COUNT(*) n FROM reviews"+w+" GROUP BY sentiment",p); neg_count=allstats["negative"] or 0
    negw=w+(" AND " if w else " WHERE ")+"sentiment='negative'"
    topicrows=rows("SELECT value topic,COUNT(DISTINCT reviews.id) n,ROUND(AVG(rating),1) average_rating FROM reviews,json_each(reviews.issue_topics)"+negw+" GROUP BY value ORDER BY n DESC,value",p)
    posw=w+(" AND " if w else " WHERE ")+"sentiment='positive'"
    praise_rows=rows("SELECT value topic,COUNT(DISTINCT reviews.id) n FROM reviews,json_each(reviews.praise_topics)"+posw+" GROUP BY value ORDER BY n DESC,value",p)
    insights=[]
    if neg_count and topicrows:
        top=topicrows[0]; insights.append(f"Top issue: {top['topic']} appeared in {top['n']/neg_count:.0%} of negative reviews ({top['n']} reviews) in the selected period.")
    positive_count=allstats["positive"] or 0
    if positive_count and praise_rows:
        top=praise_rows[0]; insights.append(f"Top praise: {top['topic']} appeared in {top['n']/positive_count:.0%} of positive reviews ({top['n']} reviews) in the selected period.")
    property_stats=rows("SELECT property_slug,COUNT(*) n,AVG(rating) avg FROM reviews"+w+" GROUP BY property_slug HAVING n>0 ORDER BY avg DESC",p)
    if len(property_stats)>1:
        strongest=property_stats[0]; weakest=property_stats[-1]
        insights.append(f"Property range: {PROPERTIES[strongest['property_slug']][0]} leads at {strongest['avg']:.1f}/10; {PROPERTIES[weakest['property_slug']][0]} is lowest at {weakest['avg']:.1f}/10.")
    if not allstats["total"]: insights.append("No reviews are in the database yet. Run the scraper to collect reviews from Booking.com.")
    current_count=scalar("SELECT COUNT(*) FROM reviews WHERE review_date>=? AND review_date<?"+prop_sql,[monday.isoformat(),next_monday.isoformat(),*prop_params]); previous_count=scalar("SELECT COUNT(*) FROM reviews WHERE review_date>=? AND review_date<?"+prop_sql,[prev.isoformat(),monday.isoformat(),*prop_params])
    current_negative=scalar("SELECT COUNT(*) FROM reviews WHERE review_date>=? AND review_date<? AND sentiment='negative'"+prop_sql,[monday.isoformat(),next_monday.isoformat(),*prop_params])
    previous_negative=scalar("SELECT COUNT(*) FROM reviews WHERE review_date>=? AND review_date<? AND sentiment='negative'"+prop_sql,[prev.isoformat(),monday.isoformat(),*prop_params])
    week_topics=rows("SELECT j.value topic,COUNT(DISTINCT r.id) review_count FROM reviews r,json_each(r.issue_topics) j WHERE r.review_date>=? AND r.review_date<? AND r.sentiment='negative'"+prop_sql+" GROUP BY j.value ORDER BY review_count DESC,j.value",[monday.isoformat(),next_monday.isoformat(),*prop_params])
    takeaways=[]
    if week_topics and current_negative:
        top=week_topics[0]
        takeaways.append({"kind":"issue","message":f"{top['review_count']/current_negative:.0%} of negative reviews this week mentioned {top['topic'].lower()} issues ({top['review_count']} of {current_negative} negative reviews).","topic":top["topic"],"sentiment":"negative"})
    if topicrows and neg_count:
        top=topicrows[0]
        topic_score=f"{top['average_rating']:.1f}/10" if top["average_rating"] is not None else "unavailable"
        takeaways.append({"kind":"issue","message":f"Across the selected filters, {top['topic']} is the #1 operational friction point ({top['n']} negative mentions; average rating {topic_score}).","topic":top["topic"],"sentiment":"negative"})
    if praise_rows and positive_count:
        top=praise_rows[0]
        takeaways.append({"kind":"praise","message":f"Top guest praise driver: {top['topic']} was highlighted positively in {top['n']/positive_count:.0%} of positive reviews ({top['n']} reviews).","topic":top["topic"],"sentiment":"positive"})
    if len(property_stats)>1:
        strongest=property_stats[0]; weakest=property_stats[-1]
        weak_issue_sql="SELECT j.value topic,COUNT(DISTINCT r.id) n FROM reviews r,json_each(r.issue_topics) j WHERE r.property_slug=? AND r.sentiment='negative'"
        weak_issue_params=[weakest["property_slug"]]
        if start_date: weak_issue_sql+=" AND r.review_date>=?"; weak_issue_params.append(start_date)
        if end_date: weak_issue_sql+=" AND r.review_date<=?"; weak_issue_params.append(end_date)
        weak_issue=rows(weak_issue_sql+" GROUP BY j.value ORDER BY n DESC,j.value LIMIT 1",weak_issue_params)
        weak_top_issue=f" (top issue: {weak_issue[0]['topic']})" if weak_issue else ""
        takeaways.append({"kind":"property","message":f"{PROPERTIES[strongest['property_slug']][0]} leads at {strongest['avg']:.1f}/10, while {PROPERTIES[weakest['property_slug']][0]} needs attention at {weakest['avg']:.1f}/10{weak_top_issue}."})
    if current is not None and previous is not None:
        rating_delta=round(current-previous,1)
        direction="improved" if rating_delta>0 else "fell" if rating_delta<0 else "held steady"
        delta_text=f" ({rating_delta:+.1f} WoW)" if rating_delta else ""
        takeaways.append({"kind":"trend","message":f"Portfolio rating {direction} week over week: {current:.1f}/10 across {current_count} reviews vs {previous:.1f}/10 across {previous_count} prior-week reviews{delta_text}."})
    sentiment_counts={r["sentiment"]:r["n"] for r in sentiment}
    return {"current_week_avg":round(current,2) if current is not None else None,"current_week_count":current_count,"previous_week_avg":round(previous,2) if previous is not None else None,"previous_week_count":previous_count,"wow_delta":round(current-previous,2) if current is not None and previous is not None else None,"total_reviews":allstats["total"],"positive_count":positive_count,"negative_count":neg_count,"neutral_count":sentiment_counts.get("neutral",0),"negative_rate":round(neg_count/allstats["total"]*100,1) if allstats["total"] else 0,"insights":insights,"takeaways":takeaways}

@app.get("/api/trends")
def trends(property:str|None=None,start_date:str|None=None,end_date:str|None=None,interval:str=Query("week",pattern="^(day|week)$")):
    w,p=filters(property,start_date,end_date); bucket="date(review_date)" if interval=="day" else "date(review_date,'-6 days','weekday 1')"
    return rows(f"SELECT {bucket} period,COUNT(*) reviews,AVG(rating) average_rating,SUM(sentiment='positive') positive,SUM(sentiment='negative') negative FROM reviews{w} GROUP BY period ORDER BY period",p)

@app.get("/api/topics")
def topics(property:str|None=None,start_date:str|None=None,end_date:str|None=None):
    w,p=filters(property,start_date,end_date)
    negw=w+(" AND " if w else " WHERE ")+"sentiment='negative'"
    negative_total=scalar("SELECT COUNT(*) FROM reviews"+negw,p)
    data=rows("SELECT value topic,COUNT(*) mentions,ROUND(AVG(rating),2) average_rating FROM reviews,json_each(reviews.topics)"+w+" GROUP BY value ORDER BY mentions DESC",p)
    negative_topics={row["topic"]:row["mentions"] for row in rows("SELECT value topic,COUNT(*) mentions FROM reviews,json_each(reviews.issue_topics)"+negw+" GROUP BY value",p)}
    for item in data:
        item["negative_mentions"]=negative_topics.get(item["topic"],0)
        item["negative_review_share"]=round(item["negative_mentions"]/negative_total*100,1) if negative_total else 0
    return data

@app.get("/api/reviews")
def reviews(page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),sort:str=Query("newest",pattern="^(newest|oldest|highest|lowest)$"),q:str|None=None,property:str|None=None,start_date:str|None=None,end_date:str|None=None,sentiment:str|None=None,topic:str|None=None):
    w,p=filters(property,start_date,end_date); extras=[]
    if sentiment: extras.append("sentiment=?"); p.append(sentiment)
    if topic:
        topic_column="issue_topics" if sentiment=="negative" else "praise_topics" if sentiment=="positive" else "topics"
        extras.append(f"EXISTS(SELECT 1 FROM json_each(reviews.{topic_column}) WHERE value=?)"); p.append(topic)
    if q: extras.append("(reviewer_name LIKE ? OR reviewer_country LIKE ? OR title LIKE ? OR positive_text LIKE ? OR negative_text LIKE ? OR property_name LIKE ?)"); p.extend([f"%{q}%"]*6)
    if extras: w+=(" AND " if w else " WHERE ")+" AND ".join(extras)
    total=scalar("SELECT COUNT(*) FROM reviews"+w,p)
    order={"newest":"review_date DESC,id DESC","oldest":"review_date ASC,id ASC","highest":"rating DESC,review_date DESC","lowest":"rating ASC,review_date DESC"}[sort]
    data=rows("SELECT review_id,property_slug,property_name,reviewer_name,reviewer_country,rating,review_date,stay_date,room_type,nights_stayed,traveller_type,title,positive_text,negative_text,hotel_reply,scraped_at,sentiment,topics,issue_topics,praise_topics FROM reviews"+w+f" ORDER BY {order} LIMIT ? OFFSET ?",[*p,page_size,(page-1)*page_size])
    for r in data:
        r["topics"]=json.loads(r["topics"] or "[]")
        r["issue_topics"]=json.loads(r["issue_topics"] or "[]")
        r["praise_topics"]=json.loads(r["praise_topics"] or "[]")
    return {"items":data,"page":page,"page_size":page_size,"total_count":total,"total_pages":(total+page_size-1)//page_size}

@app.post("/api/scrape/trigger",status_code=202)
def trigger_scrape(mode:Literal["incremental","full"]="incremental"):
    if not _start_scrape_process(mode): raise HTTPException(409,"A scrape is already running")
    return {"status":"started","pid":_scrape_process.pid}

@app.get("/api/scrape/status")
def scrape_status():
    current=rows("SELECT * FROM scraper_runs ORDER BY id DESC LIMIT 1")
    is_running=bool(_scrape_process and _scrape_process.poll() is None)
    if not current:
        return {"status":"running" if is_running else "idle","is_running":is_running,"message":"No completed scraper run recorded yet"}
    result={**current[0],"is_running":is_running}
    if is_running:
        waiting=rows("SELECT property_slug FROM property_source_state WHERE latest_run_id=? AND latest_run_status='waiting_for_verification' AND latest_run_finished_at IS NULL ORDER BY property_slug",(current[0]["id"],))
        if waiting:
            result.update(status="waiting_for_verification",waiting_for_verification=True,verification_properties=[r["property_slug"] for r in waiting])
    return result

@app.get("/api/operations")
def operations(property:str|None=None,days:int=Query(30,ge=7,le=90)):
    today=property_today(); start=today-timedelta(days=days-1)
    clauses=["r.review_date>=?","r.sentiment='negative'"]; params=[start.isoformat()]
    if property and property!="all":
        if property not in PROPERTIES: raise HTTPException(400,"Unknown property")
        clauses.append("r.property_slug=?"); params.append(property)
    base=" WHERE "+" AND ".join(clauses)
    period_clauses=["review_date>=?"]; period_params=[start.isoformat()]
    if property and property!="all": period_clauses.append("property_slug=?"); period_params.append(property)
    period_where=" WHERE "+" AND ".join(period_clauses)
    period_count=scalar("SELECT COUNT(*) FROM reviews"+period_where,period_params)
    negative_count=scalar("SELECT COUNT(*) FROM reviews"+period_where+" AND sentiment='negative'",period_params)
    positive_count=scalar("SELECT COUNT(*) FROM reviews"+period_where+" AND sentiment='positive'",period_params)
    issues=rows("SELECT j.value topic,COUNT(*) mentions,COUNT(DISTINCT r.id) review_count,ROUND(AVG(r.rating),1) average_rating,COUNT(DISTINCT r.property_slug) property_count FROM reviews r,json_each(r.issue_topics) j"+base+" GROUP BY j.value ORDER BY review_count DESC,mentions DESC",params)
    for issue in issues:
        property_rows=rows("SELECT r.property_slug property,COUNT(DISTINCT r.id) review_count FROM reviews r,json_each(r.issue_topics) j"+base+" AND j.value=? GROUP BY r.property_slug ORDER BY review_count DESC",[*params,issue["topic"]])
        issue["properties"]=[{"slug":x["property"],"name":PROPERTIES[x["property"]][0],"reviews":x["review_count"]} for x in property_rows]
        issue["period_share"]=round(issue["review_count"]/period_count*100,1) if period_count else 0
        issue["negative_share"]=round(issue["review_count"]/negative_count*100,1) if negative_count else 0
        issue["low_rating_count"]=scalar("SELECT COUNT(DISTINCT r.id) FROM reviews r,json_each(r.issue_topics) j"+base+" AND j.value=? AND r.rating<7",[*params,issue["topic"]])
        issue["examples"]=rows("SELECT r.review_id,r.property_slug,r.property_name,r.reviewer_name,r.rating,r.review_date,r.title,r.negative_text FROM reviews r,json_each(r.issue_topics) j"+base+" AND j.value=? ORDER BY r.rating ASC,r.review_date DESC,r.id DESC LIMIT 2",[*params,issue["topic"]])
        issue["severity"]="high" if issue["review_count"]>=10 else "watch" if issue["review_count"]>=3 else "low"
    praise_clauses=["r.review_date>=?","r.sentiment='positive'"]; praise_params=[start.isoformat()]
    if property and property!="all": praise_clauses.append("r.property_slug=?"); praise_params.append(property)
    praise_base=" WHERE "+" AND ".join(praise_clauses)
    praises=rows("SELECT j.value topic,COUNT(DISTINCT r.id) review_count,ROUND(AVG(r.rating),1) average_rating FROM reviews r,json_each(r.praise_topics) j"+praise_base+" GROUP BY j.value ORDER BY review_count DESC",praise_params)
    for praise in praises:
        praise["period_share"]=round(praise["review_count"]/period_count*100,1) if period_count else 0
        praise["positive_share"]=round(praise["review_count"]/positive_count*100,1) if positive_count else 0
        praise["properties"]=[{"slug":item["property"],"name":PROPERTIES[item["property"]][0],"reviews":item["reviews"]} for item in rows("SELECT r.property_slug property,COUNT(DISTINCT r.id) reviews FROM reviews r,json_each(r.praise_topics) j"+praise_base+" AND j.value=? GROUP BY r.property_slug ORDER BY reviews DESC",[*praise_params,praise["topic"]])]
        praise["examples"]=rows("SELECT r.review_id,r.property_slug,r.property_name,r.reviewer_name,r.rating,r.review_date,r.title,r.positive_text FROM reviews r,json_each(r.praise_topics) j"+praise_base+" AND j.value=? ORDER BY r.rating DESC,r.review_date DESC,r.id DESC LIMIT 2",[*praise_params,praise["topic"]])
    task_clause=" WHERE (property_slug=? OR property_slug='all')" if property and property!="all" else ""
    task_params=[property] if task_clause else []
    actions=rows("SELECT * FROM action_tasks"+task_clause+" ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,due_date IS NULL,due_date,created_at DESC",task_params)
    return {"window_start":start.isoformat(),"reference_date":today.isoformat(),"days":days,"period_review_count":period_count,"negative_review_count":negative_count,"positive_review_count":positive_count,"issues":issues,"praises":praises,"actions":actions}

@app.get("/api/actions")
def list_actions(status:str|None=None):
    if status and status not in {"open","in_progress","completed"}: raise HTTPException(400,"Unknown action status")
    sql="SELECT * FROM action_tasks"+(" WHERE status=?" if status else "")+" ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,due_date IS NULL,due_date,created_at DESC"
    return rows(sql,[status] if status else [])

@app.post("/api/actions",status_code=201)
def create_action(action:ActionCreate):
    if action.property_slug!="all" and action.property_slug not in PROPERTIES: raise HTTPException(400,"Unknown property")
    if action.topic not in TOPICS: raise HTTPException(400,"Unknown operational topic")
    if action.due_date:
        try: date.fromisoformat(action.due_date)
        except ValueError: raise HTTPException(400,"due_date must use YYYY-MM-DD")
    created=datetime.now(timezone.utc).isoformat()
    record={"id":uuid4().hex,"title":action.title.strip(),"details":action.details.strip(),"topic":action.topic,"property_slug":action.property_slug,"department":action.department.strip(),"priority":action.priority,"status":"open","owner":action.owner.strip(),"due_date":action.due_date,"completion_note":"","created_at":created,"updated_at":created,"completed_at":None}
    with connect() as db:
        db.execute("INSERT INTO action_tasks(id,title,details,topic,property_slug,department,priority,status,owner,due_date,completion_note,created_at,updated_at,completed_at) VALUES(:id,:title,:details,:topic,:property_slug,:department,:priority,:status,:owner,:due_date,:completion_note,:created_at,:updated_at,:completed_at)",record)
    return record

@app.patch("/api/actions/{action_id}")
def update_action(action_id:str,update:ActionUpdate):
    patch=update.model_dump(exclude_unset=True)
    if not patch: raise HTTPException(400,"No action fields supplied")
    if "due_date" in patch and patch["due_date"]:
        try: date.fromisoformat(patch["due_date"])
        except ValueError: raise HTTPException(400,"due_date must use YYYY-MM-DD")
    current=rows("SELECT * FROM action_tasks WHERE id=?",(action_id,))
    if not current: raise HTTPException(404,"Action not found")
    record=current[0]; record.update(patch); record["updated_at"]=datetime.now(timezone.utc).isoformat()
    if "status" in patch:
        record["completed_at"]=record["updated_at"] if patch["status"]=="completed" else None
    with connect() as db:
        db.execute("UPDATE action_tasks SET status=?,owner=?,due_date=?,completion_note=?,updated_at=?,completed_at=? WHERE id=?",(record["status"],record["owner"],record["due_date"],record["completion_note"],record["updated_at"],record["completed_at"],action_id))
    return record

@app.get("/api/automation")
def automation(impact_window:int=Query(30,ge=14,le=60)):
    if impact_window not in {14,30,60}: raise HTTPException(400,"impact_window must be 14, 30, or 60")
    today=property_today(); current_start=today-timedelta(days=29); previous_start=current_start-timedelta(days=30); previous_end=current_start-timedelta(days=1)
    current=rows("SELECT COUNT(*) count,ROUND(AVG(rating),2) average,SUM(sentiment='negative') negative FROM reviews WHERE review_date>=? AND review_date<=?",(current_start.isoformat(),today.isoformat()))[0]
    previous=rows("SELECT COUNT(*) count,ROUND(AVG(rating),2) average,SUM(sentiment='negative') negative FROM reviews WHERE review_date>=? AND review_date<=?",(previous_start.isoformat(),previous_end.isoformat()))[0]
    current["negative_rate"]=round((current["negative"] or 0)/current["count"]*100,1) if current["count"] else 0
    previous["negative_rate"]=round((previous["negative"] or 0)/previous["count"]*100,1) if previous["count"] else 0
    by_property=[]
    coverage_total=0; listing_total=0; any_listing_total=False
    now_utc=datetime.now(timezone.utc)
    for slug,(name,url) in PROPERTIES.items():
        count=scalar("SELECT COUNT(*) FROM reviews WHERE property_slug=?",(slug,))
        latest_scoped=rows("SELECT id,property_slug,status,started_at,finished_at,new_reviews,duplicates_skipped,pages,errors FROM scraper_runs WHERE property_slug=? ORDER BY id DESC LIMIT 1",(slug,))
        latest_all=rows("SELECT id,property_slug,status,started_at,finished_at,new_reviews,duplicates_skipped,pages,errors FROM scraper_runs WHERE property_slug IS NULL ORDER BY id DESC LIMIT 1")
        candidates=[run for run in (latest_scoped+latest_all) if run]
        latest_run=max(candidates,key=lambda run:run.get("started_at") or "") if candidates else None
        if latest_run and latest_run.get("property_slug") is None:
            own_errors=[line.strip().split(":",1)[1].strip() for line in (latest_run.get("errors") or "").splitlines() if line.strip().startswith(f"{slug}:")]
            latest_run={**latest_run,"errors":"\n".join(own_errors)}
            if latest_run.get("status")=="completed_with_errors" and not own_errors:
                latest_run["status"]="completed"
        source_rows=rows("SELECT * FROM property_source_state WHERE property_slug=?",(slug,)); source=source_rows[0] if source_rows else {}
        full_runs=rows("SELECT id,property_slug,finished_at,pages,new_reviews,duplicates_skipped FROM scraper_runs WHERE mode='full' AND status='completed' AND errors='' AND finished_at IS NOT NULL AND pages>0 AND (property_slug=? OR property_slug IS NULL) ORDER BY finished_at DESC LIMIT 1",(slug,))
        last_full_run=full_runs[0] if full_runs else None
        source_is_latest=bool(source.get("latest_run_started_at") and (not latest_run or source["latest_run_started_at"]>=latest_run.get("started_at", "")))
        successful=rows("SELECT id,mode,started_at,finished_at,new_reviews,duplicates_skipped,pages FROM scraper_runs WHERE (property_slug=? OR property_slug IS NULL) AND status='completed' AND errors='' AND finished_at IS NOT NULL AND pages>0 ORDER BY finished_at DESC LIMIT 1",(slug,))
        last_successful=successful[0] if successful else None
        try:
            success_age_hours=max(0,(now_utc-datetime.fromisoformat(last_successful["finished_at"])).total_seconds()/3600) if last_successful else None
        except (TypeError,ValueError): success_age_hours=None
        source_date=(source.get("source_observed_at") or "")[:10]
        source_current=bool(source_date and source_date>=today.isoformat())
        health_status="healthy" if success_age_hours is not None and success_age_hours<24 and source_current else "stale" if last_successful else "unknown"
        expected=source.get("booking_total_reviews")
        missing=max(0,expected-count) if expected is not None else None
        coverage=round(min(100,count/expected*100),1) if expected else None
        if expected is None: backfill=source.get("backfill_status") or "source_total_unknown"
        elif missing==0 and source.get("last_full_run_at"): backfill="complete"
        else: backfill="partially_collected"
        last_error=(source.get("last_error") if source_is_latest else None) or (latest_run.get("errors") if latest_run and latest_run.get("status") in {"failed","completed_with_errors"} else None)
        property_run_status=source.get("latest_run_status") if source_is_latest else None
        property_run_finished=source.get("latest_run_finished_at") if source_is_latest else None
        by_property.append({"property":slug,"name":name,"url":url,"review_count":count,"last_run":latest_run,"last_successful_run":last_successful,"success_age_hours":round(success_age_hours,1) if success_age_hours is not None else None,"health_status":health_status,"latest_attempt_status":property_run_status or (latest_run.get("status") if latest_run else "unknown"),"latest_attempt_at":property_run_finished or (latest_run.get("finished_at") if latest_run else None),"latest_attempt_error":last_error,"booking_total_reviews":expected,"booking_overall_score":source.get("booking_overall_score"),"source_observed_at":source.get("source_observed_at"),"source_method":source.get("source_method"),"coverage_pct":coverage,"missing_count":missing,"backfill_status":backfill,"accessible_cards_last_full":source.get("last_full_cards"),"last_full_pages":source.get("last_full_pages"),"last_full_run_at":source.get("last_full_run_at") or (last_full_run.get("finished_at") if last_full_run else None),"last_full_run":last_full_run,"latest_run_status":property_run_status or (latest_run.get("status") if latest_run else "unknown"),"latest_run_at":property_run_finished or (latest_run.get("finished_at") if latest_run else None),"last_error":last_error})
        coverage_total+=count
        if expected is not None: listing_total+=expected; any_listing_total=True
    history=rows("SELECT id,mode,property_slug,started_at,finished_at,status,new_reviews,duplicates_skipped,pages,errors FROM scraper_runs ORDER BY id DESC LIMIT 12")
    total=scalar("SELECT COUNT(*) FROM reviews")
    coverage={"stored_reviews":coverage_total,"listing_reviews":listing_total if any_listing_total else None,"coverage_pct":round(min(100,coverage_total/listing_total*100),1) if listing_total else None,"remaining_gap":max(0,listing_total-coverage_total) if listing_total else None,"observed_at":max((p["source_observed_at"] or "" for p in by_property),default="") or None}
    health_summary={"status":"healthy" if by_property and all(item["health_status"]=="healthy" for item in by_property) else "attention","healthy_count":sum(item["health_status"]=="healthy" for item in by_property),"property_count":len(by_property),"last_successful_at":min((item["last_successful_run"]["finished_at"] for item in by_property if item["last_successful_run"]),default=None),"blocked_attempt_count":sum(bool(item["latest_attempt_error"]) for item in by_property)}
    actions=rows("SELECT * FROM action_tasks ORDER BY completed_at DESC,created_at DESC")
    impact=[]
    def window_metrics(start_date,end_date,scope,topic):
        clause="review_date>=? AND review_date<=?"; params=[start_date,end_date]
        if scope!="all": clause+=" AND property_slug=?"; params.append(scope)
        record=rows("SELECT COUNT(*) count,ROUND(AVG(rating),2) average,SUM(sentiment='negative') negative FROM reviews WHERE "+clause,params)[0]
        tagged=scalar("SELECT COUNT(DISTINCT r.id) FROM reviews r,json_each(r.issue_topics) j WHERE r.review_date>=? AND r.review_date<=? AND r.sentiment='negative' AND j.value=?"+ (" AND r.property_slug=?" if scope!="all" else ""),[start_date,end_date,topic,*([scope] if scope!="all" else [])])
        record["negative_rate"]=round((record["negative"] or 0)/record["count"]*100,1) if record["count"] else None
        record["topic_mentions_per_100"]=round(tagged/record["count"]*100,2) if record["count"] else None
        return record
    for action in actions:
        item={"id":action["id"],"title":action["title"],"topic":action["topic"],"property_slug":action["property_slug"],"status":"awaiting_action"}
        if action["status"]=="completed" and action["completed_at"]:
            completed=date.fromisoformat(action["completed_at"][:10]); before_end=completed-timedelta(days=1); before_start=before_end-timedelta(days=impact_window-1); after_start=completed; after_end=completed+timedelta(days=impact_window-1)
            item.update({"completed_at":action["completed_at"],"window_days":impact_window,"before_start":before_start.isoformat(),"before_end":before_end.isoformat(),"after_start":after_start.isoformat(),"after_end":after_end.isoformat()})
            if after_end>today: item["status"]="awaiting_post_data"
            else:
                before_data=window_metrics(before_start.isoformat(),before_end.isoformat(),action["property_slug"],action["topic"])
                after_data=window_metrics(after_start.isoformat(),after_end.isoformat(),action["property_slug"],action["topic"])
                item.update({"before":before_data,"after":after_data})
                if not before_data["count"] or not after_data["count"]: item["status"]="awaiting_post_data"
                else:
                    delta=(after_data["topic_mentions_per_100"] or 0)-(before_data["topic_mentions_per_100"] or 0)
                    item["topic_rate_change"]=round(delta,2)
                    item["status"]="improved" if delta<0 else "worsened" if delta>0 else "unchanged"
        impact.append(item)
    impact_summary={"window_days":impact_window,"tracked_actions":len(actions),"measured_improved":sum(x["status"]=="improved" for x in impact),"worsened_or_escalated":sum(x["status"]=="worsened" for x in impact),"unchanged":sum(x["status"]=="unchanged" for x in impact),"awaiting_post_data":sum(x["status"]=="awaiting_post_data" for x in impact),"awaiting_completion":sum(x["status"]=="awaiting_action" for x in impact)}
    return {"review_count":total,"coverage":coverage,"collection_health":health_summary,"impact_summary":impact_summary,"impact_actions":impact,"current_window":{"start":current_start.isoformat(),"end":today.isoformat(),**current},"previous_window":{"start":previous_start.isoformat(),"end":previous_end.isoformat(),**previous},"rating_change":round(current["average"]-previous["average"],2) if current["average"] is not None and previous["average"] is not None else None,"negative_rate_change":round(current["negative_rate"]-previous["negative_rate"],1) if current["count"] and previous["count"] else None,"properties":by_property,"recent_runs":history}
