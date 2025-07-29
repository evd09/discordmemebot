import asyncpraw
import random
import re

async def get_meme(reddit, subreddits, keyword, nsfw=False, exclude_ids=None):
    exclude_ids = set(exclude_ids or [])
    """
    Fetches a random image post matching the keyword (including emojis) from provided subreddits.

    Searches both 'hot' and 'best' listings for broader coverage.

    Parameters:
    - reddit: asyncpraw.Reddit client instance
    - subreddits: list of subreddit names to search
    - keyword: search keyword or emoji
    - nsfw: if True, only allow over_18 posts; if False, only allow SFW

    Returns:
    - A Reddit post object, or None if no match found.
    """
    memes = []
    keyword_lower = keyword.lower()

    # Compile a word-boundary regex for alphanumeric keywords
    word_pattern = None
    if re.match(r"^\w+$", keyword_lower):
        word_pattern = re.compile(rf"\b{re.escape(keyword_lower)}\b", re.IGNORECASE)

    # Iterate both 'hot' and 'best' listings
    for listing in ("hot", "best"):
        for sub in subreddits:
            try:
                subreddit = await reddit.subreddit(sub)
                posts = getattr(subreddit, listing)(limit=100)
                async for post in posts:
                    url_lower = post.url.lower()
                    # Filter by image extensions
                    if not url_lower.endswith((".jpg", ".jpeg", ".png", ".gif")):
                        continue
                    # Filter by NSFW flag
                    if nsfw != post.over_18:
                        continue

                    title = post.title
                    title_lower = title.lower()
                    # Title cleaned of punctuation for word matches
                    title_clean = re.sub(r"[^\w\s]", "", title_lower)

                    match = False
                    # Word-boundary match for plain keywords
                    if word_pattern:
                        if word_pattern.search(title_clean) or word_pattern.search(url_lower):
                            match = True
                    # Fallback substring match (for emojis and partials)
                    if not match and keyword_lower in title_lower:
                        match = True

                    if match and post.id not in exclude_ids:
                        memes.append(post)

            except Exception:
                # Skip invalid or inaccessible subreddits
                continue
    # If matching memes found, return one; otherwise, fallback to a random post
    if memes:
        return random.choice(memes)
    # Fallback: fetch any random image post from 'hot'
    fallback = []
    for sub in subreddits:
        try:
            subreddit = await reddit.subreddit(sub)
            async for post in subreddit.hot(limit=50):
                url_lower = post.url.lower()
                if not url_lower.endswith((".jpg", ".jpeg", ".png", ".gif")):
                    continue
                if nsfw != post.over_18:
                    continue
                fallback.append(post)
        except Exception:
            continue
    return random.choice(fallback) if fallback else None
