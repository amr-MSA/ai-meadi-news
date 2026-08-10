import os
import json
import requests
import feedparser
import urllib.parse

# 1. استدعاء مفاتيح الأمان من البيئة
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def run():
    print("1. جاري جلب الأخبار التقنية من RSS...")
    feed = feedparser.parse("https://techcrunch.com/feed/")
    articles = feed.entries[:20]
    
    news_text = ""
    for idx, item in enumerate(articles, 1):
        news_text += f"{idx}. {item.title}: {item.summary}\n"

    print("2. الاتصال بنموذج Groq (Llama 3.3 70B)...")
    groq_url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    system_prompt = """
    أنت صانع محتوى تقني خبير. سيتم تزويدك بـ 20 خبر تقني.
    المطلوب منك:
    1. اختيار أهم وأفضل خبر منهم.
    2. كتابة منشور جذاب ومفصل للشبكات الاجتماعية باللغة العربية يشرح الخبر مع إيموجي وهاشتاجات مناسبة.
    3. صياغة وصف دقيق باللغة الإنجليزية لتوليد صورة مناسبة للخبر (Image Prompt).
    
    يجب أن ترجع النتيجة بصيغة JSON فقط بالتنسيق التالي:
    {
      "post": "نص المنشور باللغة العربية...",
      "image_prompt": "Detailed English prompt for image generation..."
    }
    """

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"الأخبار المتاحة اليوم:\n{news_text}"}
        ],
        "response_format": {"type": "json_object"}
    }

    res = requests.post(groq_url, headers=headers, json=payload)
    res_data = res.json()
    content = json.loads(res_data['choices'][0]['message']['content'])

    post_text = content['post']
    image_prompt = content['image_prompt']
    
    print("3. إنشاء رابط الصورة المجاني عبر Flux...")
    encoded_prompt = urllib.parse.quote(image_prompt)
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1080&model=flux&nologo=true"

    print("4. إرسال الصورة والمنشور إلى التليجرام...")
    tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    
    # تحكم بطول النص المرفق بالصورة لتجنب تجاوز حد تليجرام
    caption_text = post_text if len(post_text) <= 1000 else post_text[:990] + "..."
    
    tg_payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "photo": image_url,
        "caption": caption_text
    }
    
    tg_res = requests.post(tg_url, data=tg_payload)
    print("نتيجة الإرسال لتليجرام:", tg_res.status_code)

if __name__ == "__main__":
    run()

