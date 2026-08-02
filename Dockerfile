# Koyeb / Railway / Render için Docker ile 7/24 çalıştırma
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
EXPOSE 8000

# TELEGRAM_BOT_TOKEN ortam değişkeni platform panelinden set edilmelidir.
CMD ["python", "bot.py"]
