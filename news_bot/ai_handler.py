"""تكامل Gemini/Imagen وخط التحليل الوسيط."""

import base64
import json
import os
import tempfile
import time

import requests
from google import genai
from google.genai import types

from utils import sanitize_field

_last_gemini_request_at = None


def _wait_for_gemini_request():
    """يفرض فاصلًا أدنى بين جميع طلبات Gemini وImagen في العملية الحالية."""
    global _last_gemini_request_at
    now = time.monotonic()
    if _last_gemini_request_at is None:
        wait_seconds = GEMINI_INITIAL_REQUEST_DELAY_SECONDS
    else:
        elapsed = now - _last_gemini_request_at
        wait_seconds = max(0, GEMINI_MIN_REQUEST_INTERVAL_SECONDS - elapsed)
    if wait_seconds > 0:
        print(f"⏳ انتظار {wait_seconds:.1f} ثانية قبل طلب Google التالي.")
        time.sleep(wait_seconds)
    _last_gemini_request_at = time.monotonic()


# تُستخدم الاختبارات فقط لإعادة حالة محدد المعدل دون انتظار فعلي بين الحالات.
def _reset_request_limiter_for_tests():
    global _last_gemini_request_at
    _last_gemini_request_at = None


from config import (
    GEMINI_API_KEY,
    GEMINI_INITIAL_REQUEST_DELAY_SECONDS,
    GEMINI_MAX_RETRIES,
    GEMINI_MIN_REQUEST_INTERVAL_SECONDS,
    GEMINI_MODEL,
    GEMINI_RETRY_DELAY_SECONDS,
    IMAGEN_STYLE_WRAPPER,
    REQUIRED_GEMINI_FIELDS,
    TEMP_ANALYSIS_FILE,
)


def _generate_json_with_retries(prompt):
    if not GEMINI_API_KEY:
        print("❌ مفتاح GEMINI_API_KEY غير مضاف.")
        return None
    client = genai.Client(api_key=GEMINI_API_KEY)
    for attempt in range(GEMINI_MAX_RETRIES):
        try:
            _wait_for_gemini_request()
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", temperature=0.2
                ),
            )
            raw_text = (getattr(response, "text", "") or "").strip()
            if not raw_text:
                raise ValueError("أعاد Gemini استجابة فارغة")
            parsed = json.loads(raw_text)
            if not isinstance(parsed, dict):
                raise ValueError("استجابة Gemini ليست كائن JSON")
            return parsed
        except Exception as exc:
            print(f"⚠️ محاولة Gemini رقم {attempt + 1} فشلت: {exc}")
            if attempt < GEMINI_MAX_RETRIES - 1:
                time.sleep(GEMINI_RETRY_DELAY_SECONDS * (2 ** attempt))
            else:
                print("❌ استنفدت محاولات الاتصال بـ Gemini.")
    return None


def call_gemini_for_selection(articles_pool, history_context):
    if not GEMINI_API_KEY:
        print("❌ مفتاح GEMINI_API_KEY غير مضاف.")
        return None
    news_text = ""
    for index, item in enumerate(articles_pool, 1):
        news_text += (
            f"ID: {index} | Source: {item['source_name']}\n"
            f"Title: {item['title']}\nSummary: {item['summary']}\nLink: {item['link']}\n---\n"
        )
    history_text = json.dumps(history_context, ensure_ascii=False, indent=2) if history_context else "[]"
    system_prompt = f"""
أنت محلل تقني محترف لقناة Eng. Limitless. افحص سجل الأخبار المنشورة خلال آخر شهرين
وامنع اختيار أي خبر يغطي نفس الحدث أو الموضوع الجوهري، حتى لو اختلفت الصياغة.

السجل:
{history_text}

القواعد:
1) اختر خبرًا واحدًا فقط غير مكرر.
2) topic_key بالإنجليزية، وimage_prompt وصف بصري محايد بالإنجليزية.
3) اكتب بالعربية الفصحى المباشرة دون مقدمات تسويقية أو أسئلة تفاعلية.
4) قارن كل مرشح بالسجل. أعد selection_decision بقيمة واحدة فقط: "new" إذا كان حدثًا جديدًا،
   "duplicate" إذا كان نفس الحدث دون معلومة جوهرية جديدة، أو "update" إذا كان نفس الحدث
   لكن المصدر يضيف معلومة جوهرية فعلية. لا تسمح بالتحديث إذا كانت new_facts فارغة.
5) عند update، أعد related_history_index (رقم عنصر السجل، أو 0 إن لم يوجد)، وnew_facts
   بقائمة من 1 إلى 3 حقائق جديدة محددة، وupdate_summary في جملة قصيرة. عند new/duplicate اجعلها فارغة.
6) صنف الخبر المختار، واذكر أرقام الأخبار المهمة التي لم تخترها في important_unselected_ids.
7) أعد candidate_classifications لتلك الأخبار فقط، مع سبب مختصر لأهميتها.
8) لا تخترع معلومات غير موجودة في بيانات الأخبار، ولا تعتبر اختلاف المصدر وحده معلومة جديدة.

أعد كائن JSON فقط:
{{
  "selected_id": 1,
  "selection_decision": "new",
  "related_history_index": 0,
  "new_facts": [],
  "update_summary": "",
  "topic_key": "topic-name",
  "image_prompt": "Neutral visual description of the subject only",
  "title": "العنوان الرئيسي المباشر للخبر",
  "main_event_summary": "شرح مباشر للحدث",
  "technical_details_points": ["تفصيل تقني"],
  "impact_analysis": "الأثر المباشر",
  "company_profile": null,
  "classification": {{
    "company_name": "اسم الشركة أو غير محدد",
    "event_year_month": "YYYY-MM أو غير محدد",
    "news_type": "تصنيف مغلق أو أخرى",
    "product_name": "اسم المنتج أو غير محدد",
    "region": "المنطقة أو غير محدد",
    "topic_key": "topic-name",
    "keywords": ["keyword"]
  }},
  "important_unselected_ids": [],
  "candidate_classifications": []
}}

الأخبار الحالية:
{news_text}
"""
    content = _generate_json_with_retries(system_prompt)
    if not content:
        return None
    missing = [field for field in REQUIRED_GEMINI_FIELDS if field not in content]
    if missing:
        print(f"❌ رد Gemini ناقص الحقول المطلوبة: {missing}")
        return None
    return content


