"""نقطة تشغيل خط رصد التسريبات والأخبار العاجلة."""

import ai_handler
import history_manager
import leak_ai_handler
import leak_fetcher
import leak_publisher
import leaks_config
import publisher
import rejected_news_manager
import utils


def _is_successful_response(response):
    return response is not None and getattr(response, "status_code", None) == 200


def _image_allowed_for_reliability(level):
    levels = list(leaks_config.RELIABILITY_LEVELS)
    try:
        return levels.index(level) >= levels.index(leaks_config.LEAK_IMAGE_MIN_RELIABILITY)
    except ValueError:
        return False


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
    rejected_entries = None
    try:
        missing_vars = [
            name for name, value in leaks_config.REQUIRED_LEAK_ENV_VARS.items() if not value
        ]
        if missing_vars:
            print(f"❌ متغيرات البيئة التالية غير موجودة: {missing_vars}. إنهاء آمن.")
            return
        history = history_manager.load_history()
        history_manager.prune_history(history)
        rejected_entries = rejected_news_manager.load_rejected()
        rejected_news_manager.prune_rejected(rejected_entries)
        candidates = leak_fetcher.fetch_leak_candidates(history, rejected_entries)
        if not candidates:
            print("🧐 لا توجد عناصر جديدة من مصادر التسريبات هذه الجولة.")
            return
        history_context = history_manager.get_recent_history_window(history, 60)
        verdict = leak_ai_handler.evaluate_leak_candidates(candidates, history_context)
        if not isinstance(verdict, dict):
            for candidate in candidates:
                rejected_news_manager.record_rejection(
                    rejected_entries, candidate.get("title"), candidate.get("link"),
                    candidate.get("source_name"), "تعذر تقييم المرشح عبر Gemini", "gemini-evaluation",
                    summary=candidate.get("summary", ""),
                )
            return
        try:
            selected_id = int(verdict.get("selected_id", 0))
        except (TypeError, ValueError):
            return
        if selected_id == 0:
            for candidate in candidates:
                rejected_news_manager.record_rejection(
                    rejected_entries, candidate.get("title"), candidate.get("link"),
                    candidate.get("source_name"), "لم يحدد Gemini قيمة خبرية كافية للنشر", "gemini-selection",
                    summary=candidate.get("summary", ""),
                )
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
            rejected_news_manager.record_rejection(
                rejected_entries, selected.get("title"), selected.get("link"),
                selected.get("source_name"), "الموثوقية أقل من حد النشر", "reliability-filter",
                summary=selected.get("summary", ""),
            )
            return

        classification = history_manager.normalize_classification({
            **(verdict.get("classification") or {}),
            "topic_key": verdict.get("topic_key"),
        })
        selection_decision = verdict.get("selection_decision", "new")
        new_facts = verdict.get("new_facts", [])
        comparison = history_manager.classify_candidate_against_history(
            selected["title"], selected["link"], classification, history,
            selection_decision=selection_decision, new_facts=new_facts,
        )
        if comparison["action"] == "duplicate":
            rejected_news_manager.record_rejection(
                rejected_entries, selected.get("title"), selected.get("link"),
                selected.get("source_name"),
                f"مكرر أو بلا تحديث جوهري: {comparison['reason']}", "history-duplicate",
                summary=selected.get("summary", ""), classification=classification,
            )
            print(f"⚠️ الخبر المختار مكرر أو بلا تحديث جوهري ({comparison['reason']})، تجاهل النشر.")
            return
        is_update = comparison["action"] == "update"
        new_facts = comparison.get("novel_facts", new_facts)
        existing = comparison.get("existing") or {}

        title = verdict.get("title") or selected["title"]
        summary = verdict.get("summary") or selected["summary"]
        image_url = None
        image_bytes = None
        image_note = None
        if _image_allowed_for_reliability(reliability_level):
            image_url = publisher.get_leak_og_image(selected["link"])
            if image_url:
                image_note = leaks_config.LEAK_SOURCE_IMAGE_NOTE
            elif leaks_config.LEAK_IMAGE_FALLBACK_ENABLED:
                image_bytes = ai_handler.generate_google_imagen(
                    verdict.get("image_prompt") or selected["title"],
                    image_kind="leak_illustration",
                )
                if image_bytes:
                    image_note = leaks_config.LEAK_AI_IMAGE_NOTE
        else:
            print("ℹ️ لن تُرفق صورة لأن مستوى موثوقية التسريب منخفض جدًا.")
        post_content = leak_publisher.build_leak_post_content(
            reliability_level,
            verdict.get("reliability_reason"),
            title,
            summary,
            verdict.get("disclaimer"),
            selected["source_name"],
            selected["link"],
            image_note=image_note,
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
            is_update=is_update, update_summary=verdict.get("update_summary", ""),
            new_facts=new_facts, updates_event_key=history_manager.build_event_key(classification),
            supersedes_posted_at=existing.get("posted_at") if is_update else None,
        )
        for candidate in candidates:
            if candidate.get("link") == selected.get("link"):
                continue
            rejected_news_manager.record_rejection(
                rejected_entries, candidate.get("title"), candidate.get("link"),
                candidate.get("source_name"), "لم يُختر للتسريبات في هذه الجولة", "gemini-selection",
                summary=candidate.get("summary", ""),
            )
        print("✅ تم نشر التسريب وحفظه بعد نجاح الإرسال.")
    finally:
        if rejected_entries is not None:
            rejected_news_manager.save_rejected(rejected_entries)
        utils.release_lock()


if __name__ == "__main__":
    run()
