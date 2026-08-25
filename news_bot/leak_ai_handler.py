"""تقييم مرشحي التسريبات عبر Gemini بصياغة تحريرية مختصرة."""

from ai_handler import _generate_json_with_retries
from leaks_config import RELIABILITY_LEVELS, REQUIRED_LEAK_FIELDS, RELIABILITY_REASON_MAX_CHARACTERS


NEWS_TYPES = (
    "ذكاء اصطناعي",
    "أمن سيبراني",
    "برمجيات",
    "أجهزة وعتاد",
    "أنظمة تشغيل",
    "تطوير وبرمجة",
    "سحابة ومراكز بيانات",
    "أعمال وتقنية",
    "خصوصية وبيانات",
    "أخرى",
)


def evaluate_leak_candidates(candidates_pool):
    """يقيّم المرشحين ويعيد JSON صالحًا أو None."""
    if not candidates_pool:
        return None

    items_text = ""
    for index, item in enumerate(candidates_pool, 1):
        items_text += (
            f"ID: {index} | Source: {item['source_name']}\n"
            f"Title: {item['title']}\nSummary: {item['summary']}\nLink: {item['link']}\n---\n"
        )

    reliability_guide = "\n".join(
        f"{emoji} → {description}" for emoji, description in RELIABILITY_LEVELS.items()
    )

    prompt = f"""
أنت محلل استخبارات تقنية. افحص المرشحين وحدد هل يستحق أحدهم النشر كتسريب عاجل.
لا تنشر الشائعة التافهة أو الخبر المؤكد رسميًا. إذا لم يستحق أي عنصر، أعد selected_id=0.

مقياس الموثوقية:
{reliability_guide}

القواعد:
1) اختر عنصرًا واحدًا فقط عند وجود قيمة خبرية حقيقية.
2) أعد reliability_reason في جملة واحدة مباشرة لا تتجاوز {RELIABILITY_REASON_MAX_CHARACTERS} حرفًا.
   اذكر نوع الدليل أو غيابه فقط، ولا تكتب «تنويه» أو «تحذير» أو شرحًا مطولًا.
3) أعد disclaimer قصيرًا جدًا دون عنوان أو تكرار، مثل: غير مؤكد رسميًا؛ يُنشر لأهميته وسرعته فقط.
4) اكتب title وsummary بالعربية الفصحى. اجعل summary موجزًا ومركزًا على الادعاء الأساسي،
   ولا يتجاوز 700 حرف. لا تضف أرقامًا أو علاقات سببية غير موجودة في بيانات المرشح.
5) اكتب topic_key بالإنجليزية وimage_prompt بالإنجليزية.
6) صنّف الخبر داخل classification وباستخدام news_type واحد فقط من هذه القائمة: {NEWS_TYPES}، أو «أخرى».

أعد JSON فقط بهذا الشكل:
{{
  "selected_id": 0,
  "reliability_level": "🔴",
  "reliability_reason": "مصدر غير رسمي دون تأكيد مستقل.",
  "topic_key": "topic-name",
  "title": "عنوان مباشر للتسريب",
  "summary": "ملخص موجز للادعاء وأهميته التقنية",
  "disclaimer": "غير مؤكد رسميًا؛ يُنشر لأهميته وسرعته فقط.",
  "image_prompt": "Neutral visual description of the subject only",
  "classification": {
    "company_name": "اسم الشركة أو غير محدد",
    "event_year_month": "YYYY-MM أو غير محدد",
    "news_type": "أخرى",
    "product_name": "اسم المنتج أو غير محدد",
    "region": "المنطقة أو غير محدد",
    "topic_key": "topic-name",
    "keywords": ["keyword"]
  }
}}

المرشحون:
{items_text}
"""

    result = _generate_json_with_retries(prompt)
    if not isinstance(result, dict):
        return None

    missing = [field for field in REQUIRED_LEAK_FIELDS if field not in result]
    if missing:
        print(f"❌ رد Gemini (تسريبات) ناقص الحقول المطلوبة: {missing}")
        return None

    try:
        selected_id = int(result.get("selected_id", 0))
    except (TypeError, ValueError):
        print("❌ رد Gemini (تسريبات) يحتوي selected_id غير صالح.")
        return None
    if selected_id < 0:
        print("❌ رد Gemini (تسريبات) يحتوي selected_id سالبًا.")
        return None
    if selected_id and result.get("reliability_level") not in RELIABILITY_LEVELS:
        print("❌ رد Gemini (تسريبات) يحتوي مستوى موثوقية غير معروف.")
        return None
    return result
