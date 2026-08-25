"""تكامل Gemini/Imagen وخط التحليل الوسيط."""

import base64
import json
import os
import tempfile
import time

import requests
from google import genai
from google.genai import types

from config import (
    GEMINI_API_KEY,
    GEMINI_MAX_RETRIES,
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
4) صنف الخبر المختار، واذكر أرقام الأخبار المهمة التي لم تخترها في important_unselected_ids.
5) أعد candidate_classifications لتلك الأخبار فقط، مع سبب مختصر لأهميتها.
6) لا تخترع معلومات غير موجودة في بيانات الأخبار.

أعد كائن JSON فقط:
{{
  "selected_id": 1,
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


def generate_google_imagen(subject_prompt):
    if not GEMINI_API_KEY:
        return None
    final_prompt = IMAGEN_STYLE_WRAPPER.format(subject=str(subject_prompt)[:200])
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={GEMINI_API_KEY}"
    try:
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
