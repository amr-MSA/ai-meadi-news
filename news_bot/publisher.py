"""
publisher.py
=========================================================
كل ما يخص:
1) بروتوكول الصور: جلب صورة المقال الحقيقية (og:image) والتحقق من أبعادها.
   (توليد الصورة الاحتياطية عبر Google Imagen موجود في ai_handler.py
   لأنه استدعاء لنموذج ذكاء اصطناعي — هنا فقط نستهلك نتيجته).
2) صياغة القالب النهائي الثابت للمنشور.
3) التواصل الفعلي مع بوت تيليجرام: تحميل الصور محلياً لتفادي حظر الروابط،
   إرسال الصورة + العنوان، ثم التقرير الكامل، ثم الرد ببطاقة الشركة.
=========================================================
"""

import requests
from bs4 import BeautifulSoup

try:
    from PIL import Image
    from io import BytesIO
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    BAD_IMAGE_HINTS,
    MIN_IMAGE_DIMENSION,
    CHANNEL_SIGNATURE,
    CHANNEL_HASHTAGS,
    CAPTION_HASHTAGS,
    TELEGRAM_CAPTION_HARD_LIMIT,
    TELEGRAM_SHORT_POST_THRESHOLD,
)
from utils import sanitize_field, escape_telegram_markdown


# =========================================================
# 1) بروتوكول الصور (أولوية 1: صورة المقال الحقيقية)
# =========================================================
def _looks_like_icon(url):
    lowered = url.lower()
    return any(hint in lowered for hint in BAD_IMAGE_HINTS)


def _validate_image_dimensions(img_url):
    """التحقق أن الصورة ليست أيقونة صغيرة عبر أبعادها الفعلية (إن توفرت مكتبة Pillow)."""
    if not PIL_AVAILABLE:
        return True  # لا نمنع النشر إن كانت المكتبة غير متوفرة، فقط نتجاوز هذا الفحص
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(img_url, headers=headers, timeout=6)
        img = Image.open(BytesIO(res.content))
        w, h = img.size
        return w >= MIN_IMAGE_DIMENSION and h >= MIN_IMAGE_DIMENSION
    except Exception:
        return True  # تعذر التحقق -> لا نستبعدها ظلماً، النشر يمر عبر مسار الصورة الحقيقية أصلاً


def get_og_image(article_url):
    """أولوية 1: جلب صورة المقال الحقيقية (og:image) مع استبعاد الأيقونات الصغيرة."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(article_url, headers=headers, timeout=8)
        if res.status_code != 200:
            return None

        soup = BeautifulSoup(res.text, "html.parser")
        candidates = []
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            candidates.append(og_img["content"])
        tw_img = soup.find("meta", attrs={"name": "twitter:image"})
        if tw_img and tw_img.get("content"):
            candidates.append(tw_img["content"])

        for img_url in candidates:
            if not img_url.startswith("http"):
                continue
            if img_url.lower().endswith(".ico") or _looks_like_icon(img_url):
                continue
            if _validate_image_dimensions(img_url):
                return img_url

    except Exception as e:
        print(f"لم تُوجد صورة og:image صالحة: {e}")

    return None


# =========================================================
# 2) القالب الإخباري الثابت
# =========================================================
def build_post_content(title, main_event, tech_details_list, impact, source):
    """القالب الإخباري الثابت (Hardcoded) — لا يُترك للذكاء الاصطناعي كتابته حراً."""
    title = escape_telegram_markdown(sanitize_field(title))
    main_event = escape_telegram_markdown(sanitize_field(main_event))
    impact = escape_telegram_markdown(sanitize_field(impact))
    tech_details_list = [sanitize_field(p) for p in tech_details_list if sanitize_field(p)]
    tech_details_list = [escape_telegram_markdown(p) for p in tech_details_list]
    tech_details = "\n• ".join(tech_details_list) if tech_details_list else "لا توجد تفاصيل إضافية."

    post_content = f"""{title}

🔹 الحدث الرئيسي:
{main_event}

🔹 التفاصيل والأرقام التقنية:
• {tech_details}

🔹 الأثر والأهمية:
{impact}

