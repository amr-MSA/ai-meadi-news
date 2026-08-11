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

# ─── ثوابت GitHub مُعرَّفة في الكود مباشرة ───
GITHUB_REPO = "amr-MSA/ai-meadi-news"
GITHUB_BRANCH = "main"

# ─── قراءة التوكن: في GitHub Actions يأتي تلقائياً كـ GITHUB_TOKEN
#     إذا شغّلت محلياً، استخدم GH_TOKEN (لأن GitHub يمنع GITHUB_ في Secrets) ───
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

# ─── عتبة طول التقرير ───
REPORT_LENGTH_THRESHOLD = 1000

HISTORY_FILE = "posted_history.json"
LOCK_FILE = "bot.lock"
REPORT_FILE = "report.txt"
IMAGE_FILE = "report_image.jpg"
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
    print("[1/10] 🔒 التحقق من قفل التنفيذ...")
    if os.path.exists(LOCK_FILE):
        age = time.time() - os.path.getmtime(LOCK_FILE)
        if age < LOCK_MAX_AGE_SECONDS:
            print("[1/10] ❌ يوجد تشغيل آخر نشط. إنهاء.")
            return False
        else:
            print("[1/10] ⚠️ قفل قديم متروك، تجاوز.")
    try:
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        print("[1/10] ✅ تم إنشاء القفل.")
        return True
    except Exception as e:
        print(f"[1/10] ⚠️ تعذر إنشاء القفل: {e}")
        return True


def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            print("[10/10] 🔓 تم إزالة القفل.")
    except Exception as e:
        print(f"[10/10] ⚠️ تعذر إزالة القفل: {e}")


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
    print("[2/10] 📂 تحميل السجل التاريخي...")
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                result = data if isinstance(data, list) else []
                print(f"[2/10] ✅ تم تحميل السجل: {len(result)} خبر منشور.")
                return result
            except Exception as e:
                print(f"[2/10] ⚠️ خطأ في قراءة السجل: {e}")
                return []
    print("[2/10] ℹ️ لا يوجد سجل سابق.")
    return []


def save_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        print("💾 تم حفظ السجل التاريخي.")
    except Exception as e:
        print(f"❌ فشل حفظ السجل: {e}")


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
    print("🔍 إزالة التكرار من مجموعة الأخبار...")
    unique = []
    for art in articles:
        is_dup = False
        for kept in unique:
            if similarity(art["title"], kept["title"]) >= TITLE_SIMILARITY_THRESHOLD:
                is_dup = True
                break
        if not is_dup:
            unique.append(art)
    print(f"🔍 تم تقليص الأخبار من {len(articles)} إلى {len(unique)} بعد إزالة التكرار.")
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
    print(f"🌐 جلب صورة المقال من: {article_url}")
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(article_url, headers=headers, timeout=8)
        if res.status_code != 200:
            print(f"🌐 ❌ فشل جلب الصفحة: {res.status_code}")
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
                print(f"🌐 ✅ تم العثور على صورة صالحة: {img_url[:80]}...")
                return img_url

    except Exception as e:
        print(f"🌐 ⚠️ استثناء أثناء جلب الصورة: {e}")

    print("🌐 ⚠️ لم تُوجد صورة OG صالحة.")
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
        print("🎨 ⚠️ مفتاح GEMINI_API_KEY غير موجود.")
        return None

    final_prompt = IMAGEN_STYLE_WRAPPER.format(subject=subject_prompt[:200])

    print("🎨 جاري توليد صورة احتياطية عبر Google Imagen...")
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
            print("🎨 ✅ تم توليد الصورة بنجاح.")
            return base64.b64decode(b64_img)
        else:
            print(f"🎨 ❌ خطأ Imagen API: {res.status_code} - {res.text[:200]}")
    except Exception as e:
        print(f"🎨 ❌ استثناء أثناء توليد الصورة: {e}")

    return None


