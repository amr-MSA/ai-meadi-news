import os
import json
import re
import time
import base64
import difflib
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime

try:
    from PIL import Image
    from io import BytesIO
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# =========================================================
# الإعدادات العامة
# =========================================================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ─── جديد: إعدادات GitHub ───
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")      # Personal Access Token
GITHUB_REPO = os.environ.get("GITHUB_REPO")        # مثال: username/repo-name
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

# ─── جديد: عتبة طول التقرير ───
REPORT_LENGTH_THRESHOLD = 1000  # إذا كان التقرير أقل من هذا، ينشر مع الصورة. إذا أكثر، منشورين.

HISTORY_FILE = "posted_history.json"
LOCK_FILE = "bot.lock"
REPORT_FILE = "report.txt"       # ملف التقرير المحلي
IMAGE_FILE = "report_image.jpg"  # ملف الصورة المحلي
LOCK_MAX_AGE_SECONDS = 15 * 60

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

IMAGEN_STYLE_WRAPPER = (
    "Minimalist flat vector tech illustration, clean geometric shapes, "
    "professional editorial style, dark blue color palette (#0a1128, #1b263b, #00b4d8 accents), "
    "no text, no watermark, no logos, high contrast, subject: {subject}"
)


# =========================================================
# 1) قفل التنفيذ
# =========================================================
def acquire_lock():
    if os.path.exists(LOCK_FILE):
        age = time.time() - os.path.getmtime(LOCK_FILE)
        if age < LOCK_MAX_AGE_SECONDS:
            print("🔒 يوجد تشغيل آخر قيد التنفيذ حالياً (Lock نشط). إنهاء آمن لمنع التكرار.")
            return False
        else:
            print("⚠️ تم العثور على قفل قديم متروك من تشغيل سابق فشل، سيتم تجاوزه.")
    try:
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        print(f"⚠️ تعذر إنشاء ملف القفل: {e}")
        return True


def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass


# =========================================================
# 2) أدوات النص والتشابه
# =========================================================
def normalize_text(text):
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def similarity(a, b):
    return difflib.SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def sanitize_field(text):
    if not text:
        return text
    cleaned = text
    for pattern in FORBIDDEN_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.MULTILINE).strip()
    return cleaned


# =========================================================
# 3) السجل التاريخي
# =========================================================
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                return data if isinstance(data, list) else []
            except Exception:
                return []
    return []


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def is_duplicate_against_history(title, link, topic_key, history):
    current_month = datetime.now().strftime("%Y-%m")
    for item in history:
        if not isinstance(item, dict):
            if item == link:
                return True, "link"
            continue

        if item.get("link") == link:
            return True, "link"

        if item.get("title") and similarity(item["title"], title) >= TITLE_SIMILARITY_THRESHOLD:
            return True, "title-similarity"

        if item.get("month") == current_month and item.get("topic_key") and topic_key:
            if similarity(item["topic_key"], topic_key) >= TOPIC_SIMILARITY_THRESHOLD:
                return True, "topic-key"

    return False, None


def dedupe_articles_pool(articles):
    unique = []
    for art in articles:
        is_dup = False
        for kept in unique:
            if similarity(art["title"], kept["title"]) >= TITLE_SIMILARITY_THRESHOLD:
                is_dup = True
                break
        if not is_dup:
            unique.append(art)
    return unique


# =========================================================
# 4) بروتوكول الصور الصارم
# =========================================================
BAD_IMAGE_HINTS = ["logo", "icon", "favicon", "sprite", "avatar", "placeholder", "default-image"]
MIN_IMAGE_DIMENSION = 250


def _looks_like_icon(url):
    lowered = url.lower()
    return any(hint in lowered for hint in BAD_IMAGE_HINTS)


def get_og_image(article_url):
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


def _validate_image_dimensions(img_url):
    if not PIL_AVAILABLE:
        return True
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(img_url, headers=headers, timeout=6)
        img = Image.open(BytesIO(res.content))
        w, h = img.size
        return w >= MIN_IMAGE_DIMENSION and h >= MIN_IMAGE_DIMENSION
    except Exception:
        return True


def generate_google_imagen(subject_prompt):
    if not GEMINI_API_KEY:
        print("⚠️ مفتاح GEMINI_API_KEY غير مضاف.")
        return None

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


