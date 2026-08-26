"""سجل مستقل للعناصر التي لم تُنشر مع سبب الرفض للمراجعة والتحسين."""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

from config import REJECTED_HISTORY_FILE, REJECTED_RETENTION_DAYS
from history_manager import normalize_classification
from utils import normalize_text


def load_rejected():
    if not os.path.exists(REJECTED_HISTORY_FILE):
        return []
    try:
        with open(REJECTED_HISTORY_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError) as exc:
        print(f"⚠️ تعذر قراءة سجل المرفوضات، سيُستخدم سجل فارغ: {exc}")
        return []


def save_rejected(entries):
    directory = os.path.dirname(REJECTED_HISTORY_FILE) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".rejected_news.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(entries, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, REJECTED_HISTORY_FILE)
    except Exception:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise


def _parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def prune_rejected(entries, retention_days=REJECTED_RETENTION_DAYS):
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    kept = [
        item for item in entries
        if isinstance(item, dict) and (_parse_datetime(item.get("rejected_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    ]
    removed = len(entries) - len(kept)
    if removed:
        entries[:] = kept
        save_rejected(entries)
    return removed


def _same_item(existing, title, link):
    if link and existing.get("link") == link:
        return True
    return bool(title and normalize_text(existing.get("title", "")) == normalize_text(title))


def record_rejection(
    entries, title, link, source_name, reason, rejection_stage,
    summary="", classification=None, details=None,
):
    if any(_same_item(item, title, link) for item in entries if isinstance(item, dict)):
        return entries
    normalized = normalize_classification(classification)
    entries.append({
        "title": str(title or "").strip(),
        "link": str(link or "").strip(),
        "source_name": str(source_name or "").strip(),
        "summary": str(summary or "").strip()[:500],
        "reason": str(reason or "غير محدد").strip()[:240],
        "rejection_stage": str(rejection_stage or "unknown").strip(),
        "classification": normalized,
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "details": details if isinstance(details, dict) else {},
    })
    return entries
