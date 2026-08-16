import os
import re
from threading import Thread
from chanify import Chanify
from flask import Flask
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
import yt_dlp

# --- 1. خادم Flask للـ Keep-Alive ---
app = Flask(__name__)


@app.route('/')
def health_check():
  return 'Bot is running fine!'


def run_server():
  port = int(os.environ.get('PORT', 8080))
  app.run(host='0.0.0.0', port=port)


Thread(target=run_server, daemon=True).start()

# --- 2. جلب المفاتيح بأمان من Environment Variables ---
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

# إعدادات التخفي وتجاوز قيود منصات الفيديو
BASE_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'geo_bypass': True,
    'extractor_args': {
        'youtube': {
            'player_client': [
                'android',
                'ios',
                'mweb',
                'web_creator',
                'android_creator',
            ],
            'player_skip': ['configs', 'webpage'],
        }
    },
}

if os.path.exists(COOKIE_FILE):
  BASE_YDL_OPTS['cookiefile'] = COOKIE_FILE


def clean_filename(title):
  return re.sub(r'[\\/*?:"<>|]', '', title)


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
    ydl_info_opts = BASE_YDL_OPTS.copy()
    with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
      info = ydl.extract_info(url, download=False)
      title = info.get('title', 'Media_File')
      filesize = info.get('filesize') or info.get('filesize_approx') or 0
      filesize_mb = filesize / (1024 * 1024) if filesize else 0

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
          '⏳ جاري تحميل وتجهيز الملف...',
          user_id,
          status_msg.message_id,
      )

      ydl_dl_opts = BASE_YDL_OPTS.copy()
      os.makedirs('downloads', exist_ok=True)

      filename_template = f'downloads/{user_id}_%(id)s.%(ext)s'

      if is_audio:
        ydl_dl_opts.update({
            'format': 'ba/b',
            'outtmpl': filename_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
      else:
        ydl_dl_opts.update({
            'format': (
                'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bestvideo+bestaudio/best'
            ),
            'outtmpl': filename_template,
            'merge_output_format': 'mp4',
        })

      with yt_dlp.YoutubeDL(ydl_dl_opts) as ydl:
        download_info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(download_info)

        if is_audio:
          file_path = os.path.splitext(file_path)[0] + '.mp3'
        elif not file_path.endswith('.mp4'):
          # التأكد من امتداد الملف بعد عملية الدمج
          base_path = os.path.splitext(file_path)[0]
          if os.path.exists(base_path + '.mp4'):
            file_path = base_path + '.mp4'

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
    if file_path:
      # حذف الملف الأساسي أو الملف بطلب امتداد mp3/mp4 لتفادي تراكم المساحة
      base_path = os.path.splitext(file_path)[0]
      for ext in ['', '.mp3', '.mp4', '.webm', '.m4a']:
        target_file = (
            base_path + ext if not file_path.endswith(ext) else file_path
        )
        if os.path.exists(target_file):
          try:
            os.remove(target_file)
          except Exception as clean_err:
            print(f'Cleanup Error: {clean_err}')


print('Smart Downloader Bot is running...')
bot.remove_webhook()
bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)