—
{CHANNEL_SIGNATURE}
🔗 المصدر: {source}
{CHANNEL_HASHTAGS}
"""
    return post_content


# =========================================================
# 3) النشر على تيليجرام (مع التحميل المحلي للبايتس لتفادي حظر الروابط)
# =========================================================
def publish_to_telegram(title, post_content, image_url, image_bytes, chat_id=None):
    """
    chat_id: اختياري — عند تركه فارغاً يُستخدم TELEGRAM_CHAT_ID الافتراضي (خط النشرة اليومية).
    خط التسريبات (leak_publisher.py) يمرر LEAK_TELEGRAM_CHAT_ID هنا إن رغب المستخدم
    مستقبلاً بفصل قناة التسريبات عن قناة النشرة الرسمية، دون أي تعديل إضافي هنا.
    """
    target_chat_id = chat_id or TELEGRAM_CHAT_ID
    photo_data = None

    if image_url:
        try:
            print("📥 جاري تحميل صورة المقال محلياً عبر السيرفر...")
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            img_res = requests.get(image_url, headers=headers, timeout=12)
            if img_res.status_code == 200:
                photo_data = img_res.content
                print("✅ تم تحميل الصورة بنجاح.")
        except Exception as e:
            print(f"⚠️ استثناء أثناء تحميل الصورة: {e}")

    if not photo_data and image_bytes:
        print("🎨 استخدام الصورة المُولدة عبر Google Imagen...")
        photo_data = image_bytes

    # اختبار طول المنشور الكامل (مع الفوتر) لتحديد استراتيجية النشر:
    # - قصير (<= الحد الآمن): كابشن واحد يحوي المنشور كاملاً مع الصورة، برسالة واحدة فقط.
    # - طويل: صورة + عنوان مختصر فقط كابشن، ثم التقرير الكامل كرسالة نصية منفصلة تالية.
    is_short_post = len(post_content) <= TELEGRAM_SHORT_POST_THRESHOLD

    if is_short_post:
        caption_text = post_content
    else:
        caption_text = f"🚨 **{escape_telegram_markdown(title)}**\n\n{CAPTION_HASHTAGS}"

    if photo_data:
        try:
            if is_short_post:
                print(f"📸 المنشور قصير ({len(post_content)} حرف) — نشر الصورة والمنشور كاملاً برسالة واحدة...")
            else:
                print(f"📸 المنشور طويل ({len(post_content)} حرف) — نشر الصورة مع العنوان فقط، ثم التقرير لاحقاً...")

            tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            res = requests.post(
                tg_url,
                data={
                    "chat_id": target_chat_id,
                    "caption": caption_text[:TELEGRAM_CAPTION_HARD_LIMIT],
                    "parse_mode": "Markdown",
                },
                files={"photo": ("image.jpg", photo_data, "image/jpeg")},
                timeout=30,
            )
            if res.status_code == 200:
                if not is_short_post:
                    # المنشور طويل: نرسل التقرير المفصل الكامل كرسالة نصية مستقلة (تستوعب حتى 4096 حرف)
                    print("📤 جاري إرسال التقرير التقني المفصل برسالة نصية تالية...")
                    msg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                    requests.post(
                        msg_url,
                        data={
                            "chat_id": target_chat_id,
                            "text": post_content,
                            "parse_mode": "Markdown",
                            "disable_web_page_preview": True,
                        },
                        timeout=30,
                    )
                return res
            else:
                print(f"⚠️ رفض تيليجرام إرسال الصورة: {res.text}")
        except Exception as e:
            print(f"⚠️ خطأ أثناء إرسال الصورة: {e}")

    # الملاذ الأخير: إرسال المنشور كاملاً كنص منسق في حال تعذر إرسال الصورة
    print("📄 النشر كنص كامل منسق (بدون صورة)...")
    tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        res = requests.post(
            tg_url,
            data={
                "chat_id": target_chat_id,
                "text": post_content,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        if res.status_code != 200:
            print(f"⚠️ رفض تيليجرام إرسال النص أيضاً: {res.text}")
        return res
    except Exception as e:
        print(f"⚠️ استثناء أثناء إرسال النص: {e}")
        return None


# =========================================================
# 4) الرد ببطاقة تعريف الشركة (إن وُجدت) على نفس المنشور
# =========================================================
def send_company_profile_reply(message_id, company_profile, chat_id=None):
    if not company_profile or str(company_profile).strip().lower() == "null":
        return None
    target_chat_id = chat_id or TELEGRAM_CHAT_ID
    reply_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        return requests.post(
            reply_url,
            data={
                "chat_id": target_chat_id,
                "text": f"🏢 **بطاقة تعريف بالشركة المذكورة:**\n\n{escape_telegram_markdown(sanitize_field(str(company_profile)))}",
                "reply_to_message_id": message_id,
                "parse_mode": "Markdown",
            },
            timeout=30,
        )
    except Exception as e:
        print(f"⚠️ تعذر إرسال بطاقة الشركة: {e}")
        return None
