import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "news_bot"))

import ai_handler
import fetcher
import history_manager
import leaks_main
import leak_publisher
import main
import publisher
import utils
import weekly_summary_ai
import weekly_summary_main
import config


class CoreBehaviorTests(unittest.TestCase):
    def test_rss_items_older_than_one_week_are_excluded(self):
        recent = time.gmtime(time.time() - 2 * 24 * 60 * 60)
        old = time.gmtime(time.time() - 9 * 24 * 60 * 60)
        feed = SimpleNamespace(entries=[
            SimpleNamespace(title="حديث", link="https://example.com/new", summary="new", published_parsed=recent),
            SimpleNamespace(title="قديم", link="https://example.com/old", summary="old", published_parsed=old),
        ])
        with patch.object(fetcher, "RSS_SOURCES", [{"name": "Test", "url": "https://example.com/feed"}]), \
             patch.object(fetcher, "_fetch_feed", return_value=feed):
            result = fetcher.fetch_news([])
        self.assertEqual([item["title"] for item in result], ["حديث"])

    def test_weekly_summary_response_is_limited_to_two_parts(self):
        response = {"part1": "أ" * 5000, "part2": "ب" * 5000}
        with patch.object(weekly_summary_ai, "_generate_json_with_retries", return_value=response):
            result = weekly_summary_ai.generate_weekly_summary([{"title": "خبر"}], [])
        self.assertEqual(len(result["part1"]), 3900)
        self.assertEqual(len(result["part2"]), 3900)

    def test_classification_is_normalized_to_closed_values(self):
        normalized = history_manager.normalize_classification({
            "company_name": "Acme",
            "event_year_month": "2026-13",
            "news_type": "غير موجود",
        })
        self.assertEqual(normalized["news_type"], "أخرى")
        self.assertEqual(normalized["event_year_month"], "غير محدد")

    def test_exact_classification_match_is_detected(self):
        existing = [{
            "title": "عنوان مختلف",
            "link": "https://example.com/old",
            "company_name": "Acme",
            "event_year_month": "2026-08",
            "news_type": "ذكاء اصطناعي",
            "product_name": "Model X",
            "region": "Global",
        }]
        candidate = {
            "company_name": "Acme",
            "event_year_month": "2026-08",
            "news_type": "ذكاء اصطناعي",
            "product_name": "Model X",
            "region": "Global",
        }
        duplicate, reason = history_manager.compare_candidate_to_history(
            "عنوان جديد", "https://example.com/new", candidate, existing
        )
        self.assertTrue(duplicate)
        self.assertEqual(reason, "classification-exact")

    def test_old_history_is_pruned_by_real_age(self):
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        history = [{"title": "old", "posted_at": old}, {"title": "recent", "posted_at": recent}]
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "history.json")
            with patch.object(history_manager, "HISTORY_FILE", path):
                self.assertEqual(history_manager.prune_history(history), 1)
        self.assertEqual([item["title"] for item in history], ["recent"])

    def test_source_name_and_link_are_in_footer(self):
        content = publisher.build_post_content(
            "عنوان", "حدث", ["تفصيل"], "أثر", "مصدر تقني", "https://example.com/news"
        )
        self.assertIn("مصدر تقني", content)
        self.assertIn("https://example.com/news", content)

    def test_leak_image_policy_blocks_low_reliability(self):
        self.assertFalse(leaks_main._image_allowed_for_reliability("🔴"))
        self.assertFalse(leaks_main._image_allowed_for_reliability("🟠"))
        self.assertTrue(leaks_main._image_allowed_for_reliability("🟡"))
        self.assertTrue(leaks_main._image_allowed_for_reliability("🟢"))

    def test_leak_image_prompt_is_strict_and_has_no_evidence_language(self):
        prompt = ai_handler.build_leak_image_prompt("اختراق شركة X مع لقطة شاشة")
        for phrase in ["no readable text", "no logos", "no screenshots", "no visual proof", "never evidence"]:
            self.assertIn(phrase, prompt.lower())
        self.assertIn("اختراق شركة X", prompt)

    def test_leak_post_compacts_reason_and_disclaimer(self):
        content = leak_publisher.build_leak_post_content(
            "🟡", "تنويه: تحذير: " + "سبب طويل " * 50, "عنوان", "ملخص", "تحذير طويل", "مصدر", "https://example.com"
        )
        reason = next(line for line in content.splitlines() if line.startswith("📝 التبرير:"))
        self.assertLessEqual(len(reason.split(": ", 1)[1]), 140)
        self.assertEqual(content.count("تنويه"), 0)
        self.assertEqual(content.count("تحذير"), 0)
        self.assertEqual(content.count("غير مؤكد رسميًا"), 1)

    def test_leak_post_marks_ai_illustration_without_claiming_evidence(self):
        content = leak_publisher.build_leak_post_content(
            "🟡", "مصدر غير رسمي.", "عنوان", "ملخص", "تنبيه", "مصدر",
            "https://example.com", "صورة توضيحية مولدة بالذكاء الاصطناعي؛ لا تمثل دليلًا على صحة التسريب."
        )
        self.assertIn("🏷️ **توضيح الصورة:**", content)
        self.assertIn("مولدة بالذكاء الاصطناعي", content)
        self.assertIn("لا تمثل دليلًا", content)

    def test_invalid_gemini_id_is_rejected(self):
        articles = [{"title": "خبر", "link": "https://example.com"}]
        with patch.object(main.ai_handler, "call_gemini_for_selection", return_value={"selected_id": 0}), \
             patch.object(config, "SELECTION_MAX_ATTEMPTS", 1):
            selected, article = main._select_unique_article(articles, [], [])
        self.assertIsNone(selected)
        self.assertIsNone(article)

    def test_long_text_is_split_within_limit(self):
        chunks = publisher._split_text("سطر\n" * 5000, limit=100)
        self.assertTrue(all(len(chunk) <= 100 for chunk in chunks))

    def test_lock_is_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(utils, "LOCK_FILE", os.path.join(directory, "bot.lock")):
                self.assertTrue(utils.acquire_lock())
                self.assertFalse(utils.acquire_lock())
                utils.release_lock()

    def test_weekly_filters_daily_and_skipped_records(self):
        history = [
            {"type": "daily", "status": "published", "title": "daily"},
            {"type": "daily_candidate", "status": "skipped", "title": "skipped"},
            {"type": "leak", "status": "published", "title": "leak"},
        ]
        self.assertEqual([x["title"] for x in weekly_summary_main._published_daily_items(history)], ["daily"])
        self.assertEqual([x["title"] for x in weekly_summary_main._important_skipped_items(history)], ["skipped"])


if __name__ == "__main__":
    unittest.main()
