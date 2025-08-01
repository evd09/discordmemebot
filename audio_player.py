# cogs/audio/audio_player.py

import os
import json
import asyncio
import random
from io import BytesIO
from pathlib import Path
import discord
from discord import FFmpegOpusAudio, opus

from logger_setup import setup_logger

logger = setup_logger("audio", "audio.log")

if not opus.is_loaded():
    for lib in ("libopus.so.0", "libopus.so", "libopus-0.dll"):
        try:
            opus.load_opus(lib)
            logger.info(f"[OPUS] Loaded {lib}")
            break
        except OSError:
            continue
    else:
        logger.error("[OPUS] Could not load libopus — voice will NOT work.")

AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".mp4", ".webm")

class AudioCache:
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.cache: dict[str, BytesIO] = {}

    def load_config(self):
        cfg_path = Path("config.json")
        if cfg_path.exists():
            with cfg_path.open() as f:
                cfg = json.load(f)
            self.max_size = cfg.get("max_cache_size", self.max_size)

    def get(self, path: str) -> BytesIO | None:
        return self.cache.get(path)

    def add(self, path: str, buf: BytesIO):
        if len(self.cache) >= self.max_size:
            oldest = next(iter(self.cache))
            logger.info(f"[CACHE] Evicting {oldest}")
            del self.cache[oldest]
        self.cache[path] = buf

audio_cache = AudioCache()
audio_cache.load_config()

def load_audio(path: str) -> BytesIO:
    with open(path, "rb") as f:
        return BytesIO(f.read())

def preload_audio_clips():
    for folder in ("./sounds/entrances", "./sounds/beeps"):
        for file in Path(folder).glob("*"):
            if file.suffix.lower() in AUDIO_EXTS:
                try:
                    buf = load_audio(str(file))
                    audio_cache.add(str(file), buf)
                    logger.info(f"[CACHE] Preloaded {file.name}")
                except Exception as e:
                    logger.warning(f"[CACHE] Could not preload {file.name}: {e}")

preload_audio_clips()

async def play_clip(
    vc_channel: discord.VoiceChannel,
    file_path: str,
    volume: float = 1.0,
    context=None,
    fallback_label: str = "audio",
    hold_after_play: bool = False,  # Only true for preview/entrance UI
):
    guild = vc_channel.guild
    voice_client = guild.voice_client
    try:
        # 1. Join if not already connected
        if voice_client is None or not voice_client.is_connected():
            voice_client = await vc_channel.connect()
            logger.info("[AUDIO] Joined voice channel, waiting 5s to stabilize…")
            await asyncio.sleep(5)  # Wait for Discord handshake to fully complete

        elif voice_client.channel != vc_channel:
            await voice_client.move_to(vc_channel)
            logger.info("[AUDIO] Moved to voice channel, waiting 5s to stabilize…")
            await asyncio.sleep(5)

        # 2. Stop current playback if needed
        if voice_client.is_playing():
            voice_client.stop()

        # 3. Play audio (from file or buffer)
        buf = None
        try:
            from .audio_queue import audio_cache
            buf = audio_cache.get(file_path)
        except Exception:
            pass

        if buf:
            buf.seek(0)
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(buf, pipe=True), volume=volume
            )
        else:
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(file_path), volume=volume
            )

        voice_client.play(source)

        # 4. Wait for playback to finish
        while voice_client.is_playing():
            await asyncio.sleep(0.25)

        # 5. Only disconnect if requested for UI preview mode!
        if hold_after_play:
            # Used by /entrance preview UI
            pass  # Stay connected for UI or until idle/empty

        # DO NOT disconnect here! Let idle timeout or all-user-leave logic handle it.

    except Exception as e:
        logger.error(f"Failed to play clip: {e}")
        if context:
            try:
                if hasattr(context, "send"):
                    await context.send(f"⚠️ Failed to play {fallback_label}: {e}", ephemeral=True)
                elif hasattr(context, "response"):
                    await context.response.send_message(f"⚠️ Failed to play {fallback_label}: {e}", ephemeral=True)
            except Exception:
                pass
        if voice_client:
            try:
                await voice_client.disconnect(force=True)
            except Exception:
                pass

async def disconnect_voice(guild: discord.Guild):
    vc = guild.voice_client
    if vc and vc.is_connected():
        await vc.disconnect(force=True)
