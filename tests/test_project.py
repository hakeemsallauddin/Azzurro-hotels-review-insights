"""Isolated regression tests for the review warehouse and analytics."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


_TEMP_ROOT = Path(tempfile.mkdtemp(prefix="azzurro-tests-"))
os.environ["AZZURRO_DB"] = str(_TEMP_ROOT / "test-reviews.sqlite3")

from backend import db as database  # noqa: E402
from backend.analytics.classify import (  # noqa: E402
    TOPICS,
    classify,
    classify_issue_topics,
    classify_praise_topics,
)
from backend.api import main as api  # noqa: E402
from backend.scraper.run_scraper import save_review  # noqa: E402


class ProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()

    def setUp(self):
        with database.connect() as conn:
            conn.execute("DELETE FROM reviews")
            conn.execute("DELETE FROM scraper_runs")
            conn.execute("DELETE FROM action_tasks")

    def insert_review(self, *, slug, name, review_id, rating, review_date, positive="", negative=""):
        row = {
            "review_id": review_id,
            "reviewer_name": "Test guest",
            "reviewer_country": "",
            "rating": rating,
            "review_date": review_date,
            "stay_date": None,
            "room_type": None,
            "nights_stayed": None,
            "traveller_type": None,
            "title": "Test fixture",
            "positive_text": positive,
            "negative_text": negative,
            "hotel_reply": "",
            "scraped_at": "2026-01-01T00:00:00+00:00",
        }
        return asyncio.run(save_review(row, slug, name, {"new": 0, "duplicates": 0}))

    def test_all_eight_topics_are_configured_and_classified(self):
        expected = {
            "Cleanliness", "Check-in experience", "Staff behaviour", "Noise",
            "Facilities", "Location", "Room condition", "Value for money",
        }
        self.assertEqual(set(TOPICS), expected)
        sentiment, _ = classify(4, "", "The room was dirty and noisy")
        self.assertEqual(sentiment, "negative")
        self.assertEqual(
            set(classify_issue_topics(sentiment, "The room was dirty and noisy")),
            {"Cleanliness", "Noise", "Room condition"},
        )
        self.assertEqual(classify_issue_topics("positive", "dirty room"), [])
        self.assertEqual(classify_praise_topics("positive", "Great location"), ["Location"])

    def test_insert_and_deduplicate_same_review(self):
        slug, name = next(iter(database.PROPERTIES.items()))
        added = self.insert_review(slug=slug, name=name[0], review_id="source-1", rating=9,
                                   review_date="2026-11-25", positive="Great location")
        run_counters = {"new": 0, "duplicates": 0, "initial_ids": {(slug, "source-1")},
                        "initial_keys": {f"{slug}:source-1"}}
        row = {"review_id": "source-1", "reviewer_name": "Test guest", "rating": 9,
               "review_date": "2026-11-25", "title": "Test fixture", "positive_text": "Great location",
               "negative_text": "", "scraped_at": "2026-01-01T00:00:00+00:00"}
        duplicate = asyncio.run(save_review(row, slug, name[0], run_counters))
        self.assertEqual(added, "new")
        self.assertEqual(duplicate, "stored")
        with database.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0], 1)

    def test_api_filters_and_analytics_use_fixture_rows(self):
        today = datetime.now(ZoneInfo("Australia/Sydney")).date()
        this_week = today - timedelta(days=today.weekday())
        yday = today - timedelta(days=1)
        for index, (slug, (name, _url)) in enumerate(database.PROPERTIES.items()):
            date = (this_week + timedelta(days=min(index, 5))).isoformat()
            self.insert_review(slug=slug, name=name, review_id=f"fixture-{index}", rating=4 + index,
                               review_date=date, negative="Dirty room was noisy")
        overview = api.overview(property="all", start_date=None, end_date=None)
        self.assertEqual(overview["total_reviews"], 4)
        self.assertEqual(overview["current_week_count"], 4)
        self.assertEqual(overview["negative_count"], 4)
        self.assertTrue(any(item["topic"] == "Cleanliness" for item in api.topics()))
        filtered = api.reviews(page=1, page_size=2, sort="newest", q=None,
                               property=list(database.PROPERTIES)[0], start_date=None,
                               end_date=None, sentiment=None, topic=None)
        self.assertEqual(filtered["total_count"], 1)
        self.assertEqual(filtered["total_pages"], 1)
        self.assertEqual(len(api.properties()), 4)
        self.assertGreaterEqual(len(api.trends(interval="day")), 1)
        self.assertLessEqual(yday, today)

    def test_automation_uses_recorded_full_run_when_property_state_is_legacy(self):
        started = "2026-11-25T19:45:33+00:00"
        finished = "2026-11-25T20:48:25+00:00"
        with database.connect() as conn:
            conn.execute("INSERT INTO scraper_runs(mode,property_slug,started_at,finished_at,status,new_reviews,duplicates_skipped,pages,errors) VALUES('full',NULL,?,?, 'completed',8038,72,813,'')", (started, finished))
        result = api.automation(impact_window=30)
        paddington = next(item for item in result["properties"] if item["property"] == "olympic-paddington")
        self.assertEqual(paddington["last_full_run"]["finished_at"], finished)
        self.assertIsNone(paddington["last_full_run"]["property_slug"])
        self.assertEqual(paddington["backfill_status"], "partially_collected")

    def test_legacy_schema_backfills_topic_classification(self):
        old_path = _TEMP_ROOT / "legacy.sqlite3"
        import sqlite3

        legacy = sqlite3.connect(old_path)
        legacy.execute("""CREATE TABLE reviews (
            id INTEGER PRIMARY KEY, review_id TEXT NOT NULL, review_key TEXT NOT NULL UNIQUE,
            property_slug TEXT NOT NULL, property_name TEXT NOT NULL,
            reviewer_name TEXT NOT NULL DEFAULT '', reviewer_country TEXT NOT NULL DEFAULT '',
            rating REAL, review_date TEXT, stay_date TEXT, room_type TEXT,
            nights_stayed INTEGER, traveller_type TEXT, title TEXT,
            positive_text TEXT NOT NULL DEFAULT '', negative_text TEXT NOT NULL DEFAULT '',
            hotel_reply TEXT, scraped_at TEXT NOT NULL,
            sentiment TEXT NOT NULL DEFAULT 'neutral', topics TEXT NOT NULL DEFAULT '[]',
            UNIQUE(property_slug, review_id))""")
        legacy.execute("INSERT INTO reviews(review_id,review_key,property_slug,property_name,rating,negative_text,scraped_at) VALUES(?,?,?,?,?,?,?)",
                       ("legacy-1", "legacy-key", "olympic-paddington", "Olympic Hotel Paddington", 3, "Dirty room", "2026-01-01"))
        legacy.commit()
        legacy.close()

        prior_path = database.DB_PATH
        try:
            database.DB_PATH = old_path
            database.init_db()
            conn = database.connect()
            try:
                row = conn.execute("SELECT sentiment,issue_topics FROM reviews WHERE review_id='legacy-1'").fetchone()
            finally:
                conn.close()
            self.assertEqual(row["sentiment"], "negative")
            self.assertEqual(set(json.loads(row["issue_topics"])), {"Cleanliness", "Room condition"})
        finally:
            database.DB_PATH = prior_path


if __name__ == "__main__":
    unittest.main()
