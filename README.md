# MarketingBriefBot

A mobile-first Telegram bot for curated professional reading and active learning.

## v0.6 — Article Intelligence

### What changed
- Public article pages are now fetched and parsed for readable context.
- The bot stores a content status for every article:
  - `full`
  - `partial`
  - `metadata_only`
- Recommendation cards display what level of article context The Brief actually has.
- Classification now uses word-boundary matching, so `AI` no longer matches words such as `campaign`.
- Topic classification and recommendation reasoning use headline + description + available article text.
- GPT-5.6 Luna is now the code fallback model.
- AI grounding rules are stricter: metadata-only discussions cannot be presented as article claims.

### HBR subscriber workflow
HBR discovery remains automatic. Your HBR login stays in HBR; it is never stored in Railway.

When you share an HBR URL into the Telegram chat:
1. The Brief matches it to the existing article.
2. It starts a private import session.
3. Paste article text or upload a text-based PDF.
4. Use `/finishimport`.
5. The stored article context becomes `full` or `partial` based on what was imported.

The bot does not bypass subscription authentication or redistribute full article text.

### Import commands
- `/finishimport` — finalize pasted/PDF content
- `/cancelimport` — cancel the active import

### Existing commands
- `/today`
- `/saved`
- `/history`
- `/topics`
- `/notes`
- `/refresh`
- `/note`
- `/end`

### Railway variables
- `TELEGRAM_BOT_TOKEN`
- `DATABASE_URL`
- `OPENAI_API_KEY`
- optional `OPENAI_MODEL` (recommended: `gpt-5.6-luna`)


## v0.6.1 — Extraction Integrity

- Article extraction now preserves headings, lists, blockquotes, and paragraphs in document order.
- Word count alone can no longer mark an article as full.
- HBR completeness is deliberately conservative.
- Public HBR sponsored content uses structural + end-of-article signals before receiving a full-context label.
- The regression case for the Fiserv/EY-Parthenon article now captures the "Bringing It to Life" checklist rather than stopping before the list.
