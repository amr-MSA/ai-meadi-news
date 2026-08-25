"""مصدر الحقيقة المركزي لإعدادات نظام الأخبار."""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

REQUIRED_ENV_VARS = {
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
}

HISTORY_FILE = os.path.join(BASE_DIR, "posted_history.json")
LOCK_FILE = os.path.join(BASE_DIR, "bot.lock")
RSS_REQUEST_TIMEOUT_SECONDS = 15
LOCK_MAX_AGE_SECONDS = 15 * 60
TEMP_ANALYSIS_FILE = os.path.join(BASE_DIR, "temp_selected_analysis.json")

HISTORY_CONTEXT_WINDOW_DAYS = 60
NEWS_MAX_AGE_DAYS = 7
HISTORY_RETENTION_DAYS = 7

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

ARTICLES_POOL_MIN = 10
ARTICLES_POOL_MAX = 15
SELECTION_MAX_ATTEMPTS = 2
TITLE_SIMILARITY_THRESHOLD = 0.80
TOPIC_SIMILARITY_THRESHOLD = 0.72

FORBIDDEN_PATTERNS = [
    r"شارك[وا]?نا\s*رأي\w*",
    r"ما\s*رأيكم",
    r"شاركونا\s*بتعليق\w*",
    r"أخبرونا\s*في\s*التعليقات",
    r"إيش\s*رأيكم",
    r"وش\s*رأيكم",
    r"شو\s*رأيكم",
    r"\?\s*$",
]

RSS_SOURCES = [
    {"name": "BleepingComputer", "url": "https://www.bleepingcomputer.com/feed/"},
    {"name": "Hacker News", "url": "https://news.ycombinator.com/rss"},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
]

BAD_IMAGE_HINTS = ["logo", "icon", "favicon", "sprite", "avatar", "placeholder", "default-image"]
MIN_IMAGE_DIMENSION = 250
IMAGEN_STYLE_WRAPPER = (
    "Minimalist flat vector tech illustration, clean geometric shapes, "
    "professional editorial style, dark blue color palette (#0a1128, #1b263b, #00b4d8 accents), "
    "no text, no watermark, no logos, high contrast, subject: {subject}"
)

GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_DELAY_SECONDS = 5
REQUIRED_GEMINI_FIELDS = [
    "selected_id",
    "topic_key",
    "image_prompt",
    "title",
    "main_event_summary",
    "technical_details_points",
    "impact_analysis",
    "classification",
    "important_unselected_ids",
    "candidate_classifications",
]

TELEGRAM_CAPTION_HARD_LIMIT = 1024
TELEGRAM_TEXT_HARD_LIMIT = 4096
TELEGRAM_SHORT_POST_THRESHOLD = 1000
TELEGRAM_WEEKLY_SUMMARY_PREFIX = "📊 ملخص أهم أخبار الأسبوع"
WEEKLY_SUMMARY_MAX_ITEMS = 12
WEEKLY_SUMMARY_MAX_CHARACTERS = 7900
WEEKLY_SUMMARY_MAX_CHUNK_CHARACTERS = 3900

CHANNEL_SIGNATURE = "✍️ إعداد: Eng. Limitless"
CHANNEL_HASHTAGS = "#تقنية #حاسوب #EngLimitless"
CAPTION_HASHTAGS = "#تقنية #EngLimitless"
