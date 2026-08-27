# MarketingBriefBot

A mobile-first Telegram bot for curated professional reading and active learning.

## v0.5 — AI Discussion + Learning Notes

The Brief now supports persistent article-linked discussion sessions.

### New in v0.5
- Tap **💬 Discuss** to start a conversation tied to one article
- Normal Telegram messages continue that discussion
- Conversation history persists in Postgres
- The AI is instructed not to invent article details it cannot see
- If article context is insufficient, it asks for the relevant excerpt
- `/note` creates and saves a compact learning note
- `/notes` shows recent saved learning notes
- `/end` closes the active discussion
- AI provider logic is isolated in `ai_provider.py`

### Railway variables
Required:
- `TELEGRAM_BOT_TOKEN`
- `DATABASE_URL`

For AI discussion:
- `OPENAI_API_KEY`
- optional `OPENAI_MODEL` (defaults to `gpt-5.4-mini`)

Never commit secrets to GitHub.

### Important content behavior
The bot does not bypass publication paywalls. Its AI discussion is grounded in the article metadata/context the app has access to plus anything the user shares in the discussion. When context is insufficient, it should ask for an excerpt instead of pretending to know the article.
