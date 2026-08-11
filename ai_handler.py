"""
ai_handler.py
=========================================================
كل ما يخص التعامل مع Gemini لخط "النشرة اليومية":
1) اختيار أهم خبر من دفعة المقالات (10-15) مع فحص سياقي لسجل آخر شهرين
   لاستبعاد أي تكرار موضوعي بذكاء (بدل فلترة نصية محلية فقط).
2) حفظ الاختيار/التحليل الناتج في ملف نصي مؤقت (.txt) كخطوة وسيطة،
   قبل الانتقال لمرحلة صياغة القالب النهائي في publisher.py.
3) توليد صورة احتياطية عبر Google Imagen عند غياب صورة حقيقية للمقال.

كما يحتوي على `_generate_json_with_retries()`: دالة عامة منخفضة المستوى
لاستدعاء Gemini وإعادة محاولة تلقائية عند الضغط، يعاد استخدامها من طرف
leak_ai_handler.py (خط التسريبات) لتفادي تكرار نفس منطق إعادة المحاولة.
=========================================================
"""

import os
import json
import time
import base64
import requests

from google import genai
from google.genai import types

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_MAX_RETRIES,
    GEMINI_RETRY_DELAY_SECONDS,
    REQUIRED_GEMINI_FIELDS,
    IMAGEN_STYLE_WRAPPER,
    TEMP_ANALYSIS_FILE,
)


# =========================================================
# 0) دالة عامة منخفضة المستوى: استدعاء Gemini + إعادة محاولة تلقائية
# =========================================================
def _generate_json_with_retries(prompt):
    """
    يستدعي Gemini بنص الطلب الكامل (prompt) ويُعيد JSON مُحلَّلاً كقاموس Python.
    يعيد المحاولة تلقائياً حتى GEMINI_MAX_RETRIES مرات عند ضغط السيرفر (503) أو أي استثناء.
    دالة عامة (لا تفرض حقولاً محددة) يستخدمها كل من call_gemini_for_selection هنا
    و leak_ai_handler.evaluate_leak_candidates في خط التسريبات.
    """
    if not GEMINI_API_KEY:
        print("❌ مفتاح GEMINI_API_KEY غير مضاف.")
        return None

    client = genai.Client(api_key=GEMINI_API_KEY)
    for attempt in range(GEMINI_MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"⚠️ محاولة {attempt + 1} فشلت بسبب الضغط أو استثناء: {e}")
            if attempt < GEMINI_MAX_RETRIES - 1:
                time.sleep(GEMINI_RETRY_DELAY_SECONDS)
            else:
                print("❌ استنفدت محاولات الاتصال بـ Gemini.")
                return None
    return None


