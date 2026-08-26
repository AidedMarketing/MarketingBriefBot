# MarketingBriefBot

A mobile-first Telegram bot that curates professional reading from Harvard Business Review, Marketing Brew, and MIT Sloan Management Review.

## Current release: v0.2 — Real Content

- Railway-hosted Telegram bot
- Railway Postgres persistence
- Live article discovery from the three core publications
- Simple topic classification and relevance scoring
- `/today` recommendation card
- `/refresh` manual source refresh

## Commands

- `/start` — welcome screen
- `/today` — current recommended article
- `/refresh` — scan sources for new article candidates
- `/help` — command list

## Railway variables

- `TELEGRAM_BOT_TOKEN`
- `DATABASE_URL`

The bot token must never be committed to GitHub.
