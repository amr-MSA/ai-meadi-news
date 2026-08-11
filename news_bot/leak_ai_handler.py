"""
leak_ai_handler.py
=========================================================
يرسل مرشحي التسريب إلى Gemini ليقوم بدورين معاً في استدعاء واحد:
1) الحَكَم: هل يستحق أي من هذه العناصر النشر كتسريب/عاجل، أم أنها
   ضجيج/شائعة تافهة/محتوى غير تقني لا يستحق المخاطرة بالنشر؟
2) المحلل: إن استحق، ما هو "مستوى الموثوقية" (🔴🟠🟡🟢) بناءً على قوة
   المصدر وعدد القرائن الداعمة، مع صياغة تحذير صريح للقارئ.

يعيد استخدام _generate_json_with_retries من ai_handler.py لتفادي تكرار
منطق إعادة المحاولة عند الضغط على Gemini.
=========================================================
"""

import json

from ai_handler import _generate_json_with_retries
from leaks_config import RELIABILITY_LEVELS, REQUIRED_LEAK_FIELDS


def evaluate_leak_candidates(candidates_pool):
    """
    candidates_pool: قائمة عناصر (من leak_fetcher.fetch_leak_candidates)، كل عنصر
    يحمل عنوان/رابط/ملخص/اسم المصدر.

    يُعيد قاموساً بالحقول المطلوبة (REQUIRED_LEAK_FIELDS) أو None إن لم يستحق
    أي عنصر النشر (selected_id == 0) أو عند فشل الاتصال.
    """
    if not candidates_pool:
        return None

    items_text = ""
    for idx, item in enumerate(candidates_pool, 1):
        items_text += (
            f"ID: {idx} | Source: {item['source_name']}\n"
            f"Title: {item['title']}\nSummary: {item['summary']}\nLink: {item['link']}\n---\n"
        )

    reliability_guide = "\n".join(f"{emoji} → {desc}" for emoji, desc in RELIABILITY_LEVELS.items())

    prompt = f"""
أنت محلل استخبارات تقنية سريع الحركة يراقب التسريبات والأخبار العاجلة قبل أن
تنتشر في المواقع الشهيرة (مثال واقعي: تسريب كود Anthropic المصدري الذي لم
تُغطِّه المواقع الكبرى إلا بعد فوات الأوان). مهمتك اتخاذ قرار سريع، وليس
التحقق الكامل — السرعة هنا مقصودة وتُقابلها شفافية تامة عن درجة اليقين.

مقياس الموثوقية الذي يجب عليك استخدامه حرفياً (اختر رمزاً واحداً فقط):
{reliability_guide}

قواعد صارمة:
1) افحص كل عنصر في القائمة: هل هو تسريب/خبر تقني عاجل حقيقي يستحق المخاطرة
   بالنشر السريع (كود مصدري، تسريب منتج/نموذج AI قبل الإطلاق الرسمي، اختراق
   بيانات، وثيقة داخلية مسرّبة، إلخ)؟ استبعد الشائعات التافهة، المحتوى غير
   التقني، والأخبار المؤكدة رسمياً أصلاً (تلك تخص النشرة اليومية العادية لا هذا الخط).
2) إن لم يستحق أي عنصر النشر إطلاقاً، أعد "selected_id": 0 وباقي الحقول فارغة.
3) إن وُجد عنصر يستحق، اختر واحداً فقط (الأهم/الأخطر)، وحدد "reliability_level"
   بدقة حسب المقياس أعلاه، مع "reliability_reason" (سبب مختصر وصادق لهذا التصنيف).
4) "disclaimer" يجب أن يكون تحذيراً صريحاً وواضحاً للقارئ باللغة العربية يوضح
   أن هذا الخبر لم يُؤكد رسمياً بعد ويُنشر لأهميته وسرعته فقط.
5) "topic_key" بالإنجليزية بصيغة قصيرة وموحّدة، و"image_prompt" وصف بصري محايد بالإنجليزية.
6) "title" و"summary" بلغة عربية فصيحة مباشرة، بدون أي مقدمات تسويقية أو أسئلة تفاعلية.

أعد فقط كائن JSON بالهيكل التالي (بدون أي نص خارج الـ JSON):
{{
  "selected_id": 0,
  "reliability_level": "🔴",
  "reliability_reason": "سبب التصنيف",
  "topic_key": "topic-name",
  "title": "عنوان مباشر للتسريب",
  "summary": "شرح مختصر ومباشر لما تم تسريبه ولماذا يهم القارئ التقني",
  "disclaimer": "نص تحذير صريح بعدم التأكد الرسمي",
  "image_prompt": "Neutral visual description of the subject only"
}}

العناصر المرشحة لهذه الجولة:
{items_text}
"""

    result = _generate_json_with_retries(prompt)
    if not result:
        return None

    missing = [f for f in REQUIRED_LEAK_FIELDS if f not in result]
    if missing:
        print(f"❌ رد Gemini (تسريبات) ناقص الحقول المطلوبة: {missing}")
        return None

    return result
