import os
import json
import requests
import feedparser
import urllib.parse

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HISTORY_FILE = "posted_history.json"

def load_history():
    """تحميل سجل الأخبار المنشورة سابقاً"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except:
                return []
    return []

def save_history(history):
    """حفظ سجل الأخبار"""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def run():
    history = load_history()
    print(f"تم تحميل السجل: {len(history)} خبر منشور سابقاً.")

    print("1. جاري جلب الأخبار من RSS...")
    feed = feedparser.parse("https://techcrunch.com/feed/")
    
    # فلترة الأخبار واستبعاد ما تم نشره سابقاً بناءً على الرابط
    new_articles = []
    for entry in feed.entries:
        if entry.link not in history:
            new_articles.append(entry)
            
    if not new_articles:
        print("لا توجد أخبار جديدة اليوم لم يتم نشرها من قبل!")
        return

    # أخذ أول 15 خبر جديد فقط
    articles_to_process = new_articles[:15]
    
    news_text = ""
    for idx, item in enumerate(articles_to_process, 1):
        news_text += f"ID: {idx} | Title: {item.title} | Link: {item.link} | Summary: {item.summary}\n"

    print("2. إرسال الأخبار للذكاء الاصطناعي للاختبار والصياغة...")
    groq_url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    system_prompt = """
    أنت صانع محتوى تقني محترف ومحبوب لدى الشباب العربي.
    المطلوب منك:
    1. اختيار أرقص وأهم خبر تقني من قائمة الأخبار المرفقة.
    2. صياغة منشور باللغة العربية الفصحى المبسطة والحديثة (أسلوب ودود، مباشر، مشوق، ومناسب للجمهور العربي واليمني دون تعقيد).
    3. أضف إيموجيات مناسبة وهاشتاجات تقنية في آخر المنشور.
    4. صياغة وصف دقيق باللغة الإنجليزية (Prompt) لتوليد صورة معبرة عالية الجودة.

    يجب أن ترجع الإجابة بصيغة JSON حصراً بالتنسيق التالي:
    {
      "selected_link": "رابط الخبر الذي اخترته من القائمة بالضبط",
      "post": "نص المنشور بالكامل...",
      "image_prompt": "Minimalist tech illustration of..."
    }
    """

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"الأخبار الجديدة المتاحة اليوم:\n{news_text}"}
        ],
        "response_format": {"type": "json_object"}
    }

    res = requests.post(groq_url, headers=headers, json=payload)
    res_data = res.json()
    content = json.loads(res_data['choices'][0]['message']['content'])

    selected_link = content.get('selected_link')
    post_text = content['post']
    image_prompt = content['image_prompt']

    print("3. توليد الصورة...")
    encoded_prompt = urllib.parse.quote(image_prompt)
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1080&model=flux&nologo=true"

    print("4. الإرسال إلى تليجرام...")
    tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    caption_text = post_text if len(post_text) <= 1000 else post_text[:990] + "..."
    
    tg_payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "photo": image_url,
        "caption": caption_text
    }
    
    tg_res = requests.post(tg_url, data=tg_payload)
    
    if tg_res.status_code == 200:
        print("تم النشر بنجاح على تليجرام!")
        # حفظ الخبر في السجل لمنع تكراره مستقبلاً
        if selected_link:
            history.append(selected_link)
            save_history(history)
            print("تم حفظ الخبر في سجل التاريخ.")
    else:
        print("خطأ أثناء الإرسال لتليجرام:", tg_res.text)

if __name__ == "__main__":
    run()
