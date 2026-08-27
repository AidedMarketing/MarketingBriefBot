# MarketingBriefBot

A mobile-first Telegram bot that curates professional reading from Harvard Business Review, Marketing Brew, and MIT Sloan Management Review.

## Current release: v0.3 — Interaction & Learning

- Railway-hosted Telegram bot
- Railway Postgres persistence
- Live article discovery from the three core publications
- Topic classification and relevance scoring
- Personalized recommendation queue
- Recommendations are not repeatedly delivered
- Save articles for later
- More Like This / Less Like This feedback
- Topic preferences influence future recommendations
- Recommendation history
- Discussion-room starter

## Commands

- `/start` — welcome screen
- `/today` — next personalized recommendation
- `/saved` — saved reading list
- `/history` — recent recommendations
- `/refresh` — scan sources for new article candidates
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
