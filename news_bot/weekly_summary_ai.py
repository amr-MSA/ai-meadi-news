"""توليد الملخص الأسبوعي اعتمادًا على سجل النشرة اليومية."""

from ai_handler import _generate_json_with_retries
from config import WEEKLY_SUMMARY_MAX_CHUNK_CHARACTERS


def _format_items(items):
    lines = []
    for index, item in enumerate(items, start=1):
        lines.append(
            f"ID: {index}\n"
            f"العنوان: {item.get('title', '')}\n"
            f"الملخص: {item.get('summary', '')}\n"
            f"النوع: {item.get('news_type', 'أخرى')}\n"
            f"الشركة: {item.get('company_name', 'غير محدد')}\n"
            f"التاريخ التقريبي: {item.get('event_year_month', 'غير محدد')}\n"
            f"المصدر: {item.get('source_name', '')}\n"
            f"الرابط: {item.get('telegram_message_url') or item.get('link', '')}\n---"
        )
    return "\n".join(lines) or "لا توجد عناصر."


def generate_weekly_summary(daily_items, skipped_items):
    if not daily_items and not skipped_items:
        return None
    prompt = f"""
أنت محرر تقني عربي. اكتب ملخصًا أسبوعيًا تحليليًا اعتمادًا فقط على البيانات المرفقة.
لا تخترع أخبارًا أو أرقامًا أو روابط غير موجودة.

الأخبار المنشورة في النشرة اليومية:
{_format_items(daily_items)}

الأخبار المهمة التي لم تُختر للنشر اليومي:
{_format_items(skipped_items)}

أعد JSON فقط:
{{
  "part1": "الجزء الأول",
  "part2": "الجزء الثاني"
}}

القواعد:
1) part1 يلخص أهم الأخبار المنشورة يوميًا ويحلل الاتجاهات والأثر التقني.
2) part2 يعرض المرشحين المهمين غير المنشورين مع توضيح أنهم لم يُختاروا.
3) لا يتجاوز كل جزء {WEEKLY_SUMMARY_MAX_CHUNK_CHARACTERS} حرفًا.
4) أدرج رابط المصدر أو رسالة Telegram بعد كل خبر عند توفره بصيغة URL عادية.
5) استخدم العربية الفصحى دون أسئلة تفاعلية أو عبارات تسويقية.
"""
    result = _generate_json_with_retries(prompt)
    if not isinstance(result, dict):
        return None
    part1 = str(result.get("part1", "")).strip()
    part2 = str(result.get("part2", "")).strip()
    if not part1 and not part2:
        return None
    return {
        "part1": part1[:WEEKLY_SUMMARY_MAX_CHUNK_CHARACTERS],
        "part2": part2[:WEEKLY_SUMMARY_MAX_CHUNK_CHARACTERS],
    }
