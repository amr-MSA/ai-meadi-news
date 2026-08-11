"""
config.py
=========================================================
كل الثوابت، مفاتيح البيئة، المسارات، والإعدادات القابلة للتعديل
لنظام النشرة الإخبارية اليومية (تعمل يومياً الساعة 4 عصراً).

هذا الملف هو "مصدر الحقيقة الوحيد" للإعدادات — أي تعديل مستقبلي
على عتبات التشابه، مصادر RSS، أو حجم دفعة الأخبار يتم هنا فقط
ولا يتطلب لمس أي ملف منطقي آخر.
=========================================================
"""

import os

# =========================================================
# مفاتيح البيئة (Secrets)
# =========================================================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

REQUIRED_ENV_VARS = {
    "GROQ_API_KEY": GROQ_API_KEY,
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
}

# =========================================================
# المسارات والملفات
# =========================================================
HISTORY_FILE = "posted_history.json"
LOCK_FILE = "bot.lock"
LOCK_MAX_AGE_SECONDS = 15 * 60  # أي قفل أقدم من 15 دقيقة يُعتبر متروكاً ويُتجاهل

# ملف نصي مؤقت يُحفظ فيه تحليل/اختيار Gemini كخطوة وسيطة
# قبل الانتقال لمرحلة صياغة القالب النهائي والنشر (يُحذف تلقائياً بعد الاستخدام)
TEMP_ANALYSIS_FILE = "temp_selected_analysis.txt"

# =========================================================
# نافذة السياق التاريخي المرسلة إلى Gemini
# =========================================================
# نرسل لِلنموذج سجل آخر 60 يوماً (شهرين تقريباً) ليقارن به دلالياً
# بدل الاكتفاء بمطابقة نصية محلية فقط على مواضيع الشهر الحالي
HISTORY_CONTEXT_WINDOW_DAYS = 60

# حجم دفعة المقالات المرشحة التي تُرسل دفعة واحدة لِلنموذج ليختار منها
ARTICLES_POOL_MIN = 10
ARTICLES_POOL_MAX = 15

# عدد محاولات إعادة الاختيار في حال جاء اختيار Gemini مكرراً موضوعياً
SELECTION_MAX_ATTEMPTS = 2

# =========================================================
# عتبات التشابه لمنع التكرار (0 = مختلف تماماً / 1 = متطابق)
# =========================================================
TITLE_SIMILARITY_THRESHOLD = 0.80
TOPIC_SIMILARITY_THRESHOLD = 0.72

# =========================================================
# عبارات تفاعل "مبتذلة" ممنوعة نهائياً من نص المنشور
# =========================================================
FORBIDDEN_PATTERNS = [
    r"شارك[وا]?نا\s*رأي\w*",
    r"ما\s*رأيكم",
    r"شاركونا\s*بتعليق\w*",
    r"أخبرونا\s*في\s*التعليقات",
    r"إيش\s*رأيكم",
    r"وش\s*رأيكم",
    r"شو\s*رأيكم",
    r"\?\s*$",  # أي جملة تنتهي بعلامة استفهام تسويقية في نهاية الحقل
]

# =========================================================
# مصادر RSS الخاصة بالنشرة اليومية
# =========================================================
RSS_SOURCES = [
    {"name": "BleepingComputer", "url": "https://www.bleepingcomputer.com/feed/"},
    {"name": "Hacker News", "url": "https://news.ycombinator.com/rss"},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
]

# =========================================================
# إعدادات الصور
# =========================================================
BAD_IMAGE_HINTS = ["logo", "icon", "favicon", "sprite", "avatar", "placeholder", "default-image"]
MIN_IMAGE_DIMENSION = 250  # بكسل، لاستبعاد الأيقونات الصغيرة

# صيغة ثابتة تُغلّف أي وصف صورة قادم من الذكاء الاصطناعي لمنع الهلاوس البصرية
IMAGEN_STYLE_WRAPPER = (
    "Minimalist flat vector tech illustration, clean geometric shapes, "
    "professional editorial style, dark blue color palette (#0a1128, #1b263b, #00b4d8 accents), "
    "no text, no watermark, no logos, high contrast, subject: {subject}"
)

# =========================================================
# إعدادات نموذج Gemini
# =========================================================
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
]

# =========================================================
# هوية القناة (تظهر في القالب النهائي)
# =========================================================
TELEGRAM_CAPTION_HARD_LIMIT = 1024  # حد تيليجرام الفعلي لطول كابشن الصورة
# الحد الآمن الذي إن كان طول المنشور الكامل (مع الفوتر) أقل منه أو يساويه،
# يُنشر المنشور كاملاً كـ"كابشن" مباشرة مع الصورة برسالة واحدة فقط.
# وإلا يُنشر: صورة + عنوان مختصر، ثم التقرير الكامل كرسالة نصية منفصلة تالية.
TELEGRAM_SHORT_POST_THRESHOLD = 1000

CHANNEL_SIGNATURE = "✍️ إعداد: Eng. Limitless"
CHANNEL_HASHTAGS = "#تقنية #حاسوب #EngLimitless"
CAPTION_HASHTAGS = "#تقنية #EngLimitless"
