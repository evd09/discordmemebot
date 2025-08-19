import logging
from asyncpraw.models import Submission
from html import unescape
from discord import Embed
from typing import Optional
from discord.ext.commands import Context
from urllib.parse import urlparse
import discord
import re

log = logging.getLogger(__name__)

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif")

async def send_meme(
    ctx: Context,
    url: str,
    *,
    content: Optional[str] = None,
    embed: Optional[Embed] = None,
):
    """Send a meme to Discord.

    Images are sent as an embed with the image attached. For other URLs
    (e.g., videos), the URL is included in the message content so Discord
    can generate its own preview.
    """
    # Some Reddit image URLs include query parameters (e.g. ``.jpg?width=640``)
    # which would cause a simple ``endswith`` check to fail. Parse the URL and
    # inspect only the path so such URLs are still treated as images.
    is_image = urlparse(url).path.lower().endswith(IMAGE_EXT)

    # If this is an image, attach it to the embed; otherwise, fall back to
    # sending the URL directly so Discord can unfurl videos/gifs.
    if embed and is_image:
        embed.set_image(url=url)
        text = content
    else:
        text = f"{content}\n{url}" if content else url
        if not is_image:
            embed = None

    if getattr(ctx, "interaction", None) and not ctx.interaction.response.is_done():
        try:
            await ctx.interaction.response.defer()
        except discord.errors.NotFound:
            pass

    if getattr(ctx, "interaction", None):
        try:
            return await ctx.interaction.followup.send(content=text, embed=embed)
        except discord.errors.NotFound:
            log.warning("Interaction expired; falling back to channel.send")
            if getattr(ctx, "channel", None):
                return await ctx.channel.send(content=text, embed=embed)
            return

    return await ctx.send(content=text, embed=embed)

def get_image_url(post: Submission) -> str:
    url = post.url
    log.debug("get_image_url: id=%s url=%s", post.id, url)

    for media_attr in ("media", "secure_media"):
        media = getattr(post, media_attr, None)
        if media and (rv := media.get("reddit_video")):
            fallback = rv.get("fallback_url")
            if fallback:
                log.debug(
                    "Using %s reddit_video fallback for post.id=%s: %s",
                    media_attr,
                    post.id,
                    fallback,
                )
                return fallback

    if url.lower().endswith(".gif"):
        log.debug("Matched .gif directly for post.id=%s", post.id)
        return url

    try:
        variants = post.preview["images"][0].get("variants", {})
        if "gif" in variants:
            gif_url = variants["gif"]["source"]["url"]
            log.debug("Using GIF variant %s for post.id=%s", gif_url, post.id)
            return gif_url
        if "mp4" in variants:
            mp4_url = variants["mp4"]["source"]["url"]
            log.debug("Using MP4 variant %s for post.id=%s", mp4_url, post.id)
            return mp4_url
    except Exception as e:
        log.debug("No usable preview variants for post.id=%s: %s", post.id, e)

    for embed_attr in ("secure_media_embed", "media_embed"):
        embed = getattr(post, embed_attr, None)
        if embed and (content := embed.get("content")):
            match = re.search(r'src=["\']([^"\']+)', content)
            if match:
                embed_url = match.group(1)
                log.debug(
                    "Using %s embed src for post.id=%s: %s",
                    embed_attr,
                    post.id,
                    embed_url,
                )
                return embed_url

    if url.lower().endswith(IMAGE_EXT):
        log.debug("Using image extension URL for post.id=%s: %s", post.id, url)
        return url

    try:
        preview_url = post.preview["images"][0]["source"]["url"]
        log.debug("Using fallback preview image for post.id=%s: %s", post.id, preview_url)
        return preview_url
    except Exception as e:
        log.warning("No valid image for post.id=%s – falling back to post.url: %s", post.id, e)
        return url

def get_reddit_url(url: str) -> str:
    """Return the original Reddit URL suitable for Discord embeds.

    This function used to proxy Reddit media through ``rxddit.com``, which
    prevented Discord from displaying images or videos. The proxying has been
    removed so the original Reddit URL is used directly.
    """
    log.debug("get_reddit_url input=%s", url)
    return url

async def extract_post_data(post):
    if hasattr(post, "load"):
        try:
            await post.load()
        except Exception as e:
            log.debug("post.load() failed for post.id=%s: %s", getattr(post, "id", "?"), e)
    try:
        raw_url = get_image_url(post)
        media_url = unescape(raw_url)
    except Exception as e:
        log.warning("Failed to resolve media_url for post.id=%s: %s", post.id, e)
        media_url = post.url

    return {
        "post_id": post.id,
        "subreddit": post.subreddit.display_name,
        "title": post.title,
        "url": post.url,
        "media_url": media_url,
        "author": str(post.author) if post.author else "[deleted]",
        "is_nsfw": post.over_18,
        "created_utc": int(post.created_utc),
    }