def save_selected_analysis_to_temp(selected_article, gemini_content):
    payload = {"selected_article": selected_article, "gemini_analysis": gemini_content}
    directory = os.path.dirname(TEMP_ANALYSIS_FILE) or "."
    fd, temp_path = tempfile.mkstemp(prefix=".selected_analysis.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, TEMP_ANALYSIS_FILE)
    except Exception:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise
    return TEMP_ANALYSIS_FILE


def load_selected_analysis_from_temp():
    if not os.path.exists(TEMP_ANALYSIS_FILE):
        return None
    try:
        with open(TEMP_ANALYSIS_FILE, "r", encoding="utf-8") as file:
            payload = json.load(file)
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("selected_article"), dict)
            or not isinstance(payload.get("gemini_analysis"), dict)
        ):
            raise ValueError("بنية الملف الوسيط غير صالحة")
        return payload
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"❌ تعذر قراءة التحليل الوسيط: {exc}")
        return None


def cleanup_temp_analysis():
    try:
        if os.path.exists(TEMP_ANALYSIS_FILE):
            os.remove(TEMP_ANALYSIS_FILE)
    except OSError:
        pass


def build_leak_image_prompt(subject_prompt):
    """قالب صارم لصورة توضيحية لا يمكن فهمها كدليل على التسريب."""
    subject = sanitize_field(subject_prompt)[:180] or "an abstract technology security event"
    return f"""Create a square editorial illustration for a technology news post.
Subject: {subject}
Purpose: neutral visual accompaniment for an unverified allegation, never evidence.
Composition: one clear symbolic subject, centered, uncluttered background, strong silhouette,
professional editorial technology style, dark navy and cyan palette, 1:1 composition.
Visual language: abstract conceptual illustration, non-photorealistic, no realistic people.
Hard constraints: no readable text, no letters, no numbers, no logos, no brand marks, no trademarks,
no product interfaces, no dashboards, no source code, no terminal, no hacking screen, no screenshots,
no chat posts, no social media interface, no documents, no newspaper clipping, no leaked files,
no credentials, no personal data, no flags, no watermark, no claims of confirmation, no visual proof.
The result must look like an editorial illustration only and must not imply that the allegation is verified."""


def generate_google_imagen(subject_prompt, image_kind="news"):
    if not GEMINI_API_KEY:
        return None
    if image_kind == "leak_illustration":
        final_prompt = build_leak_image_prompt(subject_prompt)
    else:
        final_prompt = IMAGEN_STYLE_WRAPPER.format(subject=str(subject_prompt)[:200])
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={GEMINI_API_KEY}"
    try:
        _wait_for_gemini_request()
        response = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "instances": [{"prompt": final_prompt}],
                "parameters": {"sampleCount": 1, "aspectRatio": "1:1"},
            },
            timeout=30,
        )
        if response.status_code == 200:
            encoded = response.json()["predictions"][0]["bytesBase64Encoded"]
            return base64.b64decode(encoded)
        print(f"❌ خطأ من Google Imagen API: {response.text}")
    except Exception as exc:
        print(f"❌ استثناء أثناء توليد صورة Google: {exc}")
    return None
