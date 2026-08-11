"""
utils.py
=========================================================
أدوات مساعدة عامة (Cross-cutting) يُعاد استخدامها في أكثر من وحدة:
- تطبيع النصوص وحساب التشابه (يُستخدم في fetcher.py و history_manager.py)
- تطهير الحقول من العبارات المبتذلة وتهريب رموز Markdown (يُستخدم في publisher.py)
- قفل التنفيذ لمنع تشغيل نسختين متزامنتين (يُستخدم في main.py)

تم فصلها هنا بدل تكرارها أو حشرها داخل وحدة منطقية لا تخصها.
=========================================================
"""

import os
import re
import time
import difflib

from config import LOCK_FILE, LOCK_MAX_AGE_SECONDS, FORBIDDEN_PATTERNS


# =========================================================
# 1) قفل تنفيذ بسيط لمنع تشغيل نسختين متزامنتين (Race Condition)
# =========================================================
def acquire_lock():
    if os.path.exists(LOCK_FILE):
        age = time.time() - os.path.getmtime(LOCK_FILE)
        if age < LOCK_MAX_AGE_SECONDS:
            print("🔒 يوجد تشغيل آخر قيد التنفيذ حالياً (Lock نشط). إنهاء آمن لمنع التكرار.")
            return False
        else:
            print("⚠️ تم العثور على قفل قديم متروك من تشغيل سابق فشل، سيتم تجاوزه.")
    try:
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        print(f"⚠️ تعذر إنشاء ملف القفل: {e}")
        return True  # لا نمنع التشغيل بسبب فشل غير متوقع في القفل نفسه


def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass


# =========================================================
# 2) أدوات النص والتشابه (لمنع التكرار الموضوعي الحقيقي)
# =========================================================
def normalize_text(text):
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def similarity(a, b):
    return difflib.SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


# =========================================================
# 3) تطهير النصوص وتهريب Markdown (خاص بمخرجات النشر النهائية)
# =========================================================
def sanitize_field(text):
    """إزالة أي صياغة تسويقية أو سؤال تفاعلي مبتذل قد يتسلل داخل حقول الذكاء الاصطناعي."""
    if not text:
        return text
    cleaned = text
    for pattern in FORBIDDEN_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.MULTILINE).strip()
    return cleaned


def escape_telegram_markdown(text):
    """
    تهريب رموز تنسيق تيليجرام (Markdown القديم) من أي نص ديناميكي (عناوين، تفاصيل، بروفايل شركة...)
    لمنع خطأ "Can't find end of the entity" الناتج عن رمز غير متزاوج مثل _ أو * أو ` أو [
    """
    if not text:
        return text
    for ch in ["_", "*", "`", "["]:
        text = text.replace(ch, "\\" + ch)
    return text
