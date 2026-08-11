"""
fetcher.py
=========================================================
جلب الأخبار من مصادر RSS، وتصفيتها مبدئياً:
1) استبعاد أي خبر مطابق حرفياً أو شبه مطابق لسجل سابق (فلترة أولية سريعة).
2) دمج الأخبار المتشابهة القادمة من مصادر مختلفة (نفس الحدث بروابط
   مختلفة) والاحتفاظ بنسخة واحدة فقط قبل حتى إرسالها لِلنموذج.

هذا الملف لا يقرر أبداً "الأهم" بين الأخبار — هذا القرار أصبح بالكامل
من اختصاص Gemini في ai_handler.py، بعد أن يستلم دفعة المقالات + السياق
التاريخي معاً (انظر config.ARTICLES_POOL_MIN/MAX).
=========================================================
"""

import re
import feedparser

from config import RSS_SOURCES, TITLE_SIMILARITY_THRESHOLD, ARTICLES_POOL_MAX
from utils import similarity
from history_manager import is_duplicate_against_history


def fetch_news(history):
    """يجلب الأخبار من كل المصادر، يستبعد المكرر مقابل السجل، ثم يُعيد
    دفعة نظيفة (بحد أقصى ARTICLES_POOL_MAX) جاهزة لإرسالها إلى Gemini."""
    articles = []
    for source in RSS_SOURCES:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries:
                dup, _ = is_duplicate_against_history(entry.title, entry.link, None, history)
                if not dup:
                    summary = getattr(entry, "summary", entry.title)
                    clean_summary = re.sub("<[^<]+?>", "", summary)[:300]
                    articles.append(
                        {
                            "title": entry.title,
                            "link": entry.link,
                            "summary": clean_summary,
                            "source_name": source["name"],
                        }
                    )
        except Exception as e:
            print(f"خطأ في جلب {source['name']}: {e}")

    unique_articles = dedupe_articles_pool(articles)
    return unique_articles[:ARTICLES_POOL_MAX]


def dedupe_articles_pool(articles):
    """
    قبل حتى إرسال الأخبار إلى Gemini: تجميع الأخبار المتشابهة القادمة من مصادر مختلفة
    (نفس الحدث بروابط وعناوين مختلفة) والاحتفاظ بنسخة واحدة فقط.
    هذا يمنع مباشرة سيناريو "نفس خبر ميتا من مصدرين مختلفين" حتى قبل وصوله للنموذج.
    """
    unique = []
    for art in articles:
        is_dup = False
        for kept in unique:
            if similarity(art["title"], kept["title"]) >= TITLE_SIMILARITY_THRESHOLD:
                is_dup = True
                break
        if not is_dup:
            unique.append(art)
    return unique
