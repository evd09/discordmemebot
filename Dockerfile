FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

# Use unbuffered mode to ensure logs appear in real-time
CMD ["python", "-u", "bot.py"]
