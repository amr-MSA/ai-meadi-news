"""نقطة تشغيل خط النشرة اليومية المجدولة."""

import ai_handler
import config
import fetcher
import history_manager
import publisher
import utils


def _is_successful_response(response):
    return response is not None and getattr(response, "status_code", None) == 200


def _response_message_id(response):
    try:
        return response.json()["result"]["message_id"]
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def run():
    if not utils.acquire_lock():
        return
    try:
        missing_vars = [name for name, value in config.REQUIRED_ENV_VARS.items() if not value]
        if missing_vars:
            print(f"❌ متغيرات البيئة التالية غير موجودة: {missing_vars}. إنهاء آمن.")
            return
        history = history_manager.load_history()
        history_manager.prune_history(history)
        history_context = history_manager.get_recent_history_window(
            history, days=config.HISTORY_CONTEXT_WINDOW_DAYS
        )
        articles_pool = fetcher.fetch_news(history)
        if not articles_pool:
            print("⚠️ لا توجد أخبار جديدة خلال آخر أسبوع ولم تتكرر موضوعياً!")
            return

        content, selected_article = _select_unique_article(articles_pool, history_context, history)
        if not content or not selected_article:
            print("❌ لم يتم التوصل لخبر غير مكرر بعد المحاولات المتاحة.")
            return

        ai_handler.save_selected_analysis_to_temp(selected_article, content)
        staged = ai_handler.load_selected_analysis_from_temp()
        if not staged or not staged.get("gemini_analysis"):
            print("❌ تعذر تحميل التحليل الوسيط. إنهاء آمن بدون نشر.")
            return
        selected_article = staged["selected_article"]
        content = staged["gemini_analysis"]
        classification = history_manager.normalize_classification(content.get("classification"))
        title = content.get("title") or selected_article["title"]
        main_event = content.get("main_event_summary") or selected_article["summary"]
        impact = content.get("impact_analysis") or "الأثر قيد التحليل."
        source_name = selected_article["source_name"]
        source_link = selected_article["link"]
        post_content = publisher.build_post_content(
            title, main_event, content.get("technical_details_points", []),
            impact, source_name, source_link
        )

        image_url = publisher.get_og_image(source_link)
        image_bytes = None if image_url else ai_handler.generate_google_imagen(
            content.get("image_prompt") or selected_article["title"]
        )
        tg_res = publisher.publish_to_telegram(title, post_content, image_url, image_bytes)
        if not _is_successful_response(tg_res):
            print("❌ خطأ أثناء النشر على Telegram:", getattr(tg_res, "text", "No response"))
            return

        message_id = _response_message_id(tg_res)
        history_manager.append_to_history(
            history, selected_article["title"], source_link, classification["topic_key"],
            classification=classification, summary=main_event, source_name=source_name,
            telegram_message_id=message_id,
            telegram_message_url=publisher.build_telegram_message_url(message_id),
        )
        selected_id = int(content.get("selected_id", 0)) if str(content.get("selected_id", "")).isdigit() else 0
        important_ids = [
            item_id for item_id in content.get("important_unselected_ids", [])
            if str(item_id).isdigit() and int(item_id) != selected_id
        ]
        history_manager.append_skipped_candidates(
            history, articles_pool, important_ids, content.get("candidate_classifications", [])
        )
        if message_id:
            publisher.send_company_profile_reply(message_id, content.get("company_profile"))
        print("✅ تم النشر وحُفظ الخبر والتصنيف والمرشحون المهمون.")
    finally:
        ai_handler.cleanup_temp_analysis()
        utils.release_lock()


def _select_unique_article(articles_pool, history_context, history):
    for _attempt in range(config.SELECTION_MAX_ATTEMPTS):
        candidate = ai_handler.call_gemini_for_selection(articles_pool, history_context)
        if not isinstance(candidate, dict):
            continue
        try:
            selected_id = int(candidate.get("selected_id"))
        except (TypeError, ValueError):
            continue
        if not 1 <= selected_id <= len(articles_pool):
            continue
        selected_article = articles_pool[selected_id - 1]
        classification = history_manager.normalize_classification(candidate.get("classification"))
        classification["topic_key"] = candidate.get("topic_key") or classification["topic_key"]
        duplicate, reason = history_manager.compare_candidate_to_history(
            selected_article["title"], selected_article["link"], classification, history
        )
        if duplicate:
            print(f"⚠️ الخبر المختار مكرر ({reason})، إعادة المحاولة...")
            continue
        candidate["classification"] = classification
        return candidate, selected_article
    return None, None


if __name__ == "__main__":
    run()
