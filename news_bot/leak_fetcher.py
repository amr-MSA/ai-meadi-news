"""
leak_fetcher.py
=========================================================
جلب آخر عنصر-عنصرين من كل مصدر تسريبات (leaks_config.LEAK_SOURCES)،
دون أي انتظار أو تأكيد — الهدف الوحيد هنا هو السرعة القصوى.
التحقق من الموثوقية والقيمة الخبرية يحدث لاحقاً في leak_ai_handler.py.

يعيد استخدام دوال fetcher.py و history_manager.py الموجودة أصلاً دون
تعديلها، حفاظاً على الفصل التام بين خط النشرة اليومية وخط التسريبات.
=========================================================
"""

import re
import feedparser

from leaks_config import LEAK_SOURCES, LEAK_ITEMS_PER_SOURCE
from fetcher import dedupe_articles_pool
from history_manager import is_duplicate_against_history


def fetch_leak_candidates(history):
    """
    يُرجع قائمة مرشحين للتسريب: آخر LEAK_ITEMS_PER_SOURCE من كل مصدر،
    بعد استبعاد أي عنصر مُنشر سابقاً (بنفس الرابط/العنوان) حسب السجل
    الموحّد (posted_history.json) الذي يغطي خط النشرة اليومية وخط
    التسريبات معاً.
    """
    candidates = []
    for source in LEAK_SOURCES:
        try:
            feed = feedparser.parse(source["url"])
            latest_entries = feed.entries[:LEAK_ITEMS_PER_SOURCE]
            for entry in latest_entries:
                title = getattr(entry, "title", "").strip()
                link = getattr(entry, "link", "").strip()
                if not title or not link:
                    continue

                dup, _ = is_duplicate_against_history(title, link, None, history)
                if dup:
                    continue

                summary = getattr(entry, "summary", title)
                clean_summary = re.sub("<[^<]+?>", "", summary)[:400]
                candidates.append(
                    {
                        "title": title,
                        "link": link,
                        "summary": clean_summary,
                        "source_name": source["name"],
                    }
                )
        except Exception as e:
            print(f"⚠️ خطأ في جلب مصدر التسريبات {source['name']}: {e}")

    # دمج التسريبات المتشابهة القادمة من أكثر من مصدر دفعة واحدة (نفس منطق fetcher.py)
    return dedupe_articles_pool(candidates)
