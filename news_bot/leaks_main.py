"""
leaks_main.py
=========================================================
نقطة دخول منفصلة تماماً عن main.py (خط النشرة اليومية)، مخصصة لخط
"رصد التسريبات والأخبار العاجلة" (يعمل كل ساعتين عبر GitHub Actions).

الفلسفة: نخاطر بموثوقية الخبر مقابل السرعة، لكن نُصرّح بذلك دائماً
عبر شارة موثوقية (🔴🟠🟡🟢) وتحذير صريح في كل منشور.

لا يُعدَّل أي من الوحدات المشتركة (config/utils/history_manager/fetcher/
ai_handler/publisher) هنا — هذا الملف يستوردها فقط، تماماً كما هو مخطط
له في main.py الأصلي.
=========================================================
"""

import utils
import history_manager
import ai_handler
import publisher

import leaks_config
import leak_fetcher
import leak_ai_handler
import leak_publisher


def run():
    if not utils.acquire_lock():
        return

    try:
        missing_vars = [name for name, val in leaks_config.REQUIRED_LEAK_ENV_VARS.items() if not val]
        if missing_vars:
            print(f"❌ متغيرات البيئة التالية غير موجودة (خط التسريبات): {missing_vars}. إنهاء آمن.")
            return

        # السجل موحّد مع خط النشرة اليومية، لضمان عدم تكرار نفس الحدث بين الخطين
        history = history_manager.load_history()

        candidates = leak_fetcher.fetch_leak_candidates(history)
        if not candidates:
            print("🧐 لا توجد عناصر جديدة من مصادر التسريبات هذه الجولة.")
            return
        print(f"📡 تم جلب {len(candidates)} مرشحاً محتملاً للتسريب.")

        verdict = leak_ai_handler.evaluate_leak_candidates(candidates)
        if not verdict:
            print("⚠️ تعذر الحصول على تقييم من Gemini هذه الجولة.")
            return

        try:
            selected_id = int(verdict.get("selected_id", 0))
        except Exception:
            selected_id = 0

        if selected_id == 0:
            print("🧐 قرار Gemini: لا يوجد خبر يستحق المخاطرة بالنشر هذه الجولة.")
            return

        try:
            selected = candidates[selected_id - 1]
        except (IndexError, TypeError):
            print("⚠️ selected_id غير صالح من رد Gemini، تجاهل هذه الجولة.")
            return

        reliability_level = verdict.get("reliability_level", "🔴")
        topic_key = verdict.get("topic_key", selected["title"][:30])

        # فحص تكراري أخير مقابل السجل الموحّد (طبقة أمان إضافية قبل النشر الفعلي)
        dup, reason = history_manager.is_duplicate_against_history(
            selected["title"], selected["link"], topic_key, history
        )
        if dup:
            print(f"⚠️ الخبر المختار مكرر ({reason})، تجاهل النشر لتفادي الازدواجية.")
            return

        title = verdict.get("title", selected["title"])
        summary = verdict.get("summary", selected["summary"])
        disclaimer = verdict.get("disclaimer", "هذا الخبر غير مؤكد رسمياً بعد.")
        image_prompt = verdict.get("image_prompt", selected["title"])
        reliability_reason = verdict.get("reliability_reason", "")
        source = selected["source_name"]

        post_content = leak_publisher.build_leak_post_content(
            reliability_level, reliability_reason, title, summary, disclaimer, source
        )
        print(f"🚨 تسريب مختار [{reliability_level}]: {selected['title']}")

        # بروتوكول الصور نفسه المستخدم في النشرة اليومية (صورة حقيقية أولاً، ثم توليد احتياطي)
        image_url = publisher.get_og_image(selected["link"])
        image_bytes = None
        if not image_url:
            image_bytes = ai_handler.generate_google_imagen(image_prompt)

        # تحديث السجل الموحّد قبل النشر لضمان عدم تكرار نفس التسريب لاحقاً حتى لو فشل الإرسال جزئياً
        history_manager.append_to_history(
            history, selected["title"], selected["link"], topic_key,
            entry_type="leak", reliability_level=reliability_level,
        )

        tg_res = leak_publisher.publish_leak_to_telegram(
            reliability_level, title, post_content, image_url, image_bytes
        )

        if tg_res is not None and tg_res.status_code == 200:
            print("✅ تم نشر التسريب بنجاح مع شارة الموثوقية والتحذير.")
        else:
            print("❌ خطأ أثناء نشر التسريب على تيليجرام:", tg_res.text if tg_res is not None else "No response")

    finally:
        utils.release_lock()


if __name__ == "__main__":
    run()
