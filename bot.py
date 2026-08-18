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

# --- 1. إعداد FFmpeg ---
try:
  static_ffmpeg.add_paths()
except Exception as e:
  print(f'FFmpeg Warning: {e}')

# --- 2. خادم Flask ---
app = Flask(__name__)


@app.route('/')
def health_check():
  return 'Bot Service Active'


def run_server():
  port = int(os.environ.get('PORT', 8080))
  app.run(host='0.0.0.0', port=port)


def keep_alive_ping():
  time.sleep(20)
  url = 'https://nowm-downloader-bot-3-syg0.onrender.com'
  while True:
    try:
      requests.get(url, timeout=10)
    except Exception as e:
      print(f'Keep-alive failed: {e}')
    time.sleep(600)


Thread(target=run_server, daemon=True).start()
Thread(target=keep_alive_ping, daemon=True).start()

# --- 3. تهيئة البوت ---
TOKEN = os.environ.get('TOKEN')
CHANIFY_KEY = os.environ.get('CHANIFY_KEY')

if not TOKEN:
  raise ValueError('❌ لم يتم العثور على TOKEN!')

chanify = Chanify(CHANIFY_KEY) if CHANIFY_KEY else None
bot = telebot.TeleBot(TOKEN)

user_urls = {}
COOKIE_FILE = 'cookies.txt'

# --- إعدادات yt-dlp المرنة للسيرفرات السحابية ---
BASE_YTDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'geo_bypass': True,
    # اختيار صيغة جاهزة مسبقاً يمنع خطأ Requested format
    'format': 'best',
    'format_sort': ['res', 'ext:mp4:m4a'],
    'extractor_args': {
        'youtube': {'player_client': ['android', 'ios', 'mweb', 'web']}
    },
}

if os.path.exists(COOKIE_FILE):
  BASE_YTDL_OPTS['cookiefile'] = COOKIE_FILE


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

  bot.answer_callback_query(call.id, 'جاري معالجة طلبك...')

  if chanify:
    try:
      chanify.show_ad(chat_id=user_id)
    except Exception as e:
      print(f'Chanify Error: {e}')

  status_msg = bot.send_message(user_id, '🔍 جاري فحص الرابط والمعلومات...')

  is_audio = call.data == 'dl_audio'
  is_tiktok = 'tiktok.com' in url.lower()
  file_path = None

  try:
    filesize_mb = 0
    title = 'Media_File'

    # 1. جلب معلومات الملف
    with yt_dlp.YoutubeDL(BASE_YTDL_OPTS) as ydl:
      try:
        info = ydl.extract_info(url, download=False)
        title = info.get('title', 'Media_File')
        filesize = info.get('filesize') or info.get('filesize_approx') or 0
        filesize_mb = filesize / (1024 * 1024) if filesize else 0
      except Exception as info_err:
        print(f'Info Fetch Warning: {info_err}')

    if filesize_mb > 50 and not is_tiktok:
      bot.edit_message_text(
          f'⚠️ **حجم الملف كبير ({filesize_mb:.1f} MB)** ويتجاوز الحد المسموح'
          ' به (50MB) للرفع في تلجرام.',
          user_id,
          status_msg.message_id,
          parse_mode='Markdown',
      )
      return

    bot.edit_message_text(
        '⏳ جاري تحميل وتجهيز الملف...', user_id, status_msg.message_id
    )

    # 2. تحديد إعدادات التنزيل
    os.makedirs('downloads', exist_ok=True)
    filename_template = f'downloads/{user_id}_{int(time.time())}.%(ext)s'

    ydl_dl_opts = BASE_YTDL_OPTS.copy()
    ydl_dl_opts['outtmpl'] = filename_template

    if is_audio:
      ydl_dl_opts.update({
          'format': 'bestaudio/best',
          'postprocessors': [{
              'key': 'FFmpegExtractAudio',
              'preferredcodec': 'mp3',
              'preferredquality': '192',
          }],
      })
    else:
      ydl_dl_opts.update({
          'format': 'best',
      })

    # 3. التنزيل
    with yt_dlp.YoutubeDL(ydl_dl_opts) as ydl:
      download_info = ydl.extract_info(url, download=True)
      file_path = ydl.prepare_filename(download_info)

      if is_audio:
        base_path = os.path.splitext(file_path)[0]
        if os.path.exists(base_path + '.mp3'):
          file_path = base_path + '.mp3'

    if file_path and os.path.exists(file_path):
      bot.edit_message_text(
          '📤 جاري رفع الملف إلى المحادثة...', user_id, status_msg.message_id
      )

      with open(file_path, 'rb') as f:
        if is_audio:
          bot.send_audio(
              user_id,
              f,
              title=title,
              performer='Downloader Bot',
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
      bot.send_message(user_id, 'تعذر الوصول إلى الملف بعد التحميل.')

  except Exception as e:
    print(f'Error Details: {e}')
    bot.send_message(
        user_id,
        'حدث خطأ أثناء معالجة الرابط، يرجى التأكد من الرابط أو المحاولة لاحقاً.',
    )

  finally:
    if file_path and os.path.exists(file_path):
      try:
        os.remove(file_path)
      except Exception as clean_err:
        print(f'Cleanup Error: {clean_err}')


# --- 4. التشغيل ومنع الـ Conflict ---
if __name__ == '__main__':
  # إلغاء أي Session قديمة من تلجرام
  try:
    bot.remove_webhook()
    time.sleep(2)
  except Exception as e:
    print(f'Webhook reset error: {e}')

  while True:
    try:
      bot.polling(
          non_stop=True,
          interval=2,
          timeout=30,
          long_polling_timeout=20,
          skip_pending=True,
      )
    except Exception as e:
      print(f'Polling Exception Handled: {e}')
      time.sleep(5)
