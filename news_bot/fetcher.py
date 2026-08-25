"""جلب الأخبار اليومية من مصادر RSS وتصفيتها مبدئيًا."""

import calendar
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from config import (
    ARTICLES_POOL_MAX,
    NEWS_MAX_AGE_DAYS,
    RSS_REQUEST_TIMEOUT_SECONDS,
    RSS_SOURCES,
    TITLE_SIMILARITY_THRESHOLD,
)
from history_manager import is_duplicate_against_history
from utils import similarity

REQUEST_HEADERS = {"User-Agent": "ai-meadi-news/1.0 (+https://github.com/amr-MSA/ai-meadi-news)"}


def _clean_summary(summary, fallback):
    text = re.sub(r"<[^>]+>", " ", str(summary or fallback))
    return re.sub(r"\s+", " ", text).strip()[:300]


def _entry_datetime(entry):
    for field in ("published_parsed", "updated_parsed"):
        value = getattr(entry, field, None)
        if value:
            try:
                return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
    return None


def _fetch_feed(url):
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=RSS_REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return feedparser.parse(response.content)


def fetch_news(history):
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_MAX_AGE_DAYS)
    articles = []
    for source in RSS_SOURCES:
        try:
            feed = _fetch_feed(source["url"])
            if getattr(feed, "bozo", False) and not feed.entries:
                raise ValueError(f"خلاصة RSS غير صالحة: {getattr(feed, 'bozo_exception', 'unknown')}")
            for entry in feed.entries:
                published_at = _entry_datetime(entry)
                if published_at is None or published_at < cutoff:
                    continue
                title = str(getattr(entry, "title", "")).strip()
                link = str(getattr(entry, "link", "")).strip()
                if not title or not link:
                    continue
                dup, _ = is_duplicate_against_history(title, link, None, history)
                if not dup:
                    articles.append({
                        "title": title,
                        "link": link,
                        "summary": _clean_summary(getattr(entry, "summary", ""), title),
                        "source_name": source["name"],
                        "published_at": published_at.isoformat(),
                    })
        except Exception as exc:
            print(f"خطأ في جلب {source['name']}: {exc}")
    return dedupe_articles_pool(articles)[:ARTICLES_POOL_MAX]


def dedupe_articles_pool(articles):
    unique = []
    for article in articles:
        if not any(similarity(article["title"], kept["title"]) >= TITLE_SIMILARITY_THRESHOLD for kept in unique):
            unique.append(article)
    return unique