# =========================================================
# 5) جلب الأخبار
# =========================================================
def fetch_news(history):
    articles = []
    for source in RSS_SOURCES:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries:
                dup, _ = is_duplicate_against_history(entry.title, entry.link, None, history)
                if not dup:
                    summary = getattr(entry, "summary", entry.title)
                    clean_summary = re.sub("<[^<]+?>", "", summary)[:300]
                    articles.append(
                        {
                            "title": entry.title,
                            "link": entry.link,
                            "summary": clean_summary,
                            "source_name": source["name"],
                        }
                    )
        except Exception as e:
            print(f"خطأ في جلب {source['name']}: {e}")

    return dedupe_articles_pool(articles)


# =========================================================
# 6) استدعاء Gemini وفرض القالب
# =========================================================
REQUIRED_FIELDS = [
    "selected_id",
    "topic_key",
    "image_prompt",
    "title",
    "main_event_summary",
    "technical_details_points",
    "impact_analysis",
]


from google import genai
from google.genai import types

def call_gemini_for_selection(articles_to_process, recent_topics):
    if not GEMINI_API_KEY:
        print("❌ مفتاح GEMINI_API_KEY غير مضاف.")
        return None

    news_text = ""
    for idx, item in enumerate(articles_to_process, 1):
        news_text += (
            f"ID: {idx} | Source: {item['source_name']}\n"
            f"Title: {item['title']}\nSummary: {item['summary']}\nLink: {item['link']}\n---\n"
        )

    system_prompt = f"""
أنت محلّل تقني محترف في قناة Eng. Limitless الموجهة لمهندسي وطلاب الحاسوب.

مواضيع تم نشرها هذا الشهر ويُمنع نهائياً اختيار أي خبر يغطي نفس الحدث، حتى لو جاء من مصدر مختلف أو بصياغة مختلفة: {recent_topics}

قواعد صارمة يجب الالتزام بها دون استثناء:
1) اختر خبراً واحداً فقط، تقنياً بحتاً، لم يُغطَّ من قبل بأي صياغة.
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

    client = genai.Client(api_key=GEMINI_API_KEY)

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=f"{system_prompt}\n\nالأخبار المتاحة:\n{news_text}",
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2
                )
            )
            content = json.loads(response.text)
            missing = [f for f in REQUIRED_FIELDS if f not in content]
            if missing:
                print(f"❌ رد Gemini ناقص الحقول المطلوبة: {missing}")
                return None
            return content
        except Exception as e:
            print(f"⚠️ محاولة {attempt+1} فشلت بسبب الضغط أو استثناء: {e}")
            if attempt < 2:
                time.sleep(5)
            else:
                print("❌ استنفدت محاولات الاتصال بـ Gemini.")
                return None
    return None


# =========================================================
# جديد: بناء التقرير الشامل (الهيدر + الفوتر + المحتوى)
# =========================================================
def build_full_report(title, main_event, tech_details_list, impact, source, company_profile=None):
    """
    يبني التقرير الشامل الذي يحتوي على الهيدر والفوتر.
    هذا هو النص الكامل الذي سيُحفظ ويُرفع إلى GitHub.
    """
    title = escape_telegram_markdown(sanitize_field(title))
    main_event = escape_telegram_markdown(sanitize_field(main_event))
    impact = escape_telegram_markdown(sanitize_field(impact))
    tech_details_list = [sanitize_field(p) for p in tech_details_list if sanitize_field(p)]
    tech_details_list = [escape_telegram_markdown(p) for p in tech_details_list]
    tech_details = "\n• ".join(tech_details_list) if tech_details_list else "لا توجد تفاصيل إضافية."

    # ─── الهيدر ───
    header = "╔══════════════════════════════════════╗\n"
    header += "║     📰  تقرير Eng. Limitless  📰     ║\n"
    header += "╚══════════════════════════════════════╝\n\n"

    # ─── المحتوى الرئيسي ───
    body = f"""🚨 {title}

🔹 الحدث الرئيسي:
{main_event}

🔹 التفاصيل والأرقام التقنية:
• {tech_details}

🔹 الأثر والأهمية:
{impact}
"""

    # ─── بطاقة الشركة (إن وجدت) ───
    company_section = ""
    if company_profile and str(company_profile).strip().lower() != "null":
        cp = escape_telegram_markdown(sanitize_field(str(company_profile)))
        company_section = f"\n\n🏢 بطاقة تعريف بالشركة المذكورة:\n{cp}\n"

    # ─── الفوتر ───
    footer = f"""\n
