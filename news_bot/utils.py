"""أدوات القفل والتطبيع والتنظيف المشتركة بين مسارات الأخبار."""

import difflib
import os
import re
import time

from config import FORBIDDEN_PATTERNS, LOCK_FILE, LOCK_MAX_AGE_SECONDS


def acquire_lock():
    """إنشاء قفل ذري قدر الإمكان، مع تجاوز الأقفال القديمة فقط."""
    try:
        if os.path.exists(LOCK_FILE):
            age = time.time() - os.path.getmtime(LOCK_FILE)
            if age < LOCK_MAX_AGE_SECONDS:
                print("🔒 يوجد تشغيل آخر قيد التنفيذ حالياً، إنهاء آمن لمنع التكرار.")
                return False
            print("⚠️ تم العثور على قفل قديم، سيتم تجاوزه.")
            try:
                os.remove(LOCK_FILE)
            except FileNotFoundError:
                pass
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
            lock_file.write(str(os.getpid()))
        return True
    except FileExistsError:
        print("🔒 تم الحصول على القفل من تشغيل آخر، إنهاء آمن.")
        return False
    except Exception as exc:
        print(f"⚠️ تعذر إنشاء ملف القفل: {exc}")
        return True


def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"⚠️ تعذر حذف ملف القفل: {exc}")


def normalize_text(text):
    if not text:
        return ""
    text = str(text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def similarity(a, b):
    return difflib.SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def sanitize_field(text):
    if text is None:
        return ""
    cleaned = str(text)
    for pattern in FORBIDDEN_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.MULTILINE).strip()
    return cleaned


def escape_telegram_markdown(text):
    if text is None:
        return ""
    text = str(text)
    for character in ["_", "*", "`", "["]:
        text = text.replace(character, "\\" + character)
    return text
