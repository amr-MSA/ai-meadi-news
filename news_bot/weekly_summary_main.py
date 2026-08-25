"""نقطة تشغيل الملخص الأسبوعي في بداية كل أسبوع."""

import ai_handler
import history_manager
import publisher
import utils
import weekly_summary_ai

from config import REQUIRED_ENV_VARS, TELEGRAM_WEEKLY_SUMMARY_PREFIX


def _is_successful_response(response):
    return response is not None and getattr(response, "status_code", None) == 200


def _published_daily_items(history):
    return [
        item for item in history
        if isinstance(item, dict)
        and item.get("type", "daily") == "daily"
        and item.get("status", "published") == "published"
    ]


def _important_skipped_items(history):
    return [
        item for item in history
        if isinstance(item, dict)
        and item.get("type") == "daily_candidate"
        and item.get("status") == "skipped"
    ]


def run():
    if not utils.acquire_lock():
        return
    try:
        missing_vars = [name for name, value in REQUIRED_ENV_VARS.items() if not value]
        if missing_vars:
            print(f"❌ متغيرات البيئة التالية غير موجودة: {missing_vars}. إنهاء آمن.")
            return
        history = history_manager.load_history()
        history_manager.prune_history(history)
        daily_items = _published_daily_items(history)
        skipped_items = _important_skipped_items(history)
        if not daily_items and not skipped_items:
            print("🧐 لا توجد أخبار لملخص هذا الأسبوع.")
            return
        summary = weekly_summary_ai.generate_weekly_summary(daily_items, skipped_items)
        if not summary:
            print("❌ تعذر توليد الملخص الأسبوعي.")
            return
        parts = []
        if summary.get("part1"):
            parts.append(f"{TELEGRAM_WEEKLY_SUMMARY_PREFIX}\n\n{summary['part1']}")
        if summary.get("part2"):
            parts.append(summary["part2"])
        for index, part in enumerate(parts, start=1):
            response = publisher.publish_text_to_telegram(part)
            if not _is_successful_response(response):
                print(f"❌ فشل نشر الجزء رقم {index} من الملخص:", getattr(response, "text", "No response"))
                return
            print(f"✅ نُشر الجزء رقم {index} من الملخص الأسبوعي.")
    finally:
        utils.release_lock()


if __name__ == "__main__":
    run()
