"""
leak_publisher.py
=========================================================
قالب نشر مختص بالتسريبات/العاجل — مختلف عمداً عن قالب النشرة اليومية:
يبدأ بشارة تحذير واضحة (🔴🟠🟡🟢) وسبب التصنيف، ثم تحذير صريح بعدم
التأكد الرسمي، قبل عرض تفاصيل الخبر نفسه.

يعيد استخدام دوال التحميل والنشر الفعلي من publisher.py (get_og_image،
publish_to_telegram) دون تعديلها — فقط قالب النص والتوقيع مختلفان.
=========================================================
"""

from utils import sanitize_field, escape_telegram_markdown
from leaks_config import (
    RELIABILITY_LEVELS,
    LEAK_HEADER,
    LEAK_SIGNATURE,
    LEAK_HASHTAGS,
    LEAK_CAPTION_HASHTAGS,
    LEAK_TELEGRAM_CHAT_ID,
)
from publisher import publish_to_telegram as _publish_to_telegram


def build_leak_post_content(reliability_level, reliability_reason, title, summary, disclaimer, source):
    """قالب التسريبات الثابت: شارة الموثوقية أولاً، ثم التحذير، ثم الخبر."""
    reliability_label = RELIABILITY_LEVELS.get(reliability_level, "غير مصنّف")

    title = escape_telegram_markdown(sanitize_field(title))
    summary = escape_telegram_markdown(sanitize_field(summary))
    reliability_reason = escape_telegram_markdown(sanitize_field(reliability_reason))
    disclaimer = escape_telegram_markdown(sanitize_field(disclaimer))

    post_content = f"""{LEAK_HEADER}

{reliability_level} مستوى الموثوقية: {reliability_label}
📝 سبب التصنيف: {reliability_reason}

🔹 {title}

{summary}

⚠️ تنويه: {disclaimer}

—
{LEAK_SIGNATURE}
🔗 المصدر الأولي: {source}
{LEAK_HASHTAGS}
"""
    return post_content


def build_leak_caption(reliability_level, title):
    """نص مختصر يُرسل مع الصورة (تحت 1024 حرف) — شارة الموثوقية + العنوان فقط."""
    safe_title = escape_telegram_markdown(sanitize_field(title))
    return f"{reliability_level} 🚨 **{safe_title}**\n\n{LEAK_CAPTION_HASHTAGS}"


def publish_leak_to_telegram(reliability_level, title, post_content, image_url, image_bytes):
    """
    يستخدم نفس آلية publisher.publish_to_telegram (تحميل الصورة محلياً، ثم
    الرسالة النصية الكاملة) لكن مع كابشن مخصص يحمل شارة الموثوقية،
    وينشر إلى LEAK_TELEGRAM_CHAT_ID (يساوي القناة الرسمية افتراضياً).
    """
    caption_title = f"{reliability_level} {title}"
    return _publish_to_telegram(
        title=caption_title,
        post_content=post_content,
        image_url=image_url,
        image_bytes=image_bytes,
        chat_id=LEAK_TELEGRAM_CHAT_ID,
    )
