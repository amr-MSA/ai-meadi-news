import os
import json
import re
import base64
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") # المفتاح الموحد للنصوص والصور
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HISTORY_FILE = "posted_history.json"

# المصادر المعتمدة
RSS_SOURCES = [
    {"name": "BleepingComputer", "url": "https://www.bleepingcomputer.com/feed/"},
    {"name": "Hacker News", "url": "https://news.ycombinator.com/rss"},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"}
]

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return []
    return []

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def is_already_posted(entry_title, entry_link, history):
    current_month = datetime.now().strftime("%Y-%m")
    for item in history:
        if isinstance(item, dict):
            # فحص الرابط أو تطابق العنوان
            if item.get("link") == entry_link or item.get("title") == entry_title:
                return True
        elif isinstance(item, str) and item == entry_link:
            return True
    return False

def get_og_image(article_url):
    """سحب الصورة الحقيقية والأصلية للمقال"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(article_url, headers=headers, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            og_img = soup.find('meta', property='og:image')
            if og_img and og_img.get('content'):
                img_url = og_img['content']
                if "http" in img_url and not img_url.endswith(".ico"):
                    return img_url
    except Exception as e:
        print(f"لم تُوجد صورة og:image: {e}")
    return None

def generate_google_imagen(prompt):
    """توليد صورة احتياطية احترافية عبر Google Imagen 3"""
    if not GEMINI_API_KEY:
        print("⚠️ مفتاح GEMINI_API_KEY غير مضاف.")
        return None

    print("🎨 جاري توليد صورة احتياطية احترافية عبر Google Imagen...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        # برومبت صارم لضمان الجودة والأسلوب المسطح
        "instances": [{"prompt": f"Minimalist professional clean minimalist flat vector icon design of... {prompt}, dark blue color palette"}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "1:1"
        }
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=25)
        if res.status_code == 200:
            data = res.json()
            b64_img = data['predictions'][0]['bytesBase64Encoded']
            return base64.b64decode(b64_img)
        else:
            print(f"❌ خطأ من Google Imagen API: {res.text}")
    except Exception as e:
        print(f"❌ استثناء أثناء توليد صورة Google: {e}")
    return None

def fetch_news(history):
    articles = []
    for source in RSS_SOURCES:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries:
                if not is_already_posted(entry.title, entry.link, history):
                    summary = getattr(entry, 'summary', entry.title)
                    clean_summary = re.sub('<[^<]+?>', '', summary)[:300]
                    articles.append({
                        "title": entry.title,
                        "link": entry.link,
                        "summary": clean_summary,
                        "source_name": source["name"]
                    })
        except Exception as e:
            print(f"خطأ في جلب {source['name']}: {e}")
    return articles

def run():
    history = load_history()
    current_month = datetime.now().strftime("%Y-%m")
    print(f"تم تحميل السجل: {len(history)} خبر منشور.")

    articles = fetch_news(history)
    if not articles:
        print("⚠️ لا توجد أخبار جديدة لليوم لم تُنشر من قبل!")
        return

    articles_to_process = articles[:15]
    news_text = ""
    for idx, item in enumerate(articles_to_process, 1):
        news_text += f"ID: {idx} | Source: {item['source_name']}\nTitle: {item['title']}\nSummary: {item['summary']}\nLink: {item['link']}\n---\n"

    # تجهيز سجل الموضوعات الشهرية لمنع التكرار الموضوعي
    recent_topics = [item.get("topic_key", "") for item in history if isinstance(item, dict) and item.get("month") == current_month]

    # برومبت نظام صارم و "آلي" لإجبار النموذج على ملء القالب
    system_prompt = f"""
    أنت محلّل تقني محترف في قناة Eng. Limitless الموجهة لمهندسي وطلاب الحاسوب.
    مواضيع تم نشرها هذا الشهر ويُمنع اختيار أي خبر يغطيها مجدداً: {recent_topics}

    المطلوب منك:
    1. اختيار أفضل خبر تقني/تسريب/ثغرة لم يُنشر هذا الشهر.
    2. استخراج "topic_key" باللغة الإنجليزية يصف الفكرة (مثل: Meta-Glimmer-AI).
    3. صياغة وصف بالإنكليزية للصورة الاحتياطية (image_prompt) بأسلوب Flat Vector Tech.
    4. ملء حقول JSON المحددة أدناه ليتكون التقرير آلياً، ممنوع أي تعليق إضافي أو أسئلة للمتابعين:
    
    {{
      "selected_id": 1,
      "topic_key": "topic-name",
      "image_prompt": "Clean flat vector illustration of...",
      "title": "[عنوان الخبر الرئيسي المباشر]",
      "main_event_summary": "[شرح مفصل ومباشر للحدث بدون مقدمات]",
      "technical_details_points": ["تفصيل تقني أو رقم 1", "تفصيل تقني أو رقم 2"],
      "impact_analysis": "[الأثر المباشر على المجال والطلاب]",
      "company_profile": "بطاقة تعريف بالشركة إن وجدت أو null"
    }}
    """

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"الأخبار المتاحة:\n{news_text}"}
        ],
        "response_format": {"type": "json_object"}
    }

    res = requests.post("https://api.groq.com/openai/v1/chat/completions", 
                        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}, 
                        json=payload)
    
    if res.status_code != 200:
        print("❌ خطأ من Groq API:", res.text)
        return

    content = json.loads(res.json()['choices'][0]['message']['content'])
    
    try:
        selected_id = int(content.get('selected_id', 1))
        selected_article = articles_to_process[selected_id - 1]
    except Exception:
        selected_article = articles_to_process[0]

    # بناء نص المنشور برمجياً من حقول JSON المحددة لضمان الامتثال التام للقالب الموحد
    title = content.get('title', selected_article['title'])
    main_event = content.get('main_event_summary', selected_article['summary'])
    tech_details_list = content.get('technical_details_points', [])
    tech_details = "\n• ".join(tech_details_list)
    impact = content.get('impact_analysis', "الأثر قيد التحليل.")
    source = selected_article['source_name']

    # القالب الموحد المطبق برمجياً
    post_content = f"""
{title}

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

    topic_key = content.get('topic_key', selected_article['title'][:30])
    image_prompt = content.get('image_prompt', selected_article['title'])
    company_profile = content.get('company_profile')

    print(f"📌 الخبر المختار: {selected_article['title']}")

    # 1️⃣ البحث عن الصورة الأصلية للمقال
    image_url = get_og_image(selected_article['link'])
    image_bytes = None

    # 2️⃣ إذا لم توجد صورة أصلية، استدعاء Google Imagen 3 (ببرومبت صارم جداً)
    if not image_url:
        image_bytes = generate_google_imagen(image_prompt)

    # 3️⃣ النشر على تليجرام بحسب الوسائط المتوفرة (أولوية للصورة الحقيقية)
    tg_res = None
    if image_url:
        print("📸 النشر مع صورة المقال الأصلية...")
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        tg_res = requests.post(tg_url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "photo": image_url,
            "caption": post_content[:1024],
            "parse_mode": "Markdown"
        })
    elif image_bytes:
        print("🎨 النشر مع الصورة المُولدة الاحترافية من Google Imagen...")
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        tg_res = requests.post(tg_url, 
                               data={"chat_id": TELEGRAM_CHAT_ID, "caption": post_content[:1024], "parse_mode": "Markdown"},
                               files={"photo": ("image.jpg", image_bytes, "image/jpeg")})
    else:
        print("📄 النشر كنص منسق عالي الجودة (بدون صورة لمنع الرداءة)...")
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        tg_res = requests.post(tg_url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": post_content,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })

    if tg_res and tg_res.status_code == 200:
        print("✅ تم النشر بنجاح على القناة!")
        message_id = tg_res.json()['result']['message_id']

        if company_profile and str(company_profile).strip().lower() != "null":
            reply_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(reply_url, data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"🏢 **بطاقة تعريف بالشركة المذكورة:**\n\n{company_profile}",
                "reply_to_message_id": message_id,
                "parse_mode": "Markdown"
            })

        # حفظ التكرار بالرابط والموضوع المقترن بالشهر لمنع التكرار الموضوعي
        history.append({
            "title": selected_article['title'],
            "link": selected_article['link'],
            "topic_key": topic_key,
            "month": current_month
        })
        save_history(history)
        print("💾 تم حفظ التقرير في السجل لتفعيل الفلترة.")
    else:
        print("❌ خطأ أثناء النشر على تليجرام:", tg_res.text if tg_res else "No response")

if __name__ == "__main__":
    run()
