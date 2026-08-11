"""
history_manager.py
=========================================================
كل ما يخص قراءة/كتابة السجل التاريخي (posted_history.json)
والتأكد من عدم تكرار نفس الموضوع.

التعديل الجوهري هنا: بدل الاكتفاء بإرسال "مواضيع الشهر الحالي" فقط
لِلنموذج، أصبحنا نبني "نافذة سياق" من آخر شهرين كاملة (عناوين + مفاتيح
مواضيع + تواريخ) لتُرسل إلى Gemini في ai_handler.py، بحيث يفحص النموذج
نفسه السياق التاريخي بذكاء بدل الاعتماد فقط على مطابقة نصية محلية.
=========================================================
"""

import os
import json
from datetime import datetime, timedelta

from config import HISTORY_FILE, TITLE_SIMILARITY_THRESHOLD, TOPIC_SIMILARITY_THRESHOLD
from utils import similarity


# =========================================================
# قراءة وكتابة السجل
# =========================================================
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                return data if isinstance(data, list) else []
            except Exception:
                return []
    return []


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def append_to_history(history, title, link, topic_key, entry_type="daily", reliability_level=None):
    """
    إضافة الخبر المنشور حديثاً إلى السجل ثم حفظه فوراً على القرص.

    entry_type: "daily" (افتراضي، خط النشرة اليومية) أو "leak" (خط التسريبات).
    استخدام نفس ملف السجل (posted_history.json) للخطين معاً مقصود: بهذا يتحقق
    is_duplicate_against_history تلقائياً من كل الأخبار المنشورة سابقاً — سواء
    كخبر رسمي في النشرة أو كتسريب سريع — فلا يتكرر نفس الحدث بين الخطين.
    reliability_level: يُحفظ فقط لأخبار التسريبات (🔴/🟠/🟡/🟢) للرجوع إليه لاحقاً.
    """
    entry = {
        "title": title,
        "link": link,
        "topic_key": topic_key,
        "month": datetime.now().strftime("%Y-%m"),
        "posted_at": datetime.now().isoformat(),
        "type": entry_type,
    }
    if reliability_level:
        entry["reliability_level"] = reliability_level

    history.append(entry)
    save_history(history)
    return history


# =========================================================
# فحص التكرار مقابل السجل الكامل (يُستخدم في التصفية الأولية للأخبار)
# =========================================================
def is_duplicate_against_history(title, link, topic_key, history):
    """الفحص الثلاثي: الرابط الحرفي + العنوان الحرفي/المتشابه + المفتاح الموضوعي الشهري."""
    current_month = datetime.now().strftime("%Y-%m")
    for item in history:
        if not isinstance(item, dict):
            if item == link:
                return True, "link"
            continue

        if item.get("link") == link:
            return True, "link"

        if item.get("title") and similarity(item["title"], title) >= TITLE_SIMILARITY_THRESHOLD:
            return True, "title-similarity"

        if item.get("month") == current_month and item.get("topic_key") and topic_key:
            if similarity(item["topic_key"], topic_key) >= TOPIC_SIMILARITY_THRESHOLD:
                return True, "topic-key"

    return False, None


# =========================================================
# بناء نافذة السياق التاريخي (آخر N يوماً) لإرسالها إلى Gemini
# =========================================================
def get_recent_history_window(history, days):
    """
    يُرجع قائمة مبسطة (عنوان، مفتاح موضوع، تاريخ نشر) لكل خبر نُشر
    خلال آخر `days` يوماً فقط، ليستخدمها Gemini كسياق كامل عند الاختيار
    بدل مجرد "مواضيع الشهر الحالي" كما كان سابقاً.
    """
    cutoff = datetime.now() - timedelta(days=days)
    window = []
    for item in history:
        if not isinstance(item, dict):
            continue
        posted_at = item.get("posted_at")
        try:
            posted_dt = datetime.fromisoformat(posted_at) if posted_at else None
        except Exception:
            posted_dt = None

        # إن تعذر تحليل التاريخ (سجل قديم بصيغة مختلفة) نُدرجه احتياطاً بدل استبعاده ظلماً
        if posted_dt is None or posted_dt >= cutoff:
            window.append(
                {
                    "title": item.get("title", ""),
                    "topic_key": item.get("topic_key", ""),
                    "posted_at": posted_at or "unknown",
                }
            )
    return window
