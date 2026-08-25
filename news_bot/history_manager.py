"""إدارة سجل الأخبار والتصنيفات ومنع تكرار الأحداث عبر الزمن."""

import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone

from config import (
    HISTORY_FILE,
    HISTORY_RETENTION_DAYS,
    NEWS_TYPES,
    TITLE_SIMILARITY_THRESHOLD,
    TOPIC_SIMILARITY_THRESHOLD,
)
from utils import normalize_text, similarity

UNKNOWN = "غير محدد"
CLASSIFICATION_FIELDS = (
    "company_name",
    "event_year_month",
    "news_type",
    "product_name",
    "region",
)


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("history"), list):
            return data["history"]
        return []
    except (OSError, json.JSONDecodeError) as exc:
        print(f"⚠️ تعذر قراءة السجل التاريخي، سيُستخدم سجل فارغ مؤقتاً: {exc}")
        return []


def save_history(history):
    """حفظ السجل بطريقة ذرية حتى لا يبقى JSON مبتوراً عند توقف العملية."""
    directory = os.path.dirname(HISTORY_FILE) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".posted_history.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(history, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, HISTORY_FILE)
    except Exception:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise


def _clean_value(value, fallback=UNKNOWN):
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def normalize_classification(classification=None):
    classification = classification if isinstance(classification, dict) else {}
    news_type = _clean_value(classification.get("news_type"), "أخرى")
    if news_type not in NEWS_TYPES:
        news_type = "أخرى"

    event_year_month = _clean_value(classification.get("event_year_month"))
    if event_year_month != UNKNOWN and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", event_year_month):
        event_year_month = UNKNOWN

    keywords = classification.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = []
    keywords = [_clean_value(keyword, "") for keyword in keywords]
    keywords = [keyword for keyword in keywords if keyword][:8]

    return {
        "company_name": _clean_value(classification.get("company_name")),
        "event_year_month": event_year_month,
        "news_type": news_type,
        "product_name": _clean_value(classification.get("product_name")),
        "region": _clean_value(classification.get("region")),
        "topic_key": _clean_value(classification.get("topic_key")),
        "keywords": keywords,
    }


def _exact_classification_match(candidate, existing):
    candidate = normalize_classification(candidate)
    existing = normalize_classification(existing)
    comparable = [
        field for field in CLASSIFICATION_FIELDS
        if candidate.get(field) not in (None, "", UNKNOWN)
        and existing.get(field) not in (None, "", UNKNOWN)
    ]
    if len(comparable) < 3:
        return False
    return all(normalize_text(candidate[field]) == normalize_text(existing[field]) for field in comparable)


def compare_candidate_to_history(title, link, classification, history):
    """يفحص المرشح مقابل كل عنصر في JSON ويعيد سبب أول تطابق مؤكد."""
    candidate = normalize_classification(classification)
    title = _clean_value(title, "")
    link = _clean_value(link, "")

    for item in history:
        if not isinstance(item, dict):
            if link and item == link:
                return True, "link"
            continue
        if link and item.get("link") == link:
            return True, "link"
        item_title = item.get("title")
        if item_title and title and similarity(item_title, title) >= TITLE_SIMILARITY_THRESHOLD:
            return True, "title-similarity"
        if _exact_classification_match(candidate, item):
            return True, "classification-exact"
        existing_topic = _clean_value(item.get("topic_key"), "")
        if candidate.get("topic_key") not in ("", UNKNOWN) and existing_topic:
            if similarity(existing_topic, candidate["topic_key"]) >= TOPIC_SIMILARITY_THRESHOLD:
                return True, "topic-key"
    return False, None


def is_duplicate_against_history(title, link, topic_key, history, classification=None):
    classification = dict(classification or {})
    classification.setdefault("topic_key", topic_key or UNKNOWN)
    return compare_candidate_to_history(title, link, classification, history)


def _parse_posted_at(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def prune_history(history, retention_days=HISTORY_RETENTION_DAYS):
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    kept = []
    removed = 0
    for item in history:
        if not isinstance(item, dict):
            removed += 1
            continue
        added_at = _parse_posted_at(item.get("posted_at"))
        if added_at is None or added_at < cutoff:
            removed += 1
        else:
            kept.append(item)
    if removed:
        history[:] = kept
        save_history(history)
        print(f"🧹 حُذف {removed} سجلًا تجاوز سبعة أيام من تاريخ إضافته.")
    return removed


def _build_entry(title, link, topic_key, entry_type, classification, summary, source_name, status):
    now = datetime.now(timezone.utc)
    normalized = normalize_classification({**(classification or {}), "topic_key": topic_key})
    return {
        "title": _clean_value(title, ""),
        "link": _clean_value(link, ""),
        "summary": _clean_value(summary, ""),
        "source_name": _clean_value(source_name, ""),
        "topic_key": normalized["topic_key"],
        "company_name": normalized["company_name"],
        "event_year_month": normalized["event_year_month"],
        "news_type": normalized["news_type"],
        "product_name": normalized["product_name"],
        "region": normalized["region"],
        "keywords": normalized["keywords"],
        "month": now.strftime("%Y-%m"),
        "posted_at": now.isoformat(),
        "type": entry_type,
        "status": status,
    }


def append_to_history(
    history, title, link, topic_key, entry_type="daily", reliability_level=None,
    classification=None, summary="", source_name="", telegram_message_id=None,
    telegram_message_url=None,
):
    """إضافة خبر منشور بعد نجاح الإرسال فقط."""
    entry = _build_entry(title, link, topic_key, entry_type, classification, summary, source_name, "published")
    if reliability_level:
        entry["reliability_level"] = reliability_level
    if telegram_message_id:
        entry["telegram_message_id"] = telegram_message_id
    if telegram_message_url:
        entry["telegram_message_url"] = telegram_message_url
    history.append(entry)
    save_history(history)
    return history


def append_skipped_candidates(history, candidates, important_ids, classifications=None):
    """حفظ الأخبار المهمة التي لم تُختر لتظهر في الملخص الأسبوعي."""
    classifications = classifications if isinstance(classifications, list) else []
    important_ids = {int(item) for item in (important_ids or []) if str(item).isdigit()}
    by_id = {
        int(item.get("id")): item for item in classifications
        if isinstance(item, dict) and str(item.get("id", "")).isdigit()
    }
    for index, candidate in enumerate(candidates, start=1):
        if index not in important_ids:
            continue
        details = by_id.get(index, {})
        entry = _build_entry(
            candidate.get("title"), candidate.get("link"),
            details.get("topic_key", candidate.get("title", "")[:30]),
            "daily_candidate", details, candidate.get("summary", ""),
            candidate.get("source_name", ""), "skipped",
        )
        entry["selection_reason"] = _clean_value(details.get("selection_reason"), "خبر مهم لم يُختر للنشر اليوم")
        history.append(entry)
    if important_ids:
        save_history(history)
    return history


def get_recent_history_window(history, days):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    window = []
    for item in history:
        if not isinstance(item, dict):
            continue
        posted_dt = _parse_posted_at(item.get("posted_at"))
        if posted_dt is None or posted_dt >= cutoff:
            window.append({
                "title": item.get("title", ""),
                "topic_key": item.get("topic_key", ""),
                "company_name": item.get("company_name", UNKNOWN),
                "event_year_month": item.get("event_year_month", UNKNOWN),
                "news_type": item.get("news_type", "أخرى"),
                "posted_at": item.get("posted_at") or "unknown",
            })
    return window
