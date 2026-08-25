"""اكتشاف صور الأخبار، بناء القوالب، والنشر على Telegram."""

from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    from io import BytesIO
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from config import (
    BAD_IMAGE_HINTS,
    CAPTION_HASHTAGS,
    CHANNEL_HASHTAGS,
    CHANNEL_SIGNATURE,
    MIN_IMAGE_DIMENSION,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CAPTION_HARD_LIMIT,
    TELEGRAM_CHAT_ID,
    TELEGRAM_SHORT_POST_THRESHOLD,
    TELEGRAM_TEXT_HARD_LIMIT,
)
from leaks_config import (
    LEAK_IMAGE_ASPECT_RATIO_MAX,
    LEAK_IMAGE_ASPECT_RATIO_MIN,
    LEAK_IMAGE_MAX_BYTES,
    LEAK_IMAGE_MIN_BYTES,
    LEAK_IMAGE_MIN_HEIGHT,
    LEAK_IMAGE_MIN_WIDTH,
)
from utils import escape_telegram_markdown, sanitize_field

REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ai-meadi-news/1.0)"}


def _looks_like_icon(url):
    lowered = url.lower()
    return any(hint in lowered for hint in BAD_IMAGE_HINTS)


def _validate_image_dimensions(image_url):
    if not PIL_AVAILABLE:
        return True
    try:
        response = requests.get(image_url, headers=REQUEST_HEADERS, timeout=6)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content))
        return image.size[0] >= MIN_IMAGE_DIMENSION and image.size[1] >= MIN_IMAGE_DIMENSION
    except Exception:
        return True


