FROM python:3.11-slim

# ── Install FFmpeg + Opus support ──
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg \
      libopus0 \
      opus-tools \
      git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Pre-create sounds directory with permissive permissions ──
RUN mkdir -p /app/sounds \
    && chmod 777 /app/sounds

# ── Create non-root user with configurable UID/GID ──
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID app && useradd -u $UID -g app -m app
RUN chown -R app:app /app/sounds
USER app

# ── Copy & install Python deps ──
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir "git+https://github.com/Rapptz/discord.py#egg=discord.py[voice]"

ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "-m", "memer.bot"]
