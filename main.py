import os
import sqlite3
import asyncio
import re
from pathlib import Path

from balethon import Client
from balethon.conditions import private, command, text
from balethon.objects import InlineKeyboard, Message

import yt_dlp

# ================= تنظیمات اصلی ربات =================
BALE_TOKEN = "1011430416:0-QaVTm8WjXtmVRcZKFvhfr_OGOL6OldiZs"
CHANNEL_ID = "4646440155"

TEMP_DIR = Path(os.path.abspath("temp_uploads"))
TEMP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = "sc_archive.db"

bot = Client(BALE_TOKEN)
bot_username = ""

# ================= مدیریت دیتابیس =================
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS tracks (
                sc_id TEXT PRIMARY KEY,
                url TEXT,
                title TEXT,
                uploader TEXT,
                thumbnail TEXT,
                channel_msg_id TEXT
            )
        ''')
        conn.commit()

init_db()

def get_track_by_id(sc_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM tracks WHERE sc_id = ?", (sc_id,))
        return dict(c.fetchone() or {})

def get_track_by_url(url):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM tracks WHERE url = ?", (url,))
        return dict(c.fetchone() or {})

def save_track(data):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO tracks (sc_id, url, title, uploader, thumbnail, channel_msg_id)
            VALUES (?, ?, ?, ?, COALESCE(?, (SELECT thumbnail FROM tracks WHERE sc_id = ?)), COALESCE(?, (SELECT channel_msg_id FROM tracks WHERE sc_id = ?)))
        ''', (data['sc_id'], data['url'], data['title'], data['uploader'], 
              data.get('thumbnail'), data['sc_id'], 
              data.get('channel_msg_id'), data['sc_id']))
        conn.commit()

# ================= توابع yt-dlp =================
def search_sc_online(keyword):
    """جستجو در ساندکلاود با استفاده از yt-dlp"""
    ydl_opts = {'quiet': True, 'extract_flat': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        # جستجوی 5 نتیجه اول در ساندکلاود
        info = ydl.extract_info(f"scsearch5:{keyword}", download=False)
        return info.get('entries', [])

def fetch_sc_info(url):
    ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': False}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)

def download_sc_audio(url):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(TEMP_DIR / '%(id)s.%(ext)s'),
        'quiet': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

# ================= هندلرها =================
@bot.on_connect()
async def on_connect(client):
    global bot_username
    me = await client.get_me()
    bot_username = me.username
    print(f"Bot @{bot_username} is running...")

@bot.on_message(command("start"))
async def start_handler(client, message):
    await message.reply("سلام! لینک ساندکلاود بفرست یا متنی بفرست تا در ساندکلاود جستجو کنم.")

async def process_search(message, keyword):
    msg = await message.reply("🔍 در حال جستجو در ساندکلاود...")
    loop = asyncio.get_event_loop()
    
    try:
        results = await loop.run_in_executor(None, search_sc_online, keyword)
    except Exception as e:
        return await msg.edit_text("❌ خطا در جستجو.")

    if not results:
        return await msg.edit_text("متاسفانه نتیجه‌ای در ساندکلاود پیدا نشد.")
    
    buttons = []
    for res in results:
        # ذخیره اولیه در دیتابیس برای استفاده در کال‌بک
        save_track({
            'sc_id': res['id'],
            'url': res['url'],
            'title': res.get('title', 'نامشخص'),
            'uploader': res.get('uploader', 'نامشخص')
        })
        buttons.append([(f"🎵 {res.get('title', '')[:20]} - {res.get('uploader', '')[:15]}", f"show:{res['id']}")])
    
    keyboard = InlineKeyboard(*buttons)
    await msg.edit_text(f"نتایج جستجو برای: {keyword}", reply_markup=keyboard)

async def show_track_info(client, chat_id, url_or_id, is_url=False):
    # دریافت از دیتابیس در صورت وجود
    cached = get_track_by_url(url_or_id) if is_url else get_track_by_id(url_or_id)
    url = url_or_id if is_url else cached['url']
    
    # اگر کاور آرت ثبت نشده بود، اطلاعات کامل را می‌گیریم
    if not cached or not cached.get('thumbnail'):
        loop = asyncio.get_event_loop()
        try:
            info = await loop.run_in_executor(None, fetch_sc_info, url)
            cached = {
                'sc_id': info['id'],
                'url': url,
                'title': info.get('title', 'نامشخص'),
                'uploader': info.get('uploader', 'نامشخص'),
                'thumbnail': info.get('thumbnail', '')
            }
            save_track(cached)
        except Exception:
            return await client.send_message(chat_id, "❌ خطا در دریافت اطلاعات تکمیلی.")

    text_info = f"🎵 **عنوان:** {cached['title']}\n👤 **هنرمند:** {cached['uploader']}"
    keyboard = InlineKeyboard([("📥 دانلود", f"dl:{cached['sc_id']}")])

    if cached.get('thumbnail'):
        await client.send_photo(chat_id, cached['thumbnail'], caption=text_info, reply_markup=keyboard)
    else:
        await client.send_message(chat_id, text_info, reply_markup=keyboard)

@bot.on_message(text)
async def text_handler(client, message: Message):
    text_content = message.text
    if text_content.startswith("/"): return

    url_match = re.search(r'(https?://(?:www\.|on\.)?soundcloud\.com/[^\s]+)', text_content)
    is_pv = message.chat.type == "private"
    mentioned = bot_username and f"@{bot_username}" in text_content

    if url_match:
        if is_pv or mentioned:
            await show_track_info(client, message.chat.id, url_match.group(1), is_url=True)
    else:
        if is_pv:
            await process_search(message, text_content)
        elif mentioned:
            keyword = text_content.replace(f"@{bot_username}", "").strip()
            if keyword:
                await process_search(message, keyword)

@bot.on_callback_query()
async def callback_handler(client, callback_query):
    data = callback_query.data
    chat_id = callback_query.message.chat.id

    if data.startswith("show:"):
        sc_id = data.split(":")[1]
        await callback_query.answer()
        await show_track_info(client, chat_id, sc_id, is_url=False)

    elif data.startswith("dl:"):
        sc_id = data.split(":")[1]
        cached = get_track_by_id(sc_id)
        
        if not cached:
            return await callback_query.answer("خطا! دیتای آهنگ موجود نیست.")

        # چک کردن کانال آرشیو
        if cached.get('channel_msg_id'):
            await callback_query.answer("🚀 در حال ارسال از آرشیو...")
            return await client.send_audio(chat_id, cached['channel_msg_id'])

        # دانلود از yt-dlp در صورت عدم وجود در آرشیو
        await callback_query.answer("⏳ در حال دانلود از ساندکلاود...")
        msg = await client.send_message(chat_id, "⏳ در حال دانلود، لطفا صبور باشید...")
        loop = asyncio.get_event_loop()
        
        try:
            filepath = await loop.run_in_executor(None, download_sc_audio, cached['url'])
            
            # آپلود در کانال آرشیو
            archive_msg = await client.send_audio(
                CHANNEL_ID, 
                filepath, 
                caption=f"🎵 {cached['title']} \n👤 {cached['uploader']}"
            )
            
            # ثبت آیدی پیام در دیتابیس
            cached['channel_msg_id'] = archive_msg.document.id
            save_track(cached)
            
            # ارسال برای کاربر
            await client.send_audio(chat_id, archive_msg.document.id)
            await msg.delete()
            
            if os.path.exists(filepath):
                os.remove(filepath)
                
        except Exception as e:
            await msg.edit_text(f"❌ خطا در دانلود: {e}")

if __name__ == "__main__":
    bot.run()
