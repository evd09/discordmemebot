FROM python:3.11-slim

WORKDIR /app

# Copy your application code
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# (Optional but helpful) Ensure logs are unbuffered for real-time output
ENV PYTHONUNBUFFERED=1

# Start the bot
CMD ["python", "-u", "bot.py"]
