import os
import sqlite3
import asyncio
import re
from pathlib import Path

from balethon import Client
from balethon.conditions import private, command, text, group
from balethon.objects import InlineKeyboard, Message

import yt_dlp

# ================= تنظیمات اصلی ربات =================
BALE_TOKEN = "1011430416:0-QaVTm8WjXtmVRcZKFvhfr_OGOL6OldiZs"
CHANNEL_ID = "4646440155"

TEMP_DIR = Path(os.path.abspath("temp_uploads"))
TEMP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = "sc_archive.db"

bot = Client(BALE_TOKEN)
bot_username = "" # به صورت خودکار پر می‌شود

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

def get_track_by_url(url):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM tracks WHERE url = ?", (url,))
        return dict(c.fetchone() or {})

def get_track_by_id(sc_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM tracks WHERE sc_id = ?", (sc_id,))
        return dict(c.fetchone() or {})

def search_tracks(keyword):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM tracks WHERE title LIKE ? OR uploader LIKE ? LIMIT 10", (f"%{keyword}%", f"%{keyword}%"))
        return [dict(row) for row in c.fetchall()]

def save_track(data):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO tracks (sc_id, url, title, uploader, thumbnail, channel_msg_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (data['sc_id'], data['url'], data['title'], data['uploader'], data.get('thumbnail'), data.get('channel_msg_id')))
        conn.commit()

# ================= توابع ساندکلاود =================
def fetch_sc_info(url):
    ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': False}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info

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
    await message.reply("سلام! لینک ساندکلاود بفرست تا اطلاعاتشو بیارم یا متنی بفرست تا تو آرشیو سرچ کنم.")

async def process_search(message, keyword):
    results = search_tracks(keyword)
    if not results:
        return await message.reply("متاسفانه چیزی در آرشیو پیدا نشد.")

    buttons = []
    for res in results:
        buttons.append([(f"🎵 {res['title'][:20]} - {res['uploader'][:15]}", f"show:{res['sc_id']}")])

    keyboard = InlineKeyboard(*buttons)
    await message.reply(f"نتایج جستجو برای: {keyword}", keyboard)

async def process_sc_link(client, message, url):
    msg = await message.reply("در حال دریافت اطلاعات ساندکلاود...")

    # بررسی کش در دیتابیس
    cached = get_track_by_url(url)

    if cached and cached.get('channel_msg_id'):
        title = cached['title']
        uploader = cached['uploader']
        sc_id = cached['sc_id']
        thumb = cached['thumbnail']
    else:
        loop = asyncio.get_event_loop()
        try:
            info = await loop.run_in_executor(None, fetch_sc_info, url)
            title = info.get('title', 'نامشخص')
            uploader = info.get('uploader', 'نامشخص')
            sc_id = info.get('id')
            thumb = info.get('thumbnail', '')

            # ذخیره اطلاعات اولیه بدون آیدی پیام کانال
            save_track({'sc_id': sc_id, 'url': url, 'title': title, 'uploader': uploader, 'thumbnail': thumb})
        except Exception as e:
            return await msg.edit_text(f"خطا در دریافت اطلاعات: {e}")

    text_info = f"🎵 **عنوان:** {title}\n👤 **هنرمند:** {uploader}"
    keyboard = InlineKeyboard([("📥 دانلود فایل صوتی", f"dl:{sc_id}")])

    await msg.delete()
    if thumb:
        await client.send_photo(message.chat.id, thumb, caption=text_info, reply_markup=keyboard)
    else:
        await message.reply(text_info, keyboard)

@bot.on_message(text)
async def text_handler(client, message: Message):
    text_content = message.text

    if text_content.startswith("/"): return

    # استخراج لینک
    url_match = re.search(r'(https?://(?:www\.|on\.)?soundcloud\.com/[^\s]+)', text_content)

    is_pv = message.chat.type == "private"
    mentioned = bot_username and f"@{bot_username}" in text_content

    if url_match:
        if is_pv or mentioned:
            await process_sc_link(client, message, url_match.group(1))
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
        cached = get_track_by_id(sc_id)
        if not cached:
            return await callback_query.answer("اطلاعات یافت نشد!")

        text_info = f"🎵 **عنوان:** {cached['title']}\n👤 **هنرمند:** {cached['uploader']}"
        keyboard = InlineKeyboard([("📥 دانلود", f"dl:{sc_id}")])
        if cached['thumbnail']:
            await client.send_photo(chat_id, cached['thumbnail'], caption=text_info, reply_markup=keyboard)
        else:
            await client.send_message(chat_id, text_info, reply_markup=keyboard)
        await callback_query.answer()

    elif data.startswith("dl:"):
        sc_id = data.split(":")[1]
        cached = get_track_by_id(sc_id)

        if not cached:
            return await callback_query.answer("خطا! دیتای آهنگ موجود نیست.")

        # اگر قبلا دانلود شده و در کانال هست
        if cached.get('channel_msg_id'):
            await callback_query.answer("در حال ارسال از آرشیو...")
            await client.send_audio(chat_id, cached['channel_msg_id'])
            return

        # اگر دانلود نشده
        await callback_query.answer("در حال دانلود، لطفا صبور باشید...")
        msg = await client.send_message(chat_id, "⏳ در حال دانلود و آپلود...")
        loop = asyncio.get_event_loop()

        try:
            filepath = await loop.run_in_executor(None, download_sc_audio, cached['url'])

            # ارسال به کانال آرشیو
            archive_msg = await client.send_audio(CHANNEL_ID, filepath, caption=f"{cached['title']} - {cached['uploader']}")

            # بروزرسانی دیتابیس
            cached['channel_msg_id'] = archive_msg.document.id
            save_track(cached)

            # ارسال به کاربر
            await client.send_audio(chat_id, archive_msg.document.id)
            await msg.delete()

            if os.path.exists(filepath):
                os.remove(filepath)

        except Exception as e:
            await msg.edit_text(f"❌ خطا در دانلود: {e}")

if __name__ == "__main__":
    bot.run()