—
✍️ إعداد: Eng. Limitless
🔗 المصدر: {source}
📅 التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}
#تقنية #حاسوب #EngLimitless
"""

    full_report = header + body + company_section + footer
    return full_report


# =========================================================
# جديد: حفظ التقرير محلياً
# =========================================================
def save_report_locally(report_text, filename=REPORT_FILE):
    """
    يحفظ التقرير في ملف txt محلي.
    إذا وجد ملف بنفس الاسم، يحذف محتواه القديم ويكتب الجديد.
    """
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(report_text)
        print(f"💾 تم حفظ التقرير محلياً في: {filename}")
        return True
    except Exception as e:
        print(f"❌ فشل حفظ التقرير محلياً: {e}")
        return False


# =========================================================
# جديد: حفظ الصورة محلياً
# =========================================================
def save_image_locally(image_data, filename=IMAGE_FILE):
    """
    يحفظ بيانات الصورة (bytes) في ملف محلي.
    إذا وجد ملف بنفس الاسم، يستبدله.
    """
    if not image_data:
        return False
    try:
        with open(filename, "wb") as f:
            f.write(image_data)
        print(f"💾 تم حفظ الصورة محلياً في: {filename}")
        return True
    except Exception as e:
        print(f"❌ فشل حفظ الصورة محلياً: {e}")
        return False


# =========================================================
# جديد: رفع الملف إلى GitHub (إنشاء أو تعديل)
# =========================================================
def upload_to_github(filepath, repo_filename, commit_message="تحديث التقرير التقني"):
    """
    يرفع ملفاً إلى GitHub Repo.
    إذا وجد ملف بنفس الاسم، يقوم بتحديثه (حذف القديم وكتابة الجديد عبر API).
    """
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("⚠️ إعدادات GitHub غير مكتملة (GITHUB_TOKEN أو GITHUB_REPO غير موجود).")
        return False

    try:
        # قراءة محتوى الملف وتحويله إلى base64
        with open(filepath, "rb") as f:
            content_bytes = f.read()
        content_b64 = base64.b64encode(content_bytes).decode("utf-8")

        api_base = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{repo_filename}"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

        # التحقق إن كان الملف موجوداً مسبقاً (للحصول على sha)
        sha = None
        check_res = requests.get(api_base, headers=headers, params={"ref": GITHUB_BRANCH})
        if check_res.status_code == 200:
            sha = check_res.json().get("sha")
            print(f"📝 الملف موجود مسبقاً على GitHub، سيتم التعديل...")

        payload = {
            "message": commit_message,
            "content": content_b64,
            "branch": GITHUB_BRANCH
        }
        if sha:
            payload["sha"] = sha  # مطلوب للتعديل

        upload_res = requests.put(api_base, headers=headers, json=payload)

        if upload_res.status_code in [200, 201]:
            print(f"✅ تم رفع/تعديل الملف على GitHub بنجاح: {repo_filename}")
            return True
        else:
            print(f"❌ فشل رفع الملف إلى GitHub: {upload_res.status_code} - {upload_res.text}")
            return False

    except Exception as e:
        print(f"❌ استثناء أثناء رفع الملف إلى GitHub: {e}")
        return False


def escape_telegram_markdown(text):
    if not text:
        return text
    for ch in ["_", "*", "`", "["]:
        text = text.replace(ch, "\\" + ch)
    return text


# =========================================================
# 7) النشر على تيليجرام (معدل بالكامل)
# =========================================================
def publish_to_telegram(title, full_report, image_url, image_bytes):
    """
    منطق النشر الذكي:
    - إذا كان التقرير أقصر من REPORT_LENGTH_THRESHOLD: ينشر مع الصورة مباشرة.
    - إذا كان أطول: ينشر الصورة + العنوان أولاً، ثم التقرير الكامل كرسالة منفصلة.
    - في حالة فشل النشر الآلي، يحفظ الملفات محلياً للنشر اليدوي.
    """
    photo_data = None

    # ─── تحضير الصورة ───
    if image_url:
        try:
            print("📥 جاري تحميل صورة المقال محلياً...")
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

    # ─── حفظ الصورة محلياً دائماً (للنشر اليدوي عند الفشل) ───
    save_image_locally(photo_data)

    report_length = len(full_report)
    print(f"📏 طول التقرير: {report_length} حرف (العتبة: {REPORT_LENGTH_THRESHOLD})")

    # ═══════════════════════════════════════════════════════
    # الحالة أ: التقرير قصير → ينشر مع الصورة مباشرة
    # ═══════════════════════════════════════════════════════
    if report_length <= REPORT_LENGTH_THRESHOLD:
        caption = full_report[:1024]  # تيليجرام يسمح بـ 1024 كحد أقصى للكابشن

        if photo_data:
            try:
                print("📸 جاري نشر الصورة مع التقرير القصير...")
                tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
                res = requests.post(
                    tg_url,
                    data={
                        "chat_id": TELEGRAM_CHAT_ID,
                        "caption": caption,
                        "parse_mode": "Markdown",
                    },
                    files={"photo": ("image.jpg", photo_data, "image/jpeg")},
                    timeout=30
                )
                if res.status_code == 200:
                    print("✅ تم النشر بنجاح (تقرير قصير + صورة)!")
                    return res
                else:
                    print(f"⚠️ رفض تيليجرام إرسال الصورة: {res.text}")
            except Exception as e:
                print(f"⚠️ خطأ أثناء إرسال الصورة: {e}")

        # ملاذ أخير: نشر كنص فقط
        print("📄 النشر كنص كامل (بدون صورة)...")
        return _send_text_message(full_report)

    # ═══════════════════════════════════════════════════════
    # الحالة ب: التقرير طويل → منشورين (صور    return difflib.SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def sanitize_field(text):
    """إزالة أي صياغة تسويقية أو سؤال تفاعلي مبتذل قد يتسلل داخل حقول الذكاء الاصطناعي."""
    if not text:
        return text
    cleaned = text
    for pattern in FORBIDDEN_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.MULTILINE).strip()
    return cleaned


# =========================================================
# 3) السجل التاريخي
# =========================================================
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                return data if isinstance(data, list) else []
            except Exception:
                return []
    return []


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def is_duplicate_against_history(title, link, topic_key, history):
    """الفحص الثلاثي: الرابط الحرفي + العنوان الحرفي/المتشابه + المفتاح الموضوعي الشهري."""
    current_month = datetime.now().strftime("%Y-%m")
    for item in history:
        if not isinstance(item, dict):
            if item == link:
                return True, "link"
            continue

        if item.get("link") == link:
            return True, "link"

        if item.get("title") and similarity(item["title"], title) >= TITLE_SIMILARITY_THRESHOLD:
            return True, "title-similarity"

        if item.get("month") == current_month and item.get("topic_key") and topic_key:
            if similarity(item["topic_key"], topic_key) >= TOPIC_SIMILARITY_THRESHOLD:
                return True, "topic-key"

    return False, None


def dedupe_articles_pool(articles):
    """
    قبل حتى إرسال الأخبار إلى Groq: تجميع الأخبار المتشابهة القادمة من مصادر مختلفة
    (نفس الحدث بروابط وعناوين مختلفة) والاحتفاظ بنسخة واحدة فقط.
    هذا يمنع مباشرة سيناريو "نفس خبر ميتا من مصدرين مختلفين" حتى قبل وصوله للنموذج.
    """
    unique = []
    for art in articles:
        is_dup = False
        for kept in unique:
            if similarity(art["title"], kept["title"]) >= TITLE_SIMILARITY_THRESHOLD:
                is_dup = True
                break
        if not is_dup:
            unique.append(art)
    return unique


# =========================================================
# 4) بروتوكول الصور الصارم (3 أولويات)
# =========================================================
BAD_IMAGE_HINTS = ["logo", "icon", "favicon", "sprite", "avatar", "placeholder", "default-image"]
MIN_IMAGE_DIMENSION = 250  # بكسل، لاستبعاد الأيقونات الصغيرة


def _looks_like_icon(url):
    lowered = url.lower()
    return any(hint in lowered for hint in BAD_IMAGE_HINTS)


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


def generate_google_imagen(subject_prompt):
    """أولوية 2: توليد جرافيك احترافي عبر Google Imagen، بأسلوب فني ثابت لا يمكن كسره."""
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


# =========================================================
# 5) جلب الأخبار
# =========================================================
def fetch_news(history):
    articles = []
    for source in RSS_SOURCES:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries:
                dup, _ = is_duplicate_against_history(entry.title, entry.link, None, history)
                if not dup:
                    summary = getattr(entry, "summary", entry.title)
                    clean_summary = re.sub("<[^<]+?>", "", summary)[:300]
                    articles.append(
                        {
                            "title": entry.title,
                            "link": entry.link,
                            "summary": clean_summary,
                            "source_name": source["name"],
                        }
                    )
        except Exception as e:
            print(f"خطأ في جلب {source['name']}: {e}")

    return dedupe_articles_pool(articles)


# =========================================================
# 6) استدعاء Groq وفرض القالب برمجياً
# =========================================================
REQUIRED_FIELDS = [
    "selected_id",
    "topic_key",
    "image_prompt",
    "title",
    "main_event_summary",
    "technical_details_points",
    "impact_analysis",
]


from google import genai
from google.genai import types

def call_gemini_for_selection(articles_to_process, recent_topics):
    if not GEMINI_API_KEY:
        print("❌ مفتاح GEMINI_API_KEY غير مضاف.")
        return None

    news_text = ""
    for idx, item in enumerate(articles_to_process, 1):
        news_text += (
            f"ID: {idx} | Source: {item['source_name']}\n"
            f"Title: {item['title']}\nSummary: {item['summary']}\nLink: {item['link']}\n---\n"
        )

    system_prompt = f"""
