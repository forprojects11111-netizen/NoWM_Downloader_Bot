FROM python:3.10-slim

# ضبط متغيرات البيئة لمنع تخزين المخرجات في الذاكرة المؤقتة (Logs)
ENV PYTHONUNBUFFERED=1

# تثبيت الحزم الأساسية ونظام FFmpeg للميديا
RUN apt-get update && apt-get install -y ffmpeg git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# نسخ التبعيات وتثبيتها مع تحديث pip
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# توثيق المنفذ الخاص بخادم Flask الحافظ للاتصال
EXPOSE 8080

CMD ["python", "bot.py"]
