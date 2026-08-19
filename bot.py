import asyncio
from flask import Flask, request
import os
import static_ffmpeg
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, Update
import time
import yt_dlp

# --- 1. إعداد FFmpeg ---
try:
  static_ffmpeg.add_paths()
except Exception as e:
  print(f'FFmpeg Warning: {e}')

# --- 2. إعداد المتغيرات ---
TOKEN = os.environ.get('TOKEN')
AD_DIRECT_LINK = os.environ.get('AD_DIRECT_LINK', '')
RENDER_EXTERNAL_URL = os.environ.get(
    'RENDER_EXTERNAL_URL', 'https://nowm-downloader-bot-3-syg0.onrender.com'
)

if not TOKEN:
  raise ValueError('❌ لم يتم العثور على TOKEN!')

bot = telebot.TeleBot(TOKEN)
user_urls = {}
# مجموعة لتتبع المستخدمين المطلوب منهم مشاهدة الإعلان للتحميل القادم
pending_ad_users = set()

COOKIE_FILE = 'cookies.txt'

# --- 3. إعدادات yt-dlp ---
BASE_YTDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'geo_bypass': True,
    'ignoreerrors': False,
    'format': 'b/best/bv*+ba',
    'format_sort': ['res', 'ext:mp4:m4a'],
    'user_agent': (
        'Mozilla/5.0 (SmartHUB; SMART-TV; U; Linux/SmartTV) AppleWebKit/537.42'
        ' (KHTML, like Gecko) SmartTV Safari/537.42'
    ),
    'extractor_args': {
        'youtube': {
            'player_client': ['tv', 'ios'],
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
      'مرحباً بك! أرسل رابط فيديو من يوتيوب أو تيك توك لتنزيله كـ فيديو أو'
      ' صوت MP3.',
  )


# إلغاء الحظر عند الضغط على زر التفعيل بعد الإعلان
@bot.callback_query_handler(func=lambda call: call.data == 'unlock_bot')
def handle_unlock(call):
  user_id = call.message.chat.id
  pending_ad_users.discard(user_id)
  bot.answer_callback_query(
      call.id, '✅ تم فتح التنزيل! يمكنك الآن إرسال رابط جديد.'
  )
  bot.send_message(user_id, '🔓 تم فتح البوت بنجاح! أرسل الرابط الجديد الآن.')


@bot.message_handler(func=lambda message: True)
def handle_message(message):
  user_id = message.chat.id
  url = message.text.strip()

  # فحص ما إذا كان المستخدم مجبراً على زيارة الإعلان أولاً
  if user_id in pending_ad_users and AD_DIRECT_LINK:
    markup = InlineKeyboardMarkup()
    btn_ad = InlineKeyboardButton(
        '📢 اضغط هنا لزيارة الإعلان والفتح', url=AD_DIRECT_LINK
    )
    btn_unlock = InlineKeyboardButton(
        '🔓 فتح التحميل بعد الزيارة', callback_data='unlock_bot'
    )
    markup.add(btn_ad)
    markup.add(btn_unlock)

    bot.reply_to(
        message,
        '⚠️ **عذراً! لاستخدام البوت وتحميل فيديو آخر:**\n\n1️⃣ اضغط على زر'
        ' الإعلان بالأسفل.\n2️⃣ بعد فتح الإعلان، اضغط على زر "🔓 فتح التحميل'
        ' بعد الزيارة".',
        reply_markup=markup,
        parse_mode='Markdown',
    )
    return

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
          'format': 'ba/ba*/best',
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

      # إعداد أزرار الإعلان وفتح التحميل القادم
      ad_markup = None
      if AD_DIRECT_LINK:
        ad_markup = InlineKeyboardMarkup()
        ad_btn = InlineKeyboardButton(
            '🎁 اضغط هنا لدعم البوت والإعلان', url=AD_DIRECT_LINK
        )
        unlock_btn = InlineKeyboardButton(
            '🔓 فتح التحميل القادم', callback_data='unlock_bot'
        )
        ad_markup.add(ad_btn)
        ad_markup.add(unlock_btn)

      with open(file_path, 'rb') as f:
        if is_audio:
          bot.send_audio(
              user_id,
              f,
              title=title,
              performer='Downloader Bot',
              caption=(
                  f'🎵 **{title}**\n\n⚠️ *للتحميل المرة القادمة، يرجى الضغط على'
                  ' زر الإعلان أسفله ثم الضغط على فتح التحميل القادم.*'
              ),
              parse_mode='Markdown',
              reply_markup=ad_markup,
          )
        else:
          bot.send_video(
              user_id,
              f,
              caption=(
                  f'🎥 **{title}**\n\n⚠️ *للتحميل المرة القادمة، يرجى الضغط على'
                  ' زر الإعلان أسفله ثم الضغط على فتح التحميل القادم.*'
              ),
              parse_mode='Markdown',
              reply_markup=ad_markup,
          )

      bot.delete_message(user_id, status_msg.message_id)

      # إضافة المستخدم للانتظار المرة القادمة
      if AD_DIRECT_LINK:
        pending_ad_users.add(user_id)

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