# =========================================================
# 1) اختيار الخبر الأهم مع الفحص السياقي التاريخي
# =========================================================
def call_gemini_for_selection(articles_pool, history_context):
    """
    articles_pool: دفعة من 10-15 مقالاً مرشحاً (قادمة من fetcher.py).
    history_context: نافذة سجل آخر شهرين (قادمة من history_manager.get_recent_history_window)
                      تُرسل كاملة لِلنموذج ليقارن دلالياً ويستبعد أي تكرار موضوعي بنفسه.
    """
    if not GEMINI_API_KEY:
        print("❌ مفتاح GEMINI_API_KEY غير مضاف.")
        return None

    news_text = ""
    for idx, item in enumerate(articles_pool, 1):
        news_text += (
            f"ID: {idx} | Source: {item['source_name']}\n"
            f"Title: {item['title']}\nSummary: {item['summary']}\nLink: {item['link']}\n---\n"
        )

    history_text = json.dumps(history_context, ensure_ascii=False, indent=2) if history_context else "[]"

    system_prompt = f"""
أنت محلّل تقني محترف في قناة Eng. Limitless الموجهة لمهندسي وطلاب الحاسوب.

فيما يلي سجل كامل بكل الأخبار المنشورة خلال آخر شهرين (عنوان + مفتاح موضوع + تاريخ نشر).
افحص هذا السجل بعناية، وامنع نهائياً اختيار أي خبر من الدفعة الحالية يغطي نفس الحدث أو نفس
الموضوع الجوهري لأي عنصر فيه، حتى لو جاء بصياغة مختلفة أو من مصدر مختلف:

سجل آخر شهرين:
{history_text}

قواعد صارمة يجب الالتزام بها دون استثناء:
1) اختر خبراً واحداً فقط من الدفعة الحالية، هو الأهم تقنياً، ولم يُغطَّ من قبل بأي صياغة حسب السجل أعلاه.
2) استخرج "topic_key" بالإنجليزية بصيغة قصيرة وموحّدة (مثال: Meta-Glimmer-AI).
3) اكتب "image_prompt" كوصف بصري موضوعي محايد لموضوع الخبر فقط باللغة الإنجليزية.
4) املأ الحقول التالية حصراً بمحتوى معلوماتي مباشر بلغة عربية فصيحة وقوية، بدون أي مقدمات تسويقية وبدون أي سؤال تفاعلي إطلاقاً.

أعد فقط كائن JSON بالهيكل التالي:
{{
  "selected_id": 1,
  "topic_key": "topic-name",
  "image_prompt": "Neutral visual description of the subject only",
  "title": "العنوان الرئيسي المباشر للخبر",
  "main_event_summary": "شرح مفصل ومباشر للحدث بدون مقدمات",
  "technical_details_points": ["تفصيل تقني أو رقم 1", "تفصيل تقني أو رقم 2"],
  "impact_analysis": "الأثر المباشر على المجال والطلاب",
  "company_profile": "بطاقة تعريف بالشركة إن وجدت أو null"
}}
"""

    full_prompt = f"{system_prompt}\n\nالأخبار المتاحة حالياً:\n{news_text}"
    content = _generate_json_with_retries(full_prompt)
    if not content:
        return None

    missing = [f for f in REQUIRED_GEMINI_FIELDS if f not in content]
    if missing:
        print(f"❌ رد Gemini ناقص الحقول المطلوبة: {missing}")
        return None
    return content


# =========================================================
# 2) الملف الوسيط: حفظ/تحميل/تنظيف التحليل المختار
# =========================================================
def save_selected_analysis_to_temp(selected_article, gemini_content):
    """
    يحفظ الخبر المختار + تحليل Gemini الكامل في ملف .txt وسيط قبل صياغة
    القالب النهائي. هذا يفصل مرحلة "القرار" عن مرحلة "الصياغة والنشر"،
    ويسهّل تتبع الأخطاء (تستطيع فتح الملف ومعرفة ماذا اختار النموذج بالضبط).
    """
    payload = {
        "selected_article": selected_article,
        "gemini_analysis": gemini_content,
    }
    with open(TEMP_ANALYSIS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return TEMP_ANALYSIS_FILE


def load_selected_analysis_from_temp():
    """يقرأ الملف الوسيط الذي حُفظ للتو ليبدأ منه مرحلة صياغة المنشور النهائي."""
    if not os.path.exists(TEMP_ANALYSIS_FILE):
        return None
    with open(TEMP_ANALYSIS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def cleanup_temp_analysis():
    """حذف الملف الوسيط بعد اكتمال النشر بنجاح، حتى لا يتراكم بين التشغيلات."""
    try:
        if os.path.exists(TEMP_ANALYSIS_FILE):
            os.remove(TEMP_ANALYSIS_FILE)
    except Exception:
        pass


# =========================================================
# 3) توليد صورة احتياطية عبر Google Imagen
# =========================================================
def generate_google_imagen(subject_prompt):
    """أولوية 2 في بروتوكول الصور: توليد جرافيك احترافي بأسلوب فني ثابت لا يمكن كسره."""
    if not GEMINI_API_KEY:
        print("⚠️ مفتاح GEMINI_API_KEY غير مضاف.")
        return None

    # الأسلوب الفني مثبت دائماً بصرف النظر عمّا يرسله النموذج، لمنع الهلاوس البصرية
    final_prompt = IMAGEN_STYLE_WRAPPER.format(subject=subject_prompt[:200])

    print("🎨 جاري توليد صورة احتياطية احترافية عبر Google Imagen...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "instances": [{"prompt": final_prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": "1:1"},
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        if res.status_code == 200:
            data = res.json()
            b64_img = data["predictions"][0]["bytesBase64Encoded"]
            return base64.b64decode(b64_img)
        else:
            print(f"❌ خطأ من Google Imagen API: {res.text}")
    except Exception as e:
        print(f"❌ استثناء أثناء توليد صورة Google: {e}")

    return None
