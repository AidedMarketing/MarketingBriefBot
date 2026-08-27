# MarketingBriefBot

A mobile-first Telegram bot that curates professional reading from Harvard Business Review, Marketing Brew, and MIT Sloan Management Review.

## Current release: v0.4 — Smarter Curation

- Railway-hosted Telegram bot
- Railway Postgres persistence
- Live article discovery from the three core publications
- Article-specific "Why I picked this" reasoning
- Topic-based personalization from 👍 / 👎 feedback
- Publication diversity penalty so one source does not dominate
- Fresh-discovery boost
- Personalized recommendation queue
- Saved reading list and recommendation history
- `/topics` preference summary
- Discussion-room starter

## Commands

- `/start` — welcome screen
- `/today` — next personalized recommendation
- `/saved` — saved reading list
- `/history` — recent recommendations
- `/topics` — what The Brief is learning about your interests
- `/refresh` — scan sources and refresh recommendation metadata
- `/help` — command list

## Recommendation buttons

- 📖 Read Article
- 🔖 Save
- 👍 More Like This
- 👎 Less Like This
- 💬 Discuss

## Railway variables

- `TELEGRAM_BOT_TOKEN`
- `DATABASE_URL`

The bot token must never be committed to GitHub.
