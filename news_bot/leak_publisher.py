"""قالب ونشر التسريبات بصياغة مختصرة وواضحة."""

import re

from leaks_config import (
    DISCLAIMER_MAX_CHARACTERS,
    FIXED_LEAK_DISCLAIMER,
    LEAK_CAPTION_HASHTAGS,
    LEAK_HASHTAGS,
    LEAK_HEADER,
    LEAK_SIGNATURE,
    LEAK_TELEGRAM_CHAT_ID,
    LEAK_SUMMARY_MAX_CHARACTERS,
    LEAK_TITLE_MAX_CHARACTERS,
    RELIABILITY_REASON_MAX_CHARACTERS,
)
from publisher import build_markdown_source_link, publish_to_telegram as _publish_to_telegram
from utils import escape_telegram_markdown, sanitize_field

SHORT_RELIABILITY_LABELS = {
    "🔴": "منخفض جدًا",
    "🟠": "ضعيف",
    "🟡": "متوسط",
    "🟢": "مرتفع نسبيًا",
}


def _compact_text(value, limit, fallback):
    text = sanitize_field(value) or fallback
    text = re.sub(
        r"^(?:(?:تنويه|تنبيه|تحذير|ملاحظة)\s*:\s*)+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", text).strip()[:limit].rstrip(" ،؛:")


def build_leak_post_content(
    reliability_level, reliability_reason, title, summary, disclaimer, source,
    source_link=None, image_note=None
):
    reason = _compact_text(
        reliability_reason,
        RELIABILITY_REASON_MAX_CHARACTERS,
        "مصدر غير رسمي دون تأكيد مستقل.",
    )
    short_disclaimer = _compact_text(
        FIXED_LEAK_DISCLAIMER,
        DISCLAIMER_MAX_CHARACTERS,
        FIXED_LEAK_DISCLAIMER,
    )
    safe_title = escape_telegram_markdown(
        _compact_text(title, LEAK_TITLE_MAX_CHARACTERS, "تسريب تقني")
    )
    safe_summary = escape_telegram_markdown(
        _compact_text(summary, LEAK_SUMMARY_MAX_CHARACTERS, "لا تتوفر تفاصيل إضافية.")
    )
    safe_reason = escape_telegram_markdown(reason)
    safe_disclaimer = escape_telegram_markdown(short_disclaimer)
    safe_image_note = escape_telegram_markdown(
        _compact_text(image_note, 150, "")
    ) if image_note else ""
    source_name = escape_telegram_markdown(sanitize_field(source))
    source_link_markdown = build_markdown_source_link(source_link)
    source_footer = (
        f"{source_name}\n🔗 {source_link_markdown}"
        if source_link_markdown else source_name
    )
    reliability_label = SHORT_RELIABILITY_LABELS.get(reliability_level, "غير مصنف")

    return f"""{LEAK_HEADER}

{reliability_level} الموثوقية: {reliability_label}
📝 التبرير: {safe_reason}

🔹 {safe_title}

{safe_summary}

⚠️ {safe_disclaimer}
{f'🏷️ **توضيح الصورة:** {safe_image_note}' if safe_image_note else ''}

—
{LEAK_SIGNATURE}
🔗 المصدر الأولي: {source_footer}
{LEAK_HASHTAGS}
"""


def build_leak_caption(reliability_level, title):
    safe_title = escape_telegram_markdown(sanitize_field(title))
    return f"{reliability_level} 🚨 **{safe_title}**\n\n{LEAK_CAPTION_HASHTAGS}"


def publish_leak_to_telegram(reliability_level, title, post_content, image_url, image_bytes):
    return _publish_to_telegram(
        title=f"{reliability_level} {title}",
        post_content=post_content,
        image_url=image_url,
        image_bytes=image_bytes,
        chat_id=LEAK_TELEGRAM_CHAT_ID,
    )
