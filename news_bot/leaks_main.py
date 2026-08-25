"""نقطة تشغيل خط رصد التسريبات والأخبار العاجلة."""

import ai_handler
import history_manager
import leak_ai_handler
import leak_fetcher
import leak_publisher
import leaks_config
import publisher
import utils


def _is_successful_response(response):
    return response is not None and getattr(response, "status_code", None) == 200


def _meets_reliability_threshold(level):
    minimum = leaks_config.MIN_RELIABILITY_TO_PUBLISH
    if minimum is None:
        return True
    levels = list(leaks_config.RELIABILITY_LEVELS)
    try:
        return levels.index(level) >= levels.index(minimum)
    except ValueError:
        return False


def run():
    if not utils.acquire_lock():
        return
    try:
        missing_vars = [
            name for name, value in leaks_config.REQUIRED_LEAK_ENV_VARS.items() if not value
        ]
        if missing_vars:
            print(f"❌ متغيرات البيئة التالية غير موجودة: {missing_vars}. إنهاء آمن.")
            return
        history = history_manager.load_history()
        history_manager.prune_history(history)
        candidates = leak_fetcher.fetch_leak_candidates(history)
        if not candidates:
            print("🧐 لا توجد عناصر جديدة من مصادر التسريبات هذه الجولة.")
            return
        verdict = leak_ai_handler.evaluate_leak_candidates(candidates)
        if not isinstance(verdict, dict):
            return
        try:
            selected_id = int(verdict.get("selected_id", 0))
        except (TypeError, ValueError):
            return
        if selected_id == 0:
            print("🧐 لا يوجد خبر يستحق النشر هذه الجولة.")
            return
        if not 1 <= selected_id <= len(candidates):
            print("⚠️ selected_id غير صالح، تجاهل هذه الجولة.")
            return

        selected = candidates[selected_id - 1]
        reliability_level = verdict.get("reliability_level")
        if reliability_level not in leaks_config.RELIABILITY_LEVELS:
            return
        if not _meets_reliability_threshold(reliability_level):
            return

        classification = history_manager.normalize_classification({
            **(verdict.get("classification") or {}),
            "topic_key": verdict.get("topic_key"),
        })
        duplicate, reason = history_manager.compare_candidate_to_history(
            selected["title"], selected["link"], classification, history
        )
        if duplicate:
            print(f"⚠️ الخبر المختار مكرر ({reason})، تجاهل النشر.")
            return

        title = verdict.get("title") or selected["title"]
        summary = verdict.get("summary") or selected["summary"]
        post_content = leak_publisher.build_leak_post_content(
            reliability_level,
            verdict.get("reliability_reason"),
            title,
            summary,
            verdict.get("disclaimer"),
            selected["source_name"],
            selected["link"],
        )
        image_url = publisher.get_og_image(selected["link"])
        image_bytes = None if image_url else ai_handler.generate_google_imagen(
            verdict.get("image_prompt") or selected["title"]
        )
        tg_res = leak_publisher.publish_leak_to_telegram(
            reliability_level, title, post_content, image_url, image_bytes
        )
        if not _is_successful_response(tg_res):
            print("❌ فشل نشر التسريب:", getattr(tg_res, "text", "No response"))
            return

        message_id = None
        try:
            message_id = tg_res.json()["result"]["message_id"]
        except (AttributeError, KeyError, TypeError, ValueError):
            pass
        history_manager.append_to_history(
            history, selected["title"], selected["link"], classification["topic_key"],
            entry_type="leak", reliability_level=reliability_level,
            classification=classification, summary=summary, source_name=selected["source_name"],
            telegram_message_id=message_id,
            telegram_message_url=publisher.build_telegram_message_url(
                message_id, leaks_config.LEAK_TELEGRAM_CHAT_ID
            ),
        )
        print("✅ تم نشر التسريب وحفظه بعد نجاح الإرسال.")
    finally:
        utils.release_lock()


if __name__ == "__main__":
    run()
