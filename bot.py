import os
import re
import time
from threading import Thread
from chanify import Chanify
from flask import Flask
import requests
import static_ffmpeg
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
import yt_dlp

# --- 0. تثبيت وتفعيل FFmpeg ---
try:
  static_ffmpeg.add_paths()
except Exception as e:
  print(f'FFmpeg setup warning: {e}')

# --- 1. خادم Flask للـ Keep-Alive ---
app = Flask(__name__)


@app.route('/')
def health_check():
  return 'Bot is running fine!'


def run_server():
  port = int(os.environ.get('PORT', 8080))
  app.run(host='0.0.0.0', port=port)


# --- 2. Self-Ping ---
def keep_alive_ping():
  time.sleep(10)
  url = 'https://nowm-downloader-bot-3-syg0.onrender.com'
  while True:
    try:
      requests.get(url, timeout=10)
      print('Self-ping sent successfully!')
    except Exception as e:
      print(f'Self-ping failed: {e}')
    time.sleep(600)


Thread(target=run_server, daemon=True).start()
Thread(target=keep_alive_ping, daemon=True).start()

# --- 3. إعداد البوت والمفاتيح ---
TOKEN = os.environ.get('TOKEN')
CHANIFY_KEY = os.environ.get('CHANIFY_KEY')

if not TOKEN:
  raise ValueError(
      '❌ خطأ: لم يتم ضبط متغير البيئة TOKEN في لوحة تحكم Render!'
  )

chanify = Chanify(CHANIFY_KEY) if CHANIFY_KEY else None
bot = telebot.TeleBot(TOKEN)

user_urls = {}
COOKIE_FILE = 'cookies.txt'

# إعدادات متقدمة لتجاوز حظر Render IP
COMMON_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'geo_bypass': True,
    'user_agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,'
        ' like Gecko) Chrome/125.0.0.0 Safari/537.36'
    ),
    'extractor_args': {
        'youtube': {
            'player_client': ['web', 'mweb', 'ios'],
            'skip': ['hls', 'dash'],
        }
    },
}

if os.path.exists(COOKIE_FILE):
  COMMON_OPTS['cookiefile'] = COOKIE_FILE


@bot.message_handler(commands=['start'])
def send_welcome(message):
  bot.reply_to(
      message,
      'مرحباً بك! أرسل رابط فيديو من يوتيوب أو تيك توك لتنزيله كـ فيديو MP4 أو'
      ' صوت MP3.',
  )


@bot.message_handler(func=lambda message: True)
def handle_message(message):
  user_id = message.chat.id
  url = message.text.strip()

  if not url.startswith('http'):
    bot.reply_to(message, 'الرجاء إرسال رابط صحيح.')
    return

  user_urls[user_id] = url

  markup = InlineKeyboardMarkup()
  btn_video = InlineKeyboardButton('تنزيل كـ فيديو 🎥', callback_data='dl_video')
  btn_audio = InlineKeyboardButton(
      'تنزيل كـ صوت MP3 🎵', callback_data='dl_audio'
  )
  markup.add(btn_video, btn_audio)

  bot.reply_to(message, 'اختر نوع التنزيل المطلوب:', reply_markup=markup)


@bot.callback_query_handler(
    func=lambda call: call.data in ['dl_video', 'dl_audio']
)
def handle_download_choice(call):
  user_id = call.message.chat.id
  url = user_urls.pop(user_id, None)

  if not url:
    bot.send_message(
        user_id, 'حدث خطأ أو انتهت جلسة الرابط، يرجى إعادة إرساله.'
    )
    return

  bot.answer_callback_query(call.id, 'جاري فحص الرابط ومعالجته...')

  if chanify:
    try:
      chanify.show_ad(chat_id=user_id)
    except Exception as e:
      print(f'Chanify Error: {e}')

  status_msg = bot.send_message(user_id, '🔍 جاري فحص الملف ومعرفة الحجم...')

  is_audio = call.data == 'dl_audio'
  is_tiktok = 'tiktok.com' in url.lower()
  file_path = None

  try:
    ydl_info_opts = COMMON_OPTS.copy()
    ydl_info_opts['format'] = 'b/worst'  # أبسط صيغة متوفرة لمنع خطأ Format
    filesize_mb = 0
    title = 'Media_File'

    with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
      try:
        info = ydl.extract_info(url, download=False)
        title = info.get('title', 'Media_File')
        filesize = info.get('filesize') or info.get('filesize_approx') or 0
        filesize_mb = filesize / (1024 * 1024) if filesize else 0
      except Exception as info_err:
        print(f'Info Fetch Warning: {info_err}')

    if filesize_mb > 50 and not is_tiktok:
      bot.edit_message_text(
          f'⚠️ **حجم الملف كبير ({filesize_mb:.1f} MB)** ويتجاوز حد الـ 50MB'
          ' المسموح به للرفع المباشر داخل تلجرام.',
          user_id,
          status_msg.message_id,
          parse_mode='Markdown',
      )
    else:
      bot.edit_message_text(
          '⏳ جاري تحميل وتجهيز الملف...', user_id, status_msg.message_id
      )

      ydl_dl_opts = COMMON_OPTS.copy()
      os.makedirs('downloads', exist_ok=True)
      filename_template = f'downloads/{user_id}_%(id)s.%(ext)s'

      if is_audio:
        ydl_dl_opts.update({
            'format': 'ba/b/best',
            'outtmpl': filename_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
      else:
        # صيغ يوتيوب الجاهزة المدمجة لتفادي مشاكل التفاوض
        ydl_dl_opts.update({
            'format': (
                'best[ext=mp4]/bestvideo+bestaudio/b[ext=mp4]/best/worst'
            ),
            'outtmpl': filename_template,
            'merge_output_format': 'mp4',
        })

      with yt_dlp.YoutubeDL(ydl_dl_opts) as ydl:
        download_info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(download_info)

        if is_audio:
          base_path = os.path.splitext(file_path)[0]
          if os.path.exists(base_path + '.mp3'):
            file_path = base_path + '.mp3'

      if file_path and os.path.exists(file_path):
        bot.edit_message_text(
            '📤 جاري رفع الملف إلى محادثتك...', user_id, status_msg.message_id
        )

        with open(file_path, 'rb') as f:
          if is_audio:
            bot.send_audio(
                user_id,
                f,
                title=title,
                performer='Smart Downloader',
                caption=f'🎵 **{title}**',
                parse_mode='Markdown',
            )
          else:
            bot.send_video(
                user_id,
                f,
                caption=f'🎥 **{title}**',
                parse_mode='Markdown',
            )

        bot.delete_message(user_id, status_msg.message_id)
      else:
        bot.send_message(user_id, 'تعذر العثور على الملف بعد المعالجة.')

  except Exception as e:
    print(f'Error Details: {e}')
    bot.send_message(
        user_id,
        'حدث خطأ أثناء معالجة الرابط، يرجى التأكد من الرابط أو المحاولة'
        ' لاحقاً.',
    )

  finally:
    if file_path and os.path.exists(file_path):
      try:
        os.remove(file_path)
      except Exception as clean_err:
        print(f'Cleanup Error: {clean_err}')


# --- 4. تشغيل البوت ---
print('Smart Downloader Bot is running...')

try:
  bot.remove_webhook()
except Exception as e:
  print(f'Webhook Removal Warning: {e}')

while True:
  try:
    bot.infinity_polling(
        timeout=20, long_polling_timeout=10, skip_pending=True
    )
  except Exception as e:
    print(f'Polling Exception Handled: {e}')
    time.sleep(5)
