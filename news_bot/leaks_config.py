"""إعدادات خاصة بخط رصد التسريبات والأخبار العاجلة."""

import os

from config import GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

LEAK_TELEGRAM_CHAT_ID = os.environ.get("LEAK_TELEGRAM_CHAT_ID") or TELEGRAM_CHAT_ID

REQUIRED_LEAK_ENV_VARS = {
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "LEAK_TELEGRAM_CHAT_ID": LEAK_TELEGRAM_CHAT_ID,
}

LEAK_SOURCES = [
    {"name": "Techmeme (مجمّع أخبار سريع)", "url": "https://www.techmeme.com/feed.xml"},
    {"name": "Hacker News - بحث leak/breach", "url": "https://hnrss.org/newest?q=leak+OR+breach+OR+source+code"},
    {"name": "r/LocalLLaMA (شائعات نماذج AI)", "url": "https://www.reddit.com/r/LocalLLaMA/.rss"},
    {"name": "r/singularity (شائعات تقنية عامة)", "url": "https://www.reddit.com/r/singularity/.rss"},
    {"name": "r/artificial", "url": "https://www.reddit.com/r/artificial/.rss"},
    {"name": "DataBreaches.net (تسريبات واختراقات)", "url": "https://databreaches.net/feed/"},
    {"name": "GitHub Trending (نشاط كود مفاجئ)", "url": "https://mshibanami.github.io/GitHubTrendingRSS/daily/all.xml"},
]

LEAK_ITEMS_PER_SOURCE = 2

RELIABILITY_LEVELS = {
    "🔴": "غير مؤكد إطلاقاً — مصدر واحد غامض أو حساب مجهول، بلا أي قرينة داعمة، احتمال كبير أن يكون شائعة أو خطأ.",
    "🟠": "ضعيف — تسريب من منتدى/مجتمع نقاش غير رسمي، بدون تأكيد من أي طرف مطّلع أو مصدر ثانٍ.",
    "🟡": "متوسط — مصدر واحد يبدو مطّلعاً (باحث أمني معروف، موظف سابق، تسريب كود/وثيقة فعلية) لكن دون تأكيد رسمي بعد.",
    "🟢": "قوي نسبياً — تأكيد أو تلميح من مصدرين مستقلين على الأقل، أو وثيقة/كود مسرّب يمكن التحقق منه مباشرة.",
}

MIN_RELIABILITY_TO_PUBLISH = None

REQUIRED_LEAK_FIELDS = [
    "selected_id",
    "reliability_level",
    "reliability_reason",
    "topic_key",
    "title",
    "summary",
    "disclaimer",
    "image_prompt",
    "classification",
]

LEAK_HEADER = "🚨 تسريب / خبر عاجل غير مؤكد رسمياً"
LEAK_SIGNATURE = "✍️ رصد: Eng. Limitless"
LEAK_HASHTAGS = "#تسريبات #عاجل #EngLimitless"
LEAK_CAPTION_HASHTAGS = "#تسريبات #عاجل"

# حدود تحريرية للنص الظاهر للقارئ.
RELIABILITY_REASON_MAX_CHARACTERS = 140
DISCLAIMER_MAX_CHARACTERS = 120
LEAK_TITLE_MAX_CHARACTERS = 180
LEAK_SUMMARY_MAX_CHARACTERS = 700
FIXED_LEAK_DISCLAIMER = "غير مؤكد رسميًا؛ يُنشر لأهميته وسرعته فقط."
