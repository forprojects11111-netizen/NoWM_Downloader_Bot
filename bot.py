import os
import time
from chanify import Chanify
from flask import Flask, request
import static_ffmpeg
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, Update
import yt_dlp

# --- 1. إعداد FFmpeg ---
try:
  static_ffmpeg.add_paths()
except Exception as e:
  print(f'FFmpeg Warning: {e}')

# --- 2. إعداد المتغيرات ---
TOKEN = os.environ.get('TOKEN')
CHANIFY_KEY = os.environ.get('CHANIFY_KEY')
RENDER_EXTERNAL_URL = os.environ.get(
    'RENDER_EXTERNAL_URL', 'https://nowm-downloader-bot-3-syg0.onrender.com'
)

if not TOKEN:
  raise ValueError('❌ لم يتم العثور على TOKEN!')

bot = telebot.TeleBot(TOKEN)
chanify = Chanify(CHANIFY_KEY) if CHANIFY_KEY else None
user_urls = {}
COOKIE_FILE = 'cookies.txt'

# --- 3. إعدادات yt-dlp المرنة الشاملة لتجاوز الحظر ---
BASE_YTDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'geo_bypass': True,
    'ignoreerrors': True,
    # اختيار أفضل جودة متاحة سواء مدمجة أو منفصلة مع بدائل مرنة
    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
    'user_agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,'
        ' like Gecko) Chrome/122.0.0.0 Safari/537.36'
    ),
    'extractor_args': {
        'youtube': {
            'player_client': ['ios', 'android', 'mweb', 'tv_embedded'],
            'skip': ['hls', 'dash'],
        }
    },
}

if os.path.exists(COOKIE_FILE):
  BASE_YTDL_OPTS['cookiefile'] = COOKIE_FILE

# --- 4. تطبيق Flask ---
app = Flask(__name__)


@app.route('/')
def health_check():
  return 'Bot Service Active'


@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
  if request.headers.get('content-type') == 'application/json':
    json_string = request.get_data().decode('utf-8')
    update = Update.de_json(json_string)
    bot.process_new_updates([update])
    return 'OK', 200
  return 'Forbidden', 403


# --- 5. التعامل مع الرسائل والأوامر ---
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

  status_msg = bot.send_message(
      user_id, '⏳ جاري تحميل وتجهيز الملف من السيرفر...'
  )
  is_audio = call.data == 'dl_audio'
  file_path = None

  try:
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

    with yt_dlp.YoutubeDL(ydl_dl_opts) as ydl:
      info_dict = ydl.extract_info(url, download=True)

      if info_dict:
        title = info_dict.get('title', 'Media_File')
        file_path = ydl.prepare_filename(info_dict)

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
      bot.edit_message_text(
          '❌ تعذر استخراج الفيديو، قد يكون الرابط مقيداً أو غير متاح.',
          user_id,
          status_msg.message_id,
      )

  except Exception as e:
    print(f'Error Details: {e}')
    bot.edit_message_text(
        'حدث خطأ أثناء معالجة الرابط، يرجى التأكد من صحته والمحاولة لاحقاً.',
        user_id,
        status_msg.message_id,
    )

  finally:
    if file_path and os.path.exists(file_path):
      try:
        os.remove(file_path)
      except Exception as clean_err:
        print(f'Cleanup Error: {clean_err}')


# --- 6. تشغيل الـ Webhook والسيرفر ---
if __name__ == '__main__':
  webhook_url = f'{RENDER_EXTERNAL_URL}/{TOKEN}'
  bot.remove_webhook()
  time.sleep(2)
  bot.set_webhook(url=webhook_url)
  print(f'Webhook set to {webhook_url}')

  port = int(os.environ.get('PORT', 10000))
  app.run(host='0.0.0.0', port=port)