# =========================================================
# 5) جلب الأخبار
# =========================================================
def fetch_news(history):
    print("[3/10] 📰 جلب الأخبار من المصادر...")
    articles = []
    for source in RSS_SOURCES:
        try:
            print(f"📰 جلب من {source['name']}...")
            feed = feedparser.parse(source["url"])
            count = 0
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
                    count += 1
            print(f"📰 ✅ {source['name']}: {count} خبر جديد.")
        except Exception as e:
            print(f"📰 ❌ خطأ في جلب {source['name']}: {e}")

    result = dedupe_articles_pool(articles)
    print(f"[3/10] ✅ إجمالي الأخبار المتاحة: {len(result)}")
    return result


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
    print("[4/10] 🤖 إرسال الأخبار إلى Gemini للاختيار...")
    if not GEMINI_API_KEY:
        print("[4/10] ❌ مفتاح GEMINI_API_KEY غير موجود.")
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
            print(f"🤖 محاولة {attempt + 1}/3...")
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
                print(f"🤖 ❌ رد Gemini ناقص الحقول: {missing}")
                               return None
            print("[4/10] ✅ تم استلام رد Gemini صالح.")
            return content
        except Exception as e:
            print(f"🤖 ⚠️ محاولة {attempt+1} فشلت: {e}")
            if attempt < 2:
                print("🤖 ⏳ انتظار 5 ثوانٍ قبل إعادة المحاولة...")
                time.sleep(5)
            else:
                print("[4/10] ❌ استنفدت محاولات الاتصال بـ Gemini.")
                return None
    return None


# =========================================================
# تهريب HTML لتيليجرام
# =========================================================
def escape_telegram_html(text):
    if not text:
        return text
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


# =========================================================
# بناء التقرير الشامل
# =========================================================
def build_full_report(title, main_event, tech_details_list, impact, source, company_profile=None):
    print("[5/10] 📝 بناء التقرير الشامل...")
    title = escape_telegram_html(sanitize_field(title))
    main_event = escape_telegram_html(sanitize_field(main_event))
    impact = escape_telegram_html(sanitize_field(impact))
    tech_details_list = [sanitize_field(p) for p in tech_details_list if sanitize_field(p)]
    tech_details_list = [escape_telegram_html(p) for p in tech_details_list]
    tech_details = "\n• ".join(tech_details_list) if tech_details_list else "لا توجد تفاصيل إضافية."

    header = "<b>╔══════════════════════════════════════╗</b>\n"
    header += "<b>║     📰  تقرير Eng. Limitless  📰     ║</b>\n"
    header += "<b>╚══════════════════════════════════════╝</b>\n\n"

    body = f"""<b>🚨 {title}</b>

🔹 <b>الحدث الرئيسي:</b>
{main_event}

🔹 <b>التفاصيل والأرقام التقنية:</b>
• {tech_details}

🔹 <b>الأثر والأهمية:</b>
{impact}
"""

    company_section = ""
    if company_profile and str(company_profile).strip().lower() != "null":
        cp = escape_telegram_html(sanitize_field(str(company_profile)))
        company_section = f"\n\n🏢 <b>بطاقة تعريف بالشركة المذكورة:</b>\n{cp}\n"

    footer = f"""\n
—
✍️ إعداد: Eng. Limitless
🔗 المصدر: {escape_telegram_html(source)}
📅 التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}
#تقنية #حاسوب #EngLimitless
"""

    full_report = header + body + company_section + footer
    print(f"[5/10] ✅ تم بناء التقرير ({len(full_report)} حرف).")
    return full_report


# =========================================================
# حفظ التقرير والصورة محلياً
# =========================================================
def save_report_locally(report_text, filename=REPORT_FILE):
    print(f"💾 حفظ التقرير محلياً في '{filename}'...")
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(report_text)
        print(f"💾 ✅ تم حفظ التقرير محلياً.")
        return True
    except Exception as e:
        print(f"💾 ❌ فشل حفظ التقرير محلياً: {e}")
        return False


