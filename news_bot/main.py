"""
main.py
=========================================================
الملف الرئيسي الخفيف الخاص حصراً بـ "النشرة اليومية المجدولة" (4 عصراً).
دوره الوحيد: ربط الوحدات ببعضها بالترتيب المنطقي الصحيح دون أي منطق
تفصيلي بداخله — أي تعديل مستقبلي على التفاصيل يذهب لملفه المختص.

ملاحظة معمارية: هذا الملف مخصص لخط أنابيب "النشرة اليومية" فقط.
أي نظام مستقبلي فرعي (مثلاً "تسريبات عاجلة" بمعدل كل ساعتين) يجب أن
يُبنى كنقطة دخول منفصلة تماماً (مثال: breaking_news_main.py) تستورد
نفس الوحدات (config/fetcher/history_manager/ai_handler/publisher)
دون أي تعديل عليها، حفاظاً على الفصل التام المطلوب.
=========================================================
"""

from datetime import datetime

import config
import utils
import history_manager
import fetcher
import ai_handler
import publisher


def run():
    if not utils.acquire_lock():
        return

    try:
        # 1) التحقق من متغيرات البيئة الأساسية
        missing_vars = [name for name, val in config.REQUIRED_ENV_VARS.items() if not val]
        if missing_vars:
            print(f"❌ متغيرات البيئة التالية غير موجودة: {missing_vars}. إنهاء آمن.")
            return

        # 2) تحميل السجل التاريخي وبناء نافذة سياق آخر شهرين
        history = history_manager.load_history()
        print(f"تم تحميل السجل: {len(history)} خبر منشور.")
        history_context = history_manager.get_recent_history_window(
            history, days=config.HISTORY_CONTEXT_WINDOW_DAYS
        )

        # 3) جلب دفعة الأخبار المرشحة (10-15) من كل المصادر
        articles_pool = fetcher.fetch_news(history)
        if len(articles_pool) < 1:
            print("⚠️ لا توجد أخبار جديدة لم تُنشر من قبل ولم تتكرر موضوعياً!")
            return
        print(f"📦 تم جلب دفعة من {len(articles_pool)} مقالاً مرشحاً لِلنموذج.")

        # 4) اختيار الخبر الأهم عبر Gemini، مع فحص السياق التاريخي الكامل
        content, selected_article = _select_unique_article(articles_pool, history_context, history)
        if not content:
            print("❌ لم يتم التوصل لخبر غير مكرر بعد المحاولات المتاحة. إنهاء آمن بدون نشر.")
            return

        # 5) حفظ التحليل المختار في ملف .txt وسيط (خطوة بينية قبل الصياغة النهائية)
        ai_handler.save_selected_analysis_to_temp(selected_article, content)
        staged = ai_handler.load_selected_analysis_from_temp()
        selected_article = staged["selected_article"]
        content = staged["gemini_analysis"]

        # 6) صياغة القالب النهائي انطلاقاً من الملف الوسيط
        title = content.get("title", selected_article["title"])
        main_event = content.get("main_event_summary", selected_article["summary"])
        tech_details_list = content.get("technical_details_points", [])
        impact = content.get("impact_analysis", "الأثر قيد التحليل.")
        source = selected_article["source_name"]
        topic_key = content.get("topic_key", selected_article["title"][:30])
        image_prompt = content.get("image_prompt", selected_article["title"])
        company_profile = content.get("company_profile")

        post_content = publisher.build_post_content(title, main_event, tech_details_list, impact, source)
        print(f"📌 الخبر المختار: {selected_article['title']}")

        # 7) بروتوكول الصور: صورة حقيقية أولاً، ثم توليد احتياطي عبر Imagen
        image_url = publisher.get_og_image(selected_article["link"])
        image_bytes = None
        if not image_url:
            image_bytes = ai_handler.generate_google_imagen(image_prompt)

        # 8) تحديث السجل التاريخي فوراً (قبل النشر) لضمان عدم التكرار حتى لو فشل النشر جزئياً
        history_manager.append_to_history(history, selected_article["title"], selected_article["link"], topic_key)

        # 9) النشر الفعلي على تيليجرام
        tg_res = publisher.publish_to_telegram(title, post_content, image_url, image_bytes)

        if tg_res is not None and tg_res.status_code == 200:
            print("✅ تم النشر بنجاح على القناة!")
            message_id = tg_res.json()["result"]["message_id"]
            publisher.send_company_profile_reply(message_id, company_profile)
            print("💾 تم حفظ التقرير في السجل لتفعيل الفلترة المستقبلية.")
        else:
            print("❌ خطأ أثناء النشر على تليجرام:", tg_res.text if tg_res is not None else "No response")

        # 10) تنظيف الملف الوسيط بعد اكتمال التشغيل
        ai_handler.cleanup_temp_analysis()

    finally:
        utils.release_lock()


def _select_unique_article(articles_pool, history_context, history):
    """يحاول الحصول على اختيار من Gemini غير مكرر موضوعياً، بحد أقصى
    config.SELECTION_MAX_ATTEMPTS من المحاولات."""
    for attempt in range(config.SELECTION_MAX_ATTEMPTS):
        candidate = ai_handler.call_gemini_for_selection(articles_pool, history_context)
        if not candidate:
            continue

        try:
            selected_id = int(candidate.get("selected_id", 1))
            selected_article = articles_pool[selected_id - 1]
        except Exception:
            selected_article = articles_pool[0]

        topic_key = candidate.get("topic_key", selected_article["title"][:30])
        dup, reason = history_manager.is_duplicate_against_history(
            selected_article["title"], selected_article["link"], topic_key, history
        )
        if dup:
            print(f"⚠️ الاختيار رقم {attempt + 1} مكرر ({reason})، إعادة المحاولة...")
            continue

        return candidate, selected_article

    return None, None


if __name__ == "__main__":
    run()
