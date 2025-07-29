# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- New `/r_` command to fetch memes from a specific subreddit with optional keyword filtering.
- User notification messages when Reddit API rate limits cause delays.
- Exponential backoff and retry logic for Reddit API calls to improve reliability.
- Enhanced media URL extraction supporting galleries, videos, `.gifv` conversion, and various media formats.
- Cache management with automatic pruning to improve performance and reduce API calls.
- `/topreactions` command to show the top 5 memes based on reaction counts.
- Reaction tracking and storage for meme messages to support leaderboard features.

### Changed

- Updated meme fetching logic to respect API rate limits and avoid recently seen posts.
- Improved error handling across all commands for better user feedback.
- Commands now notify users when the bot is waiting due to Reddit API rate limits.
- Added detailed debug logging for subreddit validation and meme fetching steps.

### Fixed

- Fixed indentation and syntax errors causing extension load failures.
- Corrected command error handling to prevent crashes during API failures.

### Removed

- Deprecated old meme fetching methods without rate limit awareness.

## File Structure Changes

- `cogs/meme.py`:  
  Contains the main Cog with all meme commands (`/meme`, `/nsfwmeme`, `/r_`, `/topreactions`), API rate limiting, reaction tracking, and caching logic.  
  **Place this file inside the `cogs` folder.**

- `bot.py`:  
  Entry point for the bot, responsible for loading cogs and initializing the Discord bot client.

- `meme_stats.py`:  
  Helper module for reaction tracking and meme message registration (existing or new as per your setup).

## Installation & Usage Notes

- Ensure you have a `cogs` folder and place `meme.py` inside it.
- Provide Reddit API credentials via environment variables:
  - `REDDIT_CLIENT_ID`
  - `REDDIT_CLIENT_SECRET`
- Optionally maintain a `subreddits.json` file for custom subreddit lists.
- The bot now respects Reddit API rate limits automatically and informs users of any delays.