أنت محلّل تقني محترف في قناة Eng. Limitless الموجهة لمهندسي وطلاب الحاسوب.

مواضيع تم نشرها هذا الشهر ويُمنع نهائياً اختيار أي خبر يغطي نفس الحدث، حتى لو جاء من مصدر مختلف أو بصياغة مختلفة: {recent_topics}

قواعد صارمة يجب الالتزام بها دون استثناء:
1) اختر خبراً واحداً فقط، تقنياً بحتاً، لم يُغطَّ من قبل بأي صياغة.
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

    client = genai.Client(api_key=GEMINI_API_KEY)

    # محاولة إعادة الاتصال تلقائياً حتى 3 مرات في حال واجه خطأ ضغط السيرفر 503
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=f"{system_prompt}\n\nالأخبار المتاحة:\n{news_text}",
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2
                )
            )
            content = json.loads(response.text)
            missing = [f for f in REQUIRED_FIELDS if f not in content]
            if missing:
                print(f"❌ رد Gemini ناقص الحقول المطلوبة: {missing}")
                return None
            return content
        except Exception as e:
            print(f"⚠️ محاولة {attempt+1} فشلت بسبب الضغط أو استثناء: {e}")
            if attempt < 2:
                time.sleep(5)  # انتظار 5 ثوانٍ قبل إعادة المحاولة
            else:
                print("❌ استنفدت محاولات الاتصال بـ Gemini.")
                return None
    return None




