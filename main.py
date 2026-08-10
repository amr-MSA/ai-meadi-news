import os
import json
import re
import requests
import feedparser
import urllib.parse
from bs4 import BeautifulSoup

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HISTORY_FILE = "posted_history.json"

# المصادر الإخبارية المعتمدة
RSS_SOURCES = [
    "https://www.bleepingcomputer.com/feed/", # أمن سيبراني وتسريبات وعاجل
    "https://news.ycombinator.com/rss",        # تسريبات وتقنيات نادرة من Hacker News
    "https://www.theverge.com/rss/index.xml",  # أخبار الذكاء الاصطناعي والتقنية العامة
    "https://techcrunch.com/feed/"             # الأخبار العامة
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

def is_already_posted(entry, history):
    for item in history:
        if isinstance(item, dict):
            if item.get("link") == entry.link or item.get("title") == entry.title:
                return True
        elif isinstance(item, str) and item == entry.link:
            return True
    return False

def get_og_image(article_url):
    """جلب الصورة الحقيقية للمقال من الميتا تاغ og:image"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(article_url, headers=headers, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            og_img = soup.find('meta', property='og:image')
            if og_img and og_img.get('content'):
                return og_img['content']
    except Exception as e:
        print(f"تعذر جلب og:image: {e}")
    return None

def fetch_all_news(history):
    all_articles = []
    for source in RSS_SOURCES:
        try:
            feed = feedparser.parse(source)
            for entry in feed.entries:
                if not is_already_posted(entry, history):
                    all_articles.append(entry)
        except Exception as e:
            print(f"خطأ أثناء جلب {source}: {e}")
    return all_articles

def run():
    history = load_history()
    print(f"السجل الحالي: {len(history)} خبر سابق.")

    print("1️⃣ جاري جلب الأخبار من المصادر متعددة...")
    new_articles = fetch_all_news(history)
    
    if not new_articles:
        print("⚠️ لا توجد أخبار جديدة لم تُنشر من قبل!")
        return

    articles_to_process = new_articles[:15]
    
    news_text = ""
    for idx, item in enumerate(articles_to_process, 1):
        summary = getattr(item, 'summary', item.title)
        # تنظيف النص من أوسمة HTML
        clean_summary = re.sub('<[^<]+?>', '', summary)[:250]
        news_text += f"ID: {idx}\nTitle: {item.title}\nLink: {item.link}\nSummary: {clean_summary}\n---\n"

    print("2️⃣ إرسال الأخبار لـ Groq للتطليع والفلترة...")
    groq_url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    system_prompt = """
    أنت رئيس تحرير صحيفة تقنية موجهة لمهندسي وطلاب الحاسوب.
    معايير الاختيار:
    - أعطِ الأولوية المباشرة لـ: التسريبات (Leaks)، الثغرات الأمنية الكبرى، أدوات البرمجة والذكاء الاصطناعي الجديدة، أو الأحداث العاجلة.
    - استبعد تماماً: صفقات القروض، الاستحواذات المالية للشركات المغمورة، والأخبار الروتينية.

    المطلوب منك إرجاع JSON حصراً بالتنسيق التالي:
    {
      "selected_id": 1,
      "is_breaking": true,
      "post": "نص المنشور باللغة العربية الفصحى المبسطة بأسلوب تقني جذاب مع إيموجي وهاشتاجات...",
      "company_profile": "بطاقة تعريفية متكاملة بالشركة المذكورة في الخبر (إن وُجدت)، تشمل: المقر، التخصص، وأبرز منتجاتها. أو null إذا لم يتضمن الخبر شركة محددة",
      "fallback_image_prompt": "Flat minimalist vector style tech illustration of..."
    }
    """

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"قائمة الأخبار المتاحة:\n{news_text}"}
        ],
        "response_format": {"type": "json_object"}
    }

    res = requests.post(groq_url, headers=headers, json=payload)
    if res.status_code != 200:
        print("❌ خطأ من Groq:", res.text)
        return

    content = json.loads(res.json()['choices'][0]['message']['content'])

    try:
        selected_id = int(content.get('selected_id', 1))
        selected_article = articles_to_process[selected_id - 1]
    except Exception:
        selected_article = articles_to_process[0]

    post_text = content['post']
    company_profile = content.get('company_profile')
    is_breaking = content.get('is_breaking', False)

    if is_breaking:
        post_text = "⚡ **تغطية خاصة / خبر عاجل**\n\n" + post_text

    print(f"📌 الخبر المختار: {selected_article.title}")

    print("3️⃣ البحث عن صورة الخبر الأصلية...")
    image_url = get_og_image(selected_article.link)
    
    if not image_url:
        print("لم تتم إيجاد صورة أصلية، جاري التوليد الاحتياطي...")
        encoded_prompt = urllib.parse.quote(content.get('fallback_image_prompt', 'tech illustration'))
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1080&model=flux&nologo=true"

    print("4️⃣ إرسال المنشور الرئيسي إلى القناة...")
    tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    caption_text = post_text if len(post_text) <= 1000 else post_text[:990] + "..."
    
    tg_payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "photo": image_url,
        "caption": caption_text,
        "parse_mode": "Markdown"
    }
    
    tg_res = requests.post(tg_url, data=tg_payload)
    
    if tg_res.status_code == 200:
        print("✅ تم نشر الخبر الرئيسي!")
        res_json = tg_res.json()
        message_id = res_json['result']['message_id']

        # إذا كانت هناك بطاقة تعريفية للشركة، أرسلها كـ Reply تحت المنشور
        if company_profile and str(company_profile).strip().lower() != "null":
            print("5️⃣ إرسال بطاقة الشركة كتعليق/رد على المنشور...")
            reply_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            reply_payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"🏢 **بطاقة تعريفية بالشركة المذكورة:**\n\n{company_profile}",
                "reply_to_message_id": message_id,
                "parse_mode": "Markdown"
            }
            requests.post(reply_url, data=reply_payload)

        history.append({
            "title": selected_article.title,
            "link": selected_article.link
        })
        save_history(history)
        print("💾 تم حفظ الخبر لمنع التكرار.")
    else:
        print("❌ خطأ أثناء النشر على تليجرام:", tg_res.text)

if __name__ == "__main__":
    run()
