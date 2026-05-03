import os
import json
import asyncio
import feedparser
from balethon import Client
from google import genai

# دریافت تنظیمات از متغیرهای محیطی گیت‌هاب
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID") # آیدی عددی یا یوزرنیم کانال مقصد (مثلا @my_channel)
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME") # یوزرنیم برای نمایش در متن (مثلا @NewsChannel)

# لیست فیدهای RSS
RSS_FEEDS = [
    "https://digiato.com/rss", # لینک RSS های خود را اینجا بگذارید
]

STATE_FILE = "processed_urls.json"

client = genai.Client(api_key=GEMINI_API_KEY)
bot = Client(BOT_TOKEN)

def load_processed_urls():
    import os
    import json # مطمئن شوید json ایمپورت شده است
    
    if not os.path.exists("processed_urls.json"):
        return []
    
    try:
        with open("processed_urls.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        # اگر فایل خالی باشد یا JSON معتبر نباشد، لیست خالی برمی‌گرداند
        return []

def save_processed_urls(urls):
    # فقط 100 لینک آخر را نگه می‌داریم تا فایل خیلی سنگین نشود
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(urls[-100:], f, ensure_ascii=False, indent=2)

def rewrite_news_with_gemini(title, summary, link):
    prompt = f"""
    تو یک سردبیر و خبرنگار حرفه ای برای یک کانال تلگرامی/بله هستی.
    خبر زیر را خلاصه، جذاب و روان بازنویسی کن.
    
    عنوان اصلی: {title}
    متن اصلی: {summary}
    لینک منبع: {link}
    
    قوانین الزامی برای خروجی:
    1. خط اول حتماً عنوان خبر باشد و کاملاً **بولد** (بین دو ستاره **عنوان**) نوشته شود.
    2. متن خبر خلاصه‌تر و جذاب‌تر از متن اصلی باشد.
    3. در انتهای متن چند هشتگ مرتبط قرار بده.
    4. خط ماقبل آخر دقیقاً این عبارت باشد: "منبع: [لینک منبع]"
    5. خط آخر دقیقاً یوزرنیم کانال یعنی {CHANNEL_USERNAME} باشد.
    6. هیچ متن اضافه‌ای مثل "باشه"، "بفرمایید" یا توضیحات جمنای در خروجی نباشد.
    """
    
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        if hasattr(response, "text"):
            return response.text.strip()
        elif hasattr(response, "candidates") and response.candidates:
            return response.candidates[0].content.parts[0].text.strip()
    except Exception as e:
        print(f"Gemini Error: {e}")
        return None

async def main():
    processed_urls = load_processed_urls()
    new_urls_processed = False
    
    await bot.connect()

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        # بررسی 5 خبر آخر هر فید
        for entry in feed.entries[:5]:
            link = entry.link
            
            if link in processed_urls:
                continue # این خبر قبلا پردازش شده
                
            title = entry.title
            # برخی RSS ها متن را در summary و برخی در description دارند
            summary = getattr(entry, "summary", getattr(entry, "description", ""))
            
            print(f"Processing: {title}")
            
            rewritten_text = rewrite_news_with_gemini(title, summary, link)
            
            if rewritten_text:
                try:
                    await bot.send_message(chat_id=CHANNEL_ID, text=rewritten_text)
                    processed_urls.append(link)
                    new_urls_processed = True
                    await asyncio.sleep(2) # جلوگیری از فلود شدن درخواست‌ها
                except Exception as e:
                    print(f"Telegram/Bale Error: {e}")

    await bot.disconnect()
    
    if new_urls_processed:
        save_processed_urls(processed_urls)

if __name__ == "__main__":
    asyncio.run(main())