def build_post_content(title, main_event, tech_details_list, impact, source):
    """القالب الإخباري الثابت (Hardcoded) — لا يُترك للذكاء الاصطناعي كتابته حراً."""
    title = sanitize_field(title)
    main_event = sanitize_field(main_event)
    impact = sanitize_field(impact)
    tech_details_list = [sanitize_field(p) for p in tech_details_list if sanitize_field(p)]
    tech_details = "\n• ".join(tech_details_list) if tech_details_list else "لا توجد تفاصيل إضافية."

    post_content = f"""{title}

🔹 الحدث الرئيسي:
{main_event}

🔹 التفاصيل والأرقام التقنية:
• {tech_details}

🔹 الأثر والأهمية:
{impact}

—
✍️ إعداد: Eng. Limitless
🔗 المصدر: {source}
#تقنية #حاسوب #Eng_Limitless
"""
    return post_content

# =========================================================
# 7) النشر على تيليجرام (مع التحميل المحلي للبايتس لتفادي حظر الروابط)
# =========================================================
def publish_to_telegram(title, post_content, image_url, image_bytes):
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

    # 1. إرسال الصورة مع العنوان الرئيسي فقط (لضمان البقاء تحت 1024 حرف وتجنب مشاكل الـ Markdown)
    caption_text = f"🚨 **{title}**\n\n#تقنية #Eng_Limitless"

    if photo_data:
        try:
            print("📸 جاري نشر الصورة مع العنوان الرئيسي على تيليجرام...")
            tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            res = requests.post(
                tg_url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption_text[:1024],
                    "parse_mode": "Markdown",
                },
                files={"photo": ("image.jpg", photo_data, "image/jpeg")},
                timeout=30
            )
            if res.status_code == 200:
                # 2. بعد نجاح إرسال الصورة، نرسل التقرير المفصل الكامل كرسالة نصية مستقلة (تستوعب حتى 4096 حرف)
                print("📤 جاري إرسال التقرير التقني المفصل برسالة نصية تالية...")
                msg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                requests.post(
                    msg_url,
                    data={
                        "chat_id": TELEGRAM_CHAT_ID,
                        "text": post_content,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                    },
                    timeout=30
                )
                return res
            else:
                print(f"⚠️ رفض تيليجرام إرسال الصورة: {res.text}")
        except Exception as e:
            print(f"⚠️ خطأ أثناء إرسال الصورة: {e}")

    # الملاذ الأخير: إرسال المنشور كاملاً كنص منسق في حال تعذر إرسال الصورة
    print("📄 النشر كنص كامل منسق (بدون صورة)...")
    tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    return requests.post(
        tg_url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": post_content,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        },
        timeout=30
    )


