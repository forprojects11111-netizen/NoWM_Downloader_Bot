import os
import re
from threading import Thread
from chanify import Chanify
from flask import Flask
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
import yt_dlp

# --- 1. خادم Flask لتشغيل البوت على Web Service مجاناً في Render ---
app = Flask(__name__)


@app.route("/")
def health_check():
  return "Bot is running fine!"


def run_server():
  port = int(os.environ.get("PORT", 8080))
  app.run(host="0.0.0.0", port=port)


Thread(target=run_server, daemon=True).start()

# --- 2. إعدادات بوت التلجرام ---
# قراءة التوكن من متغيرات البيئة في Render لتجنب تعارض القيم
TOKEN = os.environ.get("TOKEN")

if not TOKEN:
  print("❌ Error: TOKEN environment variable is not set in Render!")
  exit(1)

chanify = Chanify("chanify_live_df1f606b9f906b53f1")
bot = telebot.TeleBot(TOKEN)

user_urls = {}


def clean_filename(title):
  return re.sub(r'[\\/*?:"<>|]', "", title)


@bot.message_handler(commands=["start"])
def send_welcome(message):
  bot.reply_to(
      message,
      "مرحباً بك! أرسل رابط فيديو من يوتيوب أو تيك توك لتنزيله كـ فيديو أو صوت"
      " MP3.",
  )


@bot.message_handler(func=lambda message: True)
def handle_message(message):
  user_id = message.chat.id
  url = message.text.strip()

  if not url.startswith("http"):
    bot.reply_to(message, "الرجاء إرسال رابط صحيح.")
    return

  user_urls[user_id] = url

  markup = InlineKeyboardMarkup()
  btn_video = InlineKeyboardButton("تنزيل كـ فيديو 🎥", callback_data="dl_video")
  btn_audio = InlineKeyboardButton(
      "تنزيل كـ صوت MP3 🎵", callback_data="dl_audio"
  )
  markup.add(btn_video, btn_audio)

  bot.reply_to(message, "اختر نوع التنزيل المطلوب:", reply_markup=markup)


@bot.callback_query_handler(
    func=lambda call: call.data in ["dl_video", "dl_audio"]
)
def handle_download_choice(call):
  user_id = call.message.chat.id
  url = user_urls.get(user_id)

  if not url:
    bot.send_message(user_id, "حدث خطأ، يرجى إعادة إرسال الرابط.")
    return

  bot.answer_callback_query(call.id, "جاري فحص الرابط ومعالجته...")

  try:
    chanify.show_ad(chat_id=user_id)
  except Exception as e:
    print(f"Chanify Error: {e}")

  status_msg = bot.send_message(
      user_id, " 🔍 جاري فحص الملف ومعرفة الحجم..."
  )

  is_audio = call.data == "dl_audio"
  is_tiktok = "tiktok.com" in url.lower()

  try:
    ydl_info_opts = {"quiet": True}
    with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
      info = ydl.extract_info(url, download=False)
      title = info.get("title", "Media_File")
      filesize = info.get("filesize") or info.get("filesize_approx") or 0
      filesize_mb = filesize / (1024 * 1024) if filesize else 0

    if filesize_mb > 50 and not is_tiktok:
      bot.edit_message_text(
          f"⚠️ **حجم الملف كبير ({filesize_mb:.1f} MB)** ويتجاوز حد الـ 50MB"
          " للرفع المباشر.\nجاري استخراج رابط تنزيل مباشر للمتصفح...",
          user_id,
          status_msg.message_id,
          parse_mode="Markdown",
      )

      ydl_direct_opts = {
          "format": "bestaudio/best" if is_audio else "best",
          "quiet": True,
      }
      with yt_dlp.YoutubeDL(ydl_direct_opts) as ydl:
        direct_info = ydl.extract_info(url, download=False)
        direct_url = direct_info.get("url")

      if direct_url:
        markup = InlineKeyboardMarkup()
        label = "الصوت (MP3)" if is_audio else "الفيديو"
        dl_btn = InlineKeyboardButton(
            f"📥 اضغط هنا لتنزيل {label} مباشرة", url=direct_url
        )
        markup.add(dl_btn)

        clean_title = clean_filename(title)

        bot.send_message(
            user_id,
            f"📌 **اسم المقطع الأصلي (اضغط عليه للنسخ):**\n`{clean_title}`\n\n⚙️"
            f" **الحجم:** {filesize_mb:.1f} MB\n👇 اضغط على الزر أدناه للبدء في"
            " التنزيل المباشر على هاتفك:",
            parse_mode="Markdown",
            reply_markup=markup,
        )
        bot.delete_message(user_id, status_msg.message_id)
      else:
        bot.send_message(user_id, "تعذر استخراج رابط التنزيل المباشر.")

    else:
      bot.edit_message_text(
          "⏳ جاري تحميل وتجهيز الملف بالاسم الأصلي...",
          user_id,
          status_msg.message_id,
      )

      if is_audio:
        ydl_dl_opts = {
            "format": "bestaudio/best",
            "outtmpl": "downloads/%(title)s.%(ext)s",
            "quiet": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
      else:
        ydl_dl_opts = {
            "format": "best[ext=mp4]/best",
            "outtmpl": "downloads/%(title)s.%(ext)s",
            "quiet": True,
        }

      with yt_dlp.YoutubeDL(ydl_dl_opts) as ydl:
        download_info = ydl.extract_info(url, download=True)

        if is_audio:
          file_path = ydl.prepare_filename(download_info)
          file_path = os.path.splitext(file_path)[0] + ".mp3"
        else:
          file_path = ydl.prepare_filename(download_info)

      if os.path.exists(file_path):
        bot.edit_message_text(
            "📤 جاري رفع الملف إلى محادثتك...", user_id, status_msg.message_id
        )

        with open(file_path, "rb") as f:
          if is_audio:
            bot.send_audio(
                user_id,
                f,
                title=title,
                performer="Bot Downloader",
                caption=(
                    f"🎵 **{title}**\n\nاضغط على (⋮) ثم 'حفظ في الموسيقى'"
                    " لتجده بالاسم الأصلي داخل جهازك."
                ),
                parse_mode="Markdown",
            )
          else:
            bot.send_video(
                user_id,
                f,
                caption=(
                    f"🎥 **{title}**\n\nاضغط على (⋮) ثم 'حفظ في المعرض'."
                ),
                parse_mode="Markdown",
            )

        os.remove(file_path)
        bot.delete_message(user_id, status_msg.message_id)
      else:
        bot.send_message(user_id, "تعذر العثور على الملف بعد المعالجة.")

  except Exception as e:
    print(f"Error: {e}")
    bot.send_message(
        user_id, "حدث خطأ أثناء معالجة الرابط، يرجى المحاولة لاحقاً."
    )


print("Smart Downloader Bot is running...")
bot.infinity_polling()