def get_og_image(article_url):
    try:
        response = requests.get(article_url, headers=REQUEST_HEADERS, timeout=8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        candidates = []
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            candidates.append(og_image["content"])
        twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
        if twitter_image and twitter_image.get("content"):
            candidates.append(twitter_image["content"])
        for image_url in candidates:
            image_url = urljoin(article_url, image_url)
            if not image_url.startswith(("http://", "https://")):
                continue
            if image_url.lower().endswith(".ico") or _looks_like_icon(image_url):
                continue
            if _validate_image_dimensions(image_url):
                return image_url
    except Exception as exc:
        print(f"لم تُوجد صورة og:image صالحة: {exc}")
    return None


def get_leak_og_image(article_url):
    """يعيد صورة مصدر صالحة فقط بعد تحقق صارم؛ لا يقبل صورة عامة أو غير قابلة للتحقق."""
    try:
        response = requests.get(article_url, headers=REQUEST_HEADERS, timeout=8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        candidates = []
        for selector in [
            soup.find("meta", property="og:image"),
            soup.find("meta", attrs={"name": "twitter:image"}),
        ]:
            if selector and selector.get("content"):
                candidates.append(urljoin(article_url, selector["content"]))
        for image_url in candidates:
            if not image_url.startswith(("http://", "https://")) or _looks_like_icon(image_url):
                continue
            image_response = requests.get(image_url, headers=REQUEST_HEADERS, timeout=10)
            image_response.raise_for_status()
            content = image_response.content
            if not LEAK_IMAGE_MIN_BYTES <= len(content) <= LEAK_IMAGE_MAX_BYTES:
                continue
            if not PIL_AVAILABLE:
                continue
            with Image.open(BytesIO(content)) as image:
                image.verify()
            with Image.open(BytesIO(content)) as image:
                width, height = image.size
            ratio = width / height if height else 0
            if (
                width >= LEAK_IMAGE_MIN_WIDTH
                and height >= LEAK_IMAGE_MIN_HEIGHT
                and LEAK_IMAGE_ASPECT_RATIO_MIN <= ratio <= LEAK_IMAGE_ASPECT_RATIO_MAX
            ):
                return image_url
    except Exception as exc:
        print(f"⚠️ لم تجتز صورة التسريب تحقق المصدر: {exc}")
    return None


def build_post_content(
    title, main_event, tech_details_list, impact, source, source_link=None,
    is_update=False, update_summary=""
):
    update_banner = ""
    if is_update:
        update_text = sanitize_field(update_summary) or "معلومة جوهرية جديدة حول حدث سابق."
        update_banner = f"🔄 **تحديث جوهري:** {escape_telegram_markdown(update_text)}\n\n"
    title = escape_telegram_markdown(sanitize_field(title))
    main_event = escape_telegram_markdown(sanitize_field(main_event))
    impact = escape_telegram_markdown(sanitize_field(impact))
    details = []
    if isinstance(tech_details_list, (list, tuple)):
        for detail in tech_details_list:
            clean_detail = sanitize_field(detail)
            if clean_detail:
                details.append(escape_telegram_markdown(clean_detail))
    details_text = "\n• ".join(details) if details else "لا توجد تفاصيل إضافية."
    source_name = escape_telegram_markdown(sanitize_field(source))
    source_url = str(source_link or "").strip()
    source_footer = f"{source_name}\n🌐 الرابط: {source_url}" if source_url else source_name
    return f"""{update_banner}{title}

🔹 الحدث الرئيسي:
{main_event}

🔹 التفاصيل والأرقام التقنية:
• {details_text}

🔹 الأثر والأهمية:
{impact}

—
{CHANNEL_SIGNATURE}
🔗 المصدر: {source_footer}
{CHANNEL_HASHTAGS}
"""


def _split_text(text, limit=TELEGRAM_TEXT_HARD_LIMIT):
    text = str(text or "")
    chunks = []
    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit + 1)
        if split_at < max(1, limit // 2):
            split_at = limit
        if split_at < len(text) and text[split_at] == "\n":
            chunks.append(text[:split_at].rstrip())
            text = text[split_at:].lstrip("\n")
        else:
            chunks.append(text[:split_at])
            text = text[split_at:]
    if text or not chunks:
        chunks.append(text)
    return chunks


def build_telegram_message_url(message_id, chat_id=None):
    if not message_id:
        return None
    target = str(chat_id or TELEGRAM_CHAT_ID or "").strip()
    if target.startswith("@"):
        return f"https://t.me/{target[1:]}/{message_id}"
    if target.startswith("-100"):
        return f"https://t.me/c/{target[4:]}/{message_id}"
    return None


def _post_text_messages(target_chat_id, text, limit=TELEGRAM_TEXT_HARD_LIMIT, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    last_response = None
    for chunk in _split_text(text, limit=limit):
        data = {"chat_id": target_chat_id, "text": chunk, "disable_web_page_preview": True}
        if parse_mode:
            data["parse_mode"] = parse_mode
        last_response = requests.post(url, data=data, timeout=30)
        if last_response.status_code != 200:
            print(f"⚠️ رفض تيليجرام النص: {last_response.text}")
            return last_response
    return last_response


def publish_text_to_telegram(text, chat_id=None):
    try:
        return _post_text_messages(chat_id or TELEGRAM_CHAT_ID, text, parse_mode=None)
    except Exception as exc:
        print(f"⚠️ استثناء أثناء إرسال النص: {exc}")
        return None


def publish_to_telegram(title, post_content, image_url, image_bytes, chat_id=None):
    target_chat_id = chat_id or TELEGRAM_CHAT_ID
    photo_data = None
    if image_url:
        try:
            response = requests.get(image_url, headers=REQUEST_HEADERS, timeout=12)
            response.raise_for_status()
            if response.content:
                photo_data = response.content
        except Exception as exc:
            print(f"⚠️ تعذر تحميل الصورة الحقيقية: {exc}")
    if not photo_data and image_bytes:
        photo_data = image_bytes

    is_short = len(post_content) <= TELEGRAM_SHORT_POST_THRESHOLD
    caption = post_content if is_short else f"🚨 **{escape_telegram_markdown(title)}**\n\n{CAPTION_HASHTAGS}"
    caption = caption[:TELEGRAM_CAPTION_HARD_LIMIT]
    if photo_data:
        try:
            photo_response = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                data={"chat_id": target_chat_id, "caption": caption, "parse_mode": "Markdown"},
                files={"photo": ("image.jpg", photo_data, "image/jpeg")},
                timeout=30,
            )
            if photo_response.status_code == 200:
                if not is_short:
                    details_response = _post_text_messages(target_chat_id, post_content)
                    if details_response is None or details_response.status_code != 200:
                        return details_response
                return photo_response
            print(f"⚠️ رفض تيليجرام إرسال الصورة: {photo_response.text}")
        except Exception as exc:
            print(f"⚠️ خطأ أثناء إرسال الصورة: {exc}")
    try:
        return _post_text_messages(target_chat_id, post_content)
    except Exception as exc:
        print(f"⚠️ استثناء أثناء إرسال النص: {exc}")
        return None


def send_company_profile_reply(message_id, company_profile, chat_id=None):
    if not company_profile or str(company_profile).strip().lower() == "null":
        return None
    try:
        return requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={
                "chat_id": chat_id or TELEGRAM_CHAT_ID,
                "text": f"🏢 **بطاقة تعريف بالشركة المذكورة:**\n\n{escape_telegram_markdown(sanitize_field(company_profile))}",
                "reply_to_message_id": message_id,
                "parse_mode": "Markdown",
            },
            timeout=30,
        )
    except Exception as exc:
        print(f"⚠️ تعذر إرسال بطاقة الشركة: {exc}")
        return None