def save_image_locally(image_data, filename=IMAGE_FILE):
    if not image_data:
        print(f"💾 ⚠️ لا توجد بيانات صورة لحفظها.")
        return False
    print(f"💾 حفظ الصورة محلياً في '{filename}'...")
    try:
        with open(filename, "wb") as f:
            f.write(image_data)
        print(f"💾 ✅ تم حفظ الصورة محلياً.")
        return True
    except Exception as e:
        print(f"💾 ❌ فشل حفظ الصورة محلياً: {e}")
        return False


# =========================================================
# رفع الملف إلى GitHub (إنشاء أو تعديل)
# =========================================================
def upload_to_github(filepath, repo_filename, commit_message="تحديث التقرير التقني"):
    print(f"[6/10] ☁️ رفع '{repo_filename}' إلى GitHub ({GITHUB_REPO})...")
    if not GITHUB_TOKEN:
        print("[6/10] ⚠️ لا يوجد توكن GitHub (GITHUB_TOKEN أو GH_TOKEN).")
        print("[6/10] ℹ️ في GitHub Actions: أضف 'GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}' في الـ Workflow.")
        return False

    try:
        with open(filepath, "rb") as f:
            content_bytes = f.read()
        content_b64 = base64.b64encode(content_bytes).decode("utf-8")

        api_base = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{repo_filename}"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

        sha = None
        print(f"☁️ التحقق من وجود الملف على GitHub...")
        check_res = requests.get(api_base, headers=headers, params={"ref": GITHUB_BRANCH})
        if check_res.status_code == 200:
            sha = check_res.json().get("sha")
            print(f"☁️ 📝 الملف موجود، سيتم التعديل (sha: {sha[:8]}...).")
        elif check_res.status_code == 404:
            print(f"☁️ ℹ️ الملف غير موجود، سيتم الإنشاء.")
        else:
            print(f"☁️ ⚠️ استجابة غير متوقعة أثناء التحقق: {check_res.status_code}")

        payload = {
            "message": commit_message,
            "content": content_b64,
            "branch": GITHUB_BRANCH
        }
        if sha:
            payload["sha"] = sha

        print(f"☁️ جاري الرفع/التعديل...")
        upload_res = requests.put(api_base, headers=headers, json=payload)

        if upload_res.status_code in [200, 201]:
            print(f"[6/10] ✅ تم رفع/تعديل الملف على GitHub بنجاح.")
            return True
        else:
            print(f"[6/10] ❌ فشل رفع الملف: {upload_res.status_code}")
            print(f"[6/10] 📄 الرد: {upload_res.text[:300]}")
            return False

    except Exception as e:
        print(f"[6/10] ❌ استثناء أثناء رفع الملف: {e}")
        return False


# =========================================================
# 7) النشر على تيليجرام (HTML Mode)
# =========================================================
def publish_to_telegram(title, full_report, image_url, image_bytes):
    print("[7/10] 📤 بدء النشر على تيليجرام...")
    photo_data = None

    # ─── تحضير الصورة ───
    if image_url:
        try:
            print("📥 تحميل صورة المقال...")
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            img_res = requests.get(image_url, headers=headers, timeout=12)
            if img_res.status_code == 200:
                photo_data = img_res.content
                print(f"📥 ✅ تم تحميل الصورة ({len(photo_data)} بايت).")
            else:
                print(f"📥 ❌ فشل تحميل الصورة: {img_res.status_code}")
        except Exception as e:
            print(f"📥 ❌ استثناء أثناء تحميل الصورة: {e}")

    if not photo_data and image_bytes:
        print("🎨 استخدام الصورة المُولدة...")
        photo_data = image_bytes

    # ─── حفظ الصورة محلياً دائماً ───
    save_image_locally(photo_data)

    report_length = len(full_report)
    print(f"📏 طول التقرير: {report_length} حرف (العتبة: {REPORT_LENGTH_THRESHOLD})")

    # ═══════════════════════════════════════════════════════
 