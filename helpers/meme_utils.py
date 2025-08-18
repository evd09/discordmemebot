import logging, io, aiohttp
from urllib.parse import urlparse
from asyncpraw.models import Submission
from html import unescape
from discord import File
from discord import Embed
from typing import Optional
from discord.ext.commands import Context

log = logging.getLogger(__name__)

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif")

async def send_meme(
    ctx: Context,
    url: str,
    *,
    content: Optional[str] = None,
    embed: Optional[Embed] = None,
):
    """
    If embed is provided, set its image to `url` and send (embed + optional content).
    Otherwise just send the raw link (with optional content above it).
    """
    # 1) ACK within 3s
    if not ctx.interaction.response.is_done():
        await ctx.interaction.response.defer()

    # 2) Send either embed or plain link
    if embed:
        embed.set_image(url=url)
        return await ctx.interaction.followup.send(content=content, embed=embed)
    else:
        text = f"{content}\n{url}" if content else url
        log.debug("🔥 send_meme (plain link) → %s", text)
        return await ctx.interaction.followup.send(content=text)

def get_image_url(post: Submission) -> str:
    url = post.url
    log.debug("get_image_url: id=%s url=%s", post.id, url)

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

def get_rxddit_url(url: str) -> str:
    log.debug("get_rxddit_url input=%s", url)
    parsed = urlparse(url)
    host, path = parsed.netloc.lower(), parsed.path.lstrip("/")

    if host in ("i.redd.it", "external-preview.redd.it"):
        proxied = f"https://i.rxddit.com/{path}"
        log.debug("Proxied image URL=%s", proxied)
        return proxied

    if host == "v.redd.it":
        proxied = f"https://v.rxddit.com/{path}"
        log.debug("Proxied video URL=%s", proxied)
        return proxied

    return url

def extract_post_data(post):
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
        "created_utc": int(post.created_utc)
    }