# =========================================================
# 8) التشغيل الرئيسي
# =========================================================
def run():
    if not acquire_lock():
        return

    try:
        for var_name, var_val in [
            ("GROQ_API_KEY", GROQ_API_KEY),
            ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
            ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
        ]:
            if not var_val:
                print(f"❌ متغير البيئة {var_name} غير موجود. إنهاء آمن.")
                return

        history = load_history()
        current_month = datetime.now().strftime("%Y-%m")
        print(f"تم تحميل السجل: {len(history)} خبر منشور.")

        articles = fetch_news(history)
        if not articles:
            print("⚠️ لا توجد أخبار جديدة لم تُنشر من قبل ولم تتكرر موضوعياً!")
            return

        articles_to_process = articles[:15]
        recent_topics = [
            item.get("topic_key", "") for item in history
            if isinstance(item, dict) and item.get("month") == current_month
        ]

        content = None
        for attempt in range(2):
            candidate = call_gemini_for_selection(articles_to_process, recent_topics)
            if not candidate:
                continue

            try:
                selected_id = int(candidate.get("selected_id", 1))
                selected_article = articles_to_process[selected_id - 1]
            except Exception:
                selected_article = articles_to_process[0]

            topic_key = candidate.get("topic_key", selected_article["title"][:30])
            dup, reason = is_duplicate_against_history(
                selected_article["title"], selected_article["link"], topic_key, history
            )
            if dup:
                print(f"⚠️ الاختيار رقم {attempt + 1} مكرر ({reason})، إعادة المحاولة...")
                continue

            content = candidate
            content["_selected_article"] = selected_article
            break

        if not content:
            print("❌ لم يتم التوصل لخبر غير مكرر بعد المحاولات المتاحة. إنهاء آمن بدون نشر.")
            return

        selected_article = content["_selected_article"]
        title = content.get("title", selected_article["title"])
        main_event = content.get("main_event_summary", selected_article["summary"])
        tech_details_list = content.get("technical_details_points", [])
        impact = content.get("impact_analysis", "الأثر قيد التحليل.")
        source = selected_article["source_name"]
        topic_key = content.get("topic_key", selected_article["title"][:30])
        image_prompt = content.get("image_prompt", selected_article["title"])
        company_profile = content.get("company_profile")

        post_content = build_post_content(title, main_event, tech_details_list, impact, source)
        print(f"📌 الخبر المختار: {selected_article['title']}")

        image_url = get_og_image(selected_article["link"])
        image_bytes = None
        if not image_url:
            image_bytes = generate_google_imagen(image_prompt)

        history.append(
            {
                "title": selected_article["title"],
                "link": selected_article["link"],
                "topic_key": topic_key,
                "month": current_month,
                "posted_at": datetime.now().isoformat(),
            }
        )
        save_history(history)

        tg_res = publish_to_telegram(title, post_content, image_url, image_bytes)

        if tg_res and tg_res.status_code == 200:
            print("✅ تم النشر بنجاح على القناة!")
            message_id = tg_res.json()["result"]["message_id"]

            if company_profile and str(company_profile).strip().lower() != "null":
                reply_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                requests.post(
                    reply_url,
                    data={
                        "chat_id": TELEGRAM_CHAT_ID,
                        "text": f"🏢 **بطاقة تعريف بالشركة المذكورة:**\n\n{sanitize_field(company_profile)}",
                        "reply_to_message_id": message_id,
                        "parse_mode": "Markdown",
                    },
                )
            print("💾 تم حفظ التقرير في السجل لتفعيل الفلترة المستقبلية.")
        else:
            print("❌ خطأ أثناء النشر على تليجرام:", tg_res.text if tg_res else "No response")

    finally:
        release_lock()


if __name__ == "__main__":
    run()
