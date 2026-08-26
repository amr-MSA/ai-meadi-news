"""جلب أحدث مرشحي التسريبات من مصادر RSS."""

import calendar
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from config import NEWS_MAX_AGE_DAYS, RSS_REQUEST_TIMEOUT_SECONDS
from fetcher import REQUEST_HEADERS, dedupe_articles_pool
from history_manager import is_duplicate_against_history
from leaks_config import LEAK_ITEMS_PER_SOURCE, LEAK_SOURCES
from rejected_news_manager import record_rejection


def _clean_summary(summary, fallback):
    text = re.sub(r"<[^>]+>", " ", str(summary or fallback))
    return re.sub(r"\s+", " ", text).strip()[:400]


def fetch_leak_candidates(history, rejected_entries=None):
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_MAX_AGE_DAYS)
    candidates = []
    for source in LEAK_SOURCES:
        try:
            response = requests.get(
                source["url"], headers=REQUEST_HEADERS, timeout=RSS_REQUEST_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            if getattr(feed, "bozo", False) and not feed.entries:
                raise ValueError(f"خلاصة RSS غير صالحة: {getattr(feed, 'bozo_exception', 'unknown')}")

            accepted_from_source = 0
            for entry in feed.entries:
                if accepted_from_source >= LEAK_ITEMS_PER_SOURCE:
                    break
                published_struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
                title = str(getattr(entry, "title", "")).strip()
                link = str(getattr(entry, "link", "")).strip()
                summary = _clean_summary(getattr(entry, "summary", ""), title)
                if not published_struct:
                    if rejected_entries is not None:
                        record_rejection(rejected_entries, title, link, source["name"],
                                         "لا يوجد تاريخ موثوق", "fetch", summary=summary)
                    continue
                try:
                    published_at = datetime.fromtimestamp(
                        calendar.timegm(published_struct), tz=timezone.utc
                    )
                except (TypeError, ValueError, OverflowError):
                    continue
                if published_at < cutoff:
                    if rejected_entries is not None:
                        record_rejection(rejected_entries, title, link, source["name"],
                                         "أقدم من الحد الزمني المسموح", "age-filter", summary=summary)
                    continue
                if not title or not link:
                    if rejected_entries is not None:
                        record_rejection(rejected_entries, title, link, source["name"],
                                         "عنوان أو رابط مفقود", "validation", summary=summary)
                    continue
                dup, reason = is_duplicate_against_history(title, link, None, history)
                if dup:
                    if rejected_entries is not None:
                        record_rejection(rejected_entries, title, link, source["name"],
                                         f"مكرر في السجل: {reason}", "history-duplicate", summary=summary)
                    continue
                candidates.append({
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "source_name": source["name"],
                    "published_at": published_at.isoformat(),
                })
                accepted_from_source += 1
        except Exception as exc:
            print(f"⚠️ خطأ في جلب مصدر التسريبات {source['name']}: {exc}")
    return dedupe_articles_pool(candidates, rejected_entries)
