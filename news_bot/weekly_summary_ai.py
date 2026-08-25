"""توليد ملخص أسبوعي تحريري من سجل النشرة اليومية."""

from ai_handler import _generate_json_with_retries
from config import WEEKLY_SUMMARY_MAX_CHUNK_CHARACTERS


def _format_items(items):
    lines = []
    for index, item in enumerate(items, start=1):
        link = item.get("telegram_message_url") or item.get("link", "")
        facts = item.get("new_facts") or []
        lines.append(
            f"ID: {index}\n"
            f"العنوان: {item.get('title', '')}\n"
            f"الملخص المتاح: {item.get('summary', '')}\n"
            f"النوع: {item.get('news_type', 'أخرى')} | الشركة: {item.get('company_name', 'غير محدد')}\n"
            f"التاريخ التقريبي: {item.get('event_year_month', 'غير محدد')}\n"
            f"هل هو تحديث: {'نعم' if item.get('is_update') else 'لا'}\n"
            f"حقائق التحديث: {'؛ '.join(map(str, facts)) if facts else 'لا ينطبق'}\n"
            f"المصدر: {item.get('source_name', '')}\n"
            f"رابط الرسالة/المصدر: {link}\n---"
        )
    return "\n".join(lines) or "لا توجد عناصر."


def generate_weekly_summary(daily_items, skipped_items):
    if not daily_items and not skipped_items:
        return None
    prompt = f"""
أنت رئيس تحرير تقني عربي. اكتب ملخصًا أسبوعيًا تحليليًا اعتمادًا حصريًا على البيانات المرفقة.
هذا ليس مكانًا لإعادة نسخ المنشورات: أعد بناء الصورة العامة للأسبوع، واربط الأخبار المتقاربة
في اتجاهات أو محاور، واشرح لماذا تهم القارئ وما الذي تغير. لا تخترع معلومات أو أرقامًا أو روابط.

الأخبار التي نُشرت في النشرة اليومية:
{_format_items(daily_items)}

الأخبار المهمة التي لم تُختر للنشر اليومي:
{_format_items(skipped_items)}

أعد JSON فقط بهذا الشكل:
{{
  "part1": "ملخص تحليلي للأخبار المنشورة",
  "part2": "ملخص تحليلي للأخبار المهمة غير المنشورة"
}}

القواعد التحريرية:
1) ابدأ part1 بفقرة افتتاحية قصيرة تلخص اتجاهات الأسبوع، ثم نظم أهم الأخبار في محاور لا في نسخ حرفي.
2) لكل محور، اذكر الحدث بإيجاز، ثم أضف تفسيرًا مستقلًا لأثره أو دلالته، ثم ضع رابط الرسالة أو المصدر.
3) اجمع التحديثات مع الحدث الأصلي واشرح ما الذي أضافته الحقائق الجديدة، ولا تعرض التحديث كخبر مستقل مكرر.
4) ابدأ part2 بعبارة واضحة أن هذه أخبار مهمة لم تُنشر في النشرة اليومية، ثم لخص قيمتها دون تقديمها كأخبار مؤكدة.
5) لا تكرر العنوان والملخص كما هما، ولا تستخدم مقدمات تسويقية أو أسئلة تفاعلية.
6) حافظ على دقة درجات الموثوقية، ولا تستنتج تأكيدًا من مجرد وجود الخبر في السجل.
7) اجعل كل جزء لا يتجاوز {WEEKLY_SUMMARY_MAX_CHUNK_CHARACTERS} حرفًا، واستخدم العربية الفصحى.
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